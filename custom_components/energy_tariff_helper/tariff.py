"""Tariff schedule engine.

Pure time logic: building windows from stored data, matching an instant against
them, and selecting the active window. No Home Assistant entity or coordinator
code lives here so the behaviour is testable in isolation.

Import and export tariffs are independent schedules, so a window carries a
single rate rather than a pair.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Window fields as stored on a subentry (and in the migrated options format).
FIELD_START = "start"
FIELD_END = "end"
FIELD_RATE = "rate"

# Fields of the pre-split format, used only for migration.
_LEGACY_FIELD_IMPORT_RATE = "import_rate"
_LEGACY_FIELD_EXPORT_RATE = "export_rate"


@dataclass(frozen=True, slots=True)
class TariffWindow:
    """A recurring daily tariff window for one direction.

    ``start`` is inclusive, ``end`` is exclusive. A window whose ``start`` is
    later than its ``end`` spans midnight (e.g. 23:00-07:00).
    """

    start: time
    end: time
    rate: float

    @property
    def spans_midnight(self) -> bool:
        """Return True if the window wraps past midnight."""
        return self.start > self.end

    def as_dict(self) -> dict[str, Any]:
        """Return the storable representation."""
        return {
            FIELD_START: self.start.strftime("%H:%M"),
            FIELD_END: self.end.strftime("%H:%M"),
            FIELD_RATE: self.rate,
        }

    @property
    def label(self) -> str:
        """Return a short human label, used as the subentry title."""
        return f"{self.start:%H:%M}-{self.end:%H:%M} ({self.rate:g})"


def _parse_time(value: Any) -> time:
    """Parse a stored time value into a ``datetime.time``."""
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def window_from_dict(raw: Any) -> TariffWindow | None:
    """Build a window from a stored mapping, or None when unusable."""
    if not isinstance(raw, Mapping):
        return None
    try:
        start = _parse_time(raw[FIELD_START])
        end = _parse_time(raw[FIELD_END])
        rate = float(raw[FIELD_RATE])
    except (KeyError, TypeError, ValueError):
        return None
    if start == end:
        return None
    return TariffWindow(start=start, end=end, rate=rate)


def parse_windows(raw: Any) -> list[TariffWindow]:
    """Build windows from a stored list of mappings.

    Invalid or unusable entries are skipped with a warning rather than raising,
    so bad data can never take the sensors down. Order is preserved, which is
    what defines precedence on overlap.
    """
    if not raw:
        return []

    if not isinstance(raw, list):
        _LOGGER.warning("Tariff windows must be a list; treating as empty")
        return []

    windows: list[TariffWindow] = []
    for entry in raw:
        window = window_from_dict(entry)
        if window is None:
            _LOGGER.warning("Skipping unusable tariff window: %r", entry)
            continue
        windows.append(window)
    return windows


def split_legacy_windows(raw: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the pre-split combined format into import and export window lists.

    The oldest format stored a JSON string of windows each carrying both an
    ``import_rate`` and an ``export_rate``. Returns ``(import_windows,
    export_windows)`` in the current storable format.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            _LOGGER.warning("Legacy tariff windows are not valid JSON; discarding")
            return [], []

    if not isinstance(raw, list):
        return [], []

    import_windows: list[dict[str, Any]] = []
    export_windows: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            start = _parse_time(entry[FIELD_START])
            end = _parse_time(entry[FIELD_END])
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning("Skipping malformed legacy window: %r", entry)
            continue
        if start == end:
            continue
        base = {FIELD_START: start.strftime("%H:%M"), FIELD_END: end.strftime("%H:%M")}
        for field, target in (
            (_LEGACY_FIELD_IMPORT_RATE, import_windows),
            (_LEGACY_FIELD_EXPORT_RATE, export_windows),
        ):
            try:
                target.append({**base, FIELD_RATE: float(entry[field])})
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning("Legacy window missing %s: %r", field, entry)

    _LOGGER.info(
        "Migrated legacy tariff windows: %s import, %s export",
        len(import_windows),
        len(export_windows),
    )
    return import_windows, export_windows


def window_matches(window: TariffWindow, t: time) -> bool:
    """Return True if ``t`` falls inside ``window``."""
    if window.spans_midnight:
        return t >= window.start or t < window.end
    return window.start <= t < window.end


def active_window(windows: list[TariffWindow], t: time) -> TariffWindow | None:
    """Return the window in effect at ``t``.

    When windows overlap the earliest-listed match wins. Returns ``None`` when
    nothing matches; callers then fall back to the default rate.
    """
    for window in windows:
        if window_matches(window, t):
            return window
    return None