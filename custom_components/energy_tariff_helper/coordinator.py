"""DataUpdateCoordinator for the Energy Tariff Helper integration.

Owns the one-minute tick that re-evaluates which tariff window is active for
each direction. Import and export schedules are independent. No network I/O
happens here: ``_async_update_data`` is a pure recompute, so it can never fail.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DEFAULT_RATE, DOMAIN
from .tariff import TariffWindow, active_window

UPDATE_INTERVAL = timedelta(minutes=1)

_LOGGER = logging.getLogger(__name__)


class TariffCoordinator(DataUpdateCoordinator[None]):
    """Recomputes the active tariff once a minute."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        import_windows: list[TariffWindow],
        export_windows: list[TariffWindow],
        supply_charge: float,
        start_date: date,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN} {entry.entry_id}",
            update_interval=UPDATE_INTERVAL,
        )
        self.import_windows = import_windows
        self.export_windows = export_windows
        self.supply_charge = supply_charge
        self.start_date = start_date

    async def _async_update_data(self) -> None:
        """Recompute the active windows.

        Entities read the properties below, so there is nothing to return.
        """
        return None

    def async_set_windows(
        self,
        import_windows: list[TariffWindow],
        export_windows: list[TariffWindow],
    ) -> None:
        """Replace both schedules and push fresh state to listeners."""
        self.import_windows = import_windows
        self.export_windows = export_windows
        self.async_set_updated_data(None)

    def async_set_supply_charge(self, supply_charge: float) -> None:
        """Update the daily supply charge and push fresh state."""
        self.supply_charge = supply_charge
        self.async_set_updated_data(None)

    @property
    def active_import(self) -> TariffWindow | None:
        """Return the import window in effect right now, if any."""
        return active_window(self.import_windows, dt_util.now().time())

    @property
    def active_export(self) -> TariffWindow | None:
        """Return the export window in effect right now, if any."""
        return active_window(self.export_windows, dt_util.now().time())

    @property
    def import_rate(self) -> float:
        """Return the current import rate in currency/kWh."""
        window = self.active_import
        return window.rate if window else DEFAULT_RATE

    @property
    def export_rate(self) -> float:
        """Return the current export rate in currency/kWh."""
        window = self.active_export
        return window.rate if window else DEFAULT_RATE

    @property
    def days_elapsed(self) -> int:
        """Return whole days since setup, clamped to never go negative."""
        return max(0, (dt_util.now().date() - self.start_date).days)

    @property
    def supply_charge_total(self) -> float:
        """Return the cumulative supply charge since setup.

        Monotonically non-decreasing for a fixed charge, which is what a
        cumulative (TOTAL) statistic requires.
        """
        return self.days_elapsed * self.supply_charge
