"""DataUpdateCoordinator for the Energy Tariff Helper integration.

Owns the one-minute tick that re-evaluates which tariff window is active for
each direction and folds the daily supply charge into the accrual ledger.
Import and export schedules are independent. No network I/O happens here:
``_async_update_data`` is a pure recompute, so it can never fail.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DEFAULT_RATE, DOMAIN
from .tariff import GstSettings, TariffWindow, active_window

UPDATE_INTERVAL = timedelta(minutes=1)

# How often the accrual ledger must hit disk. A crash window costs nothing: the
# ledger is timestamp based, so the gap is rebuilt from the persisted timestamp.
SAVE_INTERVAL = timedelta(minutes=15)

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
        store: Store[dict[str, Any]],
        accrued_total: float,
        accrued_through: datetime,
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
        self.gst = gst or GstSettings()
        self._store = store
        self.accrued_total = accrued_total
        self.accrued_through = accrued_through

    async def _async_update_data(self) -> None:
        """Fold outstanding accrual into the ledger.

        Entities read the properties below, so there is nothing to return.
        """
        self._fold_accrual()
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
    def supply_charge_total(self) -> float:
        """Return the supply charge accrued since setup.

        The charge accrues continuously at the current daily rate and past
        accrual is never rewritten, so the value is monotonically non-decreasing
        (for a non-negative charge), as a cumulative (TOTAL) statistic requires.
        Changing the supply charge or tax settings only shapes accrual from the
        moment of the change.
        """
        elapsed = (dt_util.now(dt_util.UTC) - self.accrued_through).total_seconds()
        return self.accrued_total + max(0.0, elapsed) / 86400.0 * self.supply_charge

    def _fold_accrual(self) -> None:
        """Fold the accrual accumulated since the last fold into the ledger."""
        now = dt_util.now(dt_util.UTC)
        elapsed = (now - self.accrued_through).total_seconds()
        if elapsed <= 0:
            # Clock skew, or a ledger persisted from the future: let it pass.
            return
        self.accrued_total += elapsed / 86400.0 * self.supply_charge
        self.accrued_through = now
        self._store.async_delay_save(self._store_data, SAVE_INTERVAL.total_seconds())

    def _store_data(self) -> dict[str, Any]:
        """Return the storable ledger."""
        return {
            "accrued_total": self.accrued_total,
            "accrued_through": self.accrued_through.isoformat(),
        }

    async def async_flush_ledger(self) -> None:
        """Fold outstanding accrual and flush the ledger to disk."""
        self._fold_accrual()
        await self._store.async_save(self._store_data())
