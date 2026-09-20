"""The Energy Tariff Helper integration.

Publishes the current electricity import and export tariff rates plus the fixed
daily supply charge as sensors, driven by UI-configured time windows.
"""

from __future__ import annotations

from datetime import date

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXPORT_WINDOWS,
    CONF_IMPORT_WINDOWS,
    CONF_LEGACY_WINDOWS,
    CONF_START_DATE,
    CONF_SUPPLY_CHARGE,
    DOMAIN,
)
from .coordinator import TariffCoordinator
from .tariff import parse_windows, split_legacy_windows

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Tariff Helper from a config entry."""
    options = dict(entry.options)
    migrated = False

    # Split the pre-split combined window format into the two schedules.
    if CONF_IMPORT_WINDOWS not in options and CONF_EXPORT_WINDOWS not in options:
        import_windows, export_windows = split_legacy_windows(
            options.pop(CONF_LEGACY_WINDOWS, None)
        )
        options[CONF_IMPORT_WINDOWS] = import_windows
        options[CONF_EXPORT_WINDOWS] = export_windows
        migrated = True
    options.pop(CONF_LEGACY_WINDOWS, None)

    if CONF_START_DATE not in options:
        # Persist the setup date so the cumulative supply charge total never
        # resets across restarts (required by the TOTAL statistic).
        options[CONF_START_DATE] = dt_util.now().date().isoformat()
        migrated = True

    if migrated:
        hass.config_entries.async_update_entry(entry, options=options)

    coordinator = TariffCoordinator(
        hass,
        entry,
        import_windows=parse_windows(options.get(CONF_IMPORT_WINDOWS)),
        export_windows=parse_windows(options.get(CONF_EXPORT_WINDOWS)),
        supply_charge=options.get(CONF_SUPPLY_CHARGE, 0.0),
        start_date=date.fromisoformat(
            options.get(CONF_START_DATE, dt_util.now().date().isoformat())
        ),
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
    """Rebuild both schedules when options change."""
    coordinator: TariffCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_set_windows(
        parse_windows(entry.options.get(CONF_IMPORT_WINDOWS)),
        parse_windows(entry.options.get(CONF_EXPORT_WINDOWS)),
    )
    coordinator.async_set_supply_charge(entry.options.get(CONF_SUPPLY_CHARGE, 0.0))
