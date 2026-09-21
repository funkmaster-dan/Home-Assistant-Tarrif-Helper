"""DataUpdateCoordinator for the Energy Tariff Helper integration.

Owns the one-minute tick that re-evaluates which tariff window is active for
each direction. Import and export schedules are independent. No network I/O
happens here: ``_async_update_data`` is a pure recompute, so it can never fail.
"""

from __future__ import annotations

import logging
from datetime import date, time as dt_time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DEFAULT_RATE, DOMAIN
from .tariff import GstSettings, TariffWindow, active_window

UPDATE_INTERVAL = timedelta(minutes=1)

# The day's supply charge is applied a little after local midnight rather than
# exactly on it. Home Assistant buckets statistics by UTC hour, which in a
# half-hour-offset timezone (ACST, +09:30) puts a bucket boundary on local
# midnight; an increase landing there is recorded against the previous day, so
# the charge appeared a day late in daily totals. Applying it once the day is
# under way keeps it on the day it belongs to.
DAY_CHARGE_AFTER = dt_time(0, 30)

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
    def billing_date(self) -> date:
        """Return the day whose supply charge is currently in effect.

        Until ``DAY_CHARGE_AFTER`` the previous day is still in effect, so the
        charge for a day is applied once that day is under way rather than on the
        boundary, where it would be recorded against the previous day.
        """
        now = dt_util.now()
        if now.time() < DAY_CHARGE_AFTER:
            return now.date() - timedelta(days=1)
        return now.date()

    @property
    def days_billed(self) -> int:
        """Return the number of days billed, counting the current day.

        The setup day counts as day one even if the integration was added
        partway through it, and the count never decreases.
        """
        return max(1, (self.billing_date - self.start_date).days + 1)

    @property
    def supply_charge_total(self) -> float:
        """Return the cumulative supply charge since setup.

        Monotonically non-decreasing, which is what a cumulative (TOTAL)
        statistic requires.
        """
        return self.days_billed * self.supply_charge
