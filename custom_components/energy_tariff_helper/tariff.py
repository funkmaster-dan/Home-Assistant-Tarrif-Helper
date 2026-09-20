"""Tariff schedule engine.

Pure time logic: parsing the configured window list, matching an instant
against it, and selecting the active window. No Home Assistant entity or
coordinator code lives here so the behaviour is testable in isolation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Window fields as they appear in the configured JSON.
FIELD_START = "start"
FIELD_END = "end"
FIELD_IMPORT_RATE = "import_rate"
FIELD_EXPORT_RATE = "export_rate"


@dataclass(frozen=True, slots=True)
class TariffWindow:
    """A recurring daily tariff window.

    ``start`` is inclusive, ``end`` is exclusive. A window whose ``start`` is
    later than its ``end`` spans midnight (e.g. 23:00-07:00).
    """

    start: time
    end: time
    import_rate: float
    export_rate: float

    @property
    def spans_midnight(self) -> bool:
        """Return True if the window wraps past midnight."""
        return self.start > self.end


def _parse_time(value: Any) -> time:
    """Parse a configured time value into a ``datetime.time``."""
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def parse_windows(raw: str | None) -> list[TariffWindow]:
    """Build windows from the configured JSON string.

    Invalid or unusable entries are skipped with a warning rather than raising,
    so a bad edit can never take the sensors down. Order is preserved, which is
    what defines precedence on overlap.
    """
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except ValueError:
        _LOGGER.warning("Tariff windows are not valid JSON; treating as empty")
        return []

    if not isinstance(parsed, list):
        _LOGGER.warning("Tariff windows must be a JSON list; treating as empty")
        return []

    windows: list[TariffWindow] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            _LOGGER.warning("Skipping tariff window that is not an object: %r", entry)
            continue
        try:
            start = _parse_time(entry[FIELD_START])
            end = _parse_time(entry[FIELD_END])
            import_rate = float(entry[FIELD_IMPORT_RATE])
            export_rate = float(entry[FIELD_EXPORT_RATE])
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning("Skipping malformed tariff window: %r", entry)
            continue

        if start == end:
            _LOGGER.warning(
                "Ignoring zero-length tariff window %s-%s: it can never match",
                start,
                end,
            )
            continue

        windows.append(
            TariffWindow(
                start=start,
                end=end,
                import_rate=import_rate,
                export_rate=export_rate,
            )
        )

    return windows


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
