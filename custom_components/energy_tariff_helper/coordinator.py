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
from .tariff import GstSettings, TariffWindow, active_window

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
        gst: GstSettings | None = None,
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
        self.base_supply_charge = supply_charge
        self.start_date = start_date
        self.gst = gst or GstSettings()

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
        self.base_supply_charge = supply_charge
        self.async_set_updated_data(None)

    def async_set_gst(self, gst: GstSettings) -> None:
        """Update the tax settings and push fresh state."""
        self.gst = gst
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
        """Return the current import rate, with tax applied if enabled."""
        window = self.active_import
        base = window.rate if window else DEFAULT_RATE
        return base * self.gst.import_multiplier()

    @property
    def export_rate(self) -> float:
        """Return the current export rate, with tax applied if enabled."""
        window = self.active_export
        base = window.rate if window else DEFAULT_RATE
        return base * self.gst.export_multiplier()

    @property
    def supply_charge(self) -> float:
        """Return the daily supply charge, with tax applied if enabled."""
        return self.base_supply_charge * self.gst.supply_charge_multiplier()

    @property
    def days_billed(self) -> int:
        """Return the number of days billed, counting the current day.

        The supply charge applies from the start of each day, so the current day
        is included as soon as it begins and the setup day counts as day one
        even though the integration may have been added partway through it.
        """
        return max(1, (dt_util.now().date() - self.start_date).days + 1)

    @property
    def supply_charge_total(self) -> float:
        """Return the cumulative supply charge since setup.

        Monotonically non-decreasing, which is what a cumulative (TOTAL)
        statistic requires.
        """
        return self.days_billed * self.supply_charge
