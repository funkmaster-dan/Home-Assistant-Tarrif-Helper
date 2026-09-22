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
    later than its ``end`` spans midnight (e.g. 23:00-07:00). Equal ``start``
    and ``end`` covers the whole day (a flat tariff).
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
            FIELD_START: self.start.strftime("%H:%M:%S"),
            FIELD_END: self.end.strftime("%H:%M:%S"),
            FIELD_RATE: self.rate,
        }

    def title(self, direction: str, currency: str) -> str:
        """Return the subentry title: direction, times and rate with unit.

        Titles also set the row order on the integration page, so the direction
        prefix groups each schedule together instead of interleaving them.
        """
        when = (
            "all day"
            if self.start == self.end
            else f"{self.start:%H:%M}-{self.end:%H:%M}"
        )
        return f"{direction} {when} · {self.rate:g} {currency}/kWh"


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
        base = {
            FIELD_START: start.strftime("%H:%M:%S"),
            FIELD_END: end.strftime("%H:%M:%S"),
        }
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


@dataclass(frozen=True, slots=True)
class GstSettings:
    """How tax is applied to each tariff component.

    One rate, applied independently to import, export and the daily supply
    charge. Disabled components are left untouched, so a GST-free feed-in tariff
    sits alongside a taxed import rate.
    """

    percent: float = 0.0
    apply_to_import: bool = False
    apply_to_export: bool = False
    apply_to_supply_charge: bool = False

    @property
    def multiplier(self) -> float:
        """Return the multiplier for the configured rate."""
        return 1.0 + self.percent / 100.0

    def import_multiplier(self) -> float:
        """Return the multiplier to apply to import rates."""
        return self.multiplier if self.apply_to_import else 1.0

    def export_multiplier(self) -> float:
        """Return the multiplier to apply to export rates."""
        return self.multiplier if self.apply_to_export else 1.0

    def supply_charge_multiplier(self) -> float:
        """Return the multiplier to apply to the daily supply charge."""
        return self.multiplier if self.apply_to_supply_charge else 1.0


def window_matches(window: TariffWindow, t: time) -> bool:
    """Return True if ``t`` falls inside ``window``."""
    if window.start == window.end:  # covers the whole day
        return True
    if window.spans_midnight:
        return t >= window.start or t < window.end
    return window.start <= t < window.end


def _segments(window: TariffWindow) -> tuple[tuple[time, time], ...]:
    """Return the window as one or two half-open intervals on the day."""
    if window.start == window.end:
        return ((time.min, time.max),)
    if window.spans_midnight:
        return ((window.start, time.max), (time.min, window.end))
    return ((window.start, window.end),)


def windows_overlap(a: TariffWindow, b: TariffWindow) -> bool:
    """Return True if the two windows ever cover the same instant."""
    return any(
        sa < eb and sb < ea for sa, ea in _segments(a) for sb, eb in _segments(b)
    )


def _seconds_since(start: time, t: time) -> int:
    """Return whole seconds from ``start`` to ``t``, wrapping over midnight."""
    def to_seconds(x: time) -> int:
        return x.hour * 3600 + x.minute * 60 + x.second

    return (to_seconds(t) - to_seconds(start)) % 86400


def active_window(windows: list[TariffWindow], t: time) -> TariffWindow | None:
    """Return the window in effect at ``t``.

    When windows overlap, the one that started most recently wins, so a short
    override window beats the broad window it sits inside of no matter what
    order they were created in. Equal starts go to the earliest-listed window.
    Returns ``None`` when nothing matches; callers then fall back to the
    default rate.
    """
    best: TariffWindow | None = None
    best_age = 0
    for window in windows:
        if not window_matches(window, t):
            continue
        age = _seconds_since(window.start, t)
        if best is None or age < best_age:
            best, best_age = window, age
    return best