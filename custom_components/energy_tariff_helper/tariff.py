"""Tariff schedule engine.

Pure time logic: parsing configured windows, matching an instant against them,
and selecting the active window. No Home Assistant entity or coordinator code
lives here so the behaviour is testable in isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import time
from typing import Any

from .const import (
    CONF_END,
    CONF_EXPORT_RATE,
    CONF_IMPORT_RATE,
    CONF_START,
)

_LOGGER = logging.getLogger(__name__)


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
    """Parse a TimeSelector value into a ``datetime.time``."""
    if isinstance(value, time):
        return value
    # TimeSelector submits "HH:MM:SS"; tolerate "HH:MM" too.
    return time.fromisoformat(str(value))


def parse_windows(
    subentries: Iterable[Mapping[str, Any]],
) -> list[TariffWindow]:
    """Build windows from config subentry data.

    Zero-length windows (``start == end``) can never match and are skipped with
    a warning. Order is preserved, which is what defines precedence.
    """
    windows: list[TariffWindow] = []
    for data in subentries:
        start = _parse_time(data[CONF_START])
        end = _parse_time(data[CONF_END])
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
                import_rate=float(data[CONF_IMPORT_RATE]),
                export_rate=float(data[CONF_EXPORT_RATE]),
            )
        )
    return windows


def window_matches(window: TariffWindow, t: time) -> bool:
    """Return True if ``t`` falls inside ``window``."""
    if window.spans_midnight:
        return t >= window.start or t < window.end
    return window.start <= t < window.end


def active_window(windows: Iterable[TariffWindow], t: time) -> TariffWindow | None:
    """Return the window in effect at ``t``.

    When windows overlap the earliest-listed match wins. Returns ``None`` when
    nothing matches; callers then fall back to the default rate.
    """
    for window in windows:
        if window_matches(window, t):
            return window
    return None
