"""The Energy Tariff Helper integration.

Publishes the current electricity import/export tariff rates plus the fixed
daily supply charge as sensors, driven by UI-configured time windows.
"""

from __future__ import annotations

from datetime import date

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_START_DATE,
    CONF_SUPPLY_CHARGE,
    DOMAIN,
)
from .coordinator import TariffCoordinator
from .tariff import parse_windows

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Tariff Helper from a config entry."""
    if CONF_START_DATE not in entry.options:
        # Persist the setup date so the cumulative supply charge total never
        # resets across restarts (required by the TOTAL statistic).
        hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                CONF_START_DATE: dt_util.now().date().isoformat(),
            },
        )

    coordinator = TariffCoordinator(
        hass,
        entry,
        windows=parse_windows(entry.subentries.values()),
        supply_charge=entry.options.get(CONF_SUPPLY_CHARGE, 0.0),
        start_date=date.fromisoformat(entry.options[CONF_START_DATE]),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rebuild the schedule when subentries or options change."""
    coordinator: TariffCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_set_windows(parse_windows(entry.subentries.values()))
    coordinator.async_set_supply_charge(entry.options.get(CONF_SUPPLY_CHARGE, 0.0))
