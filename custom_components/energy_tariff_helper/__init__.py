"""The Energy Tariff Helper integration.

Publishes the current electricity import and export tariff rates plus the fixed
daily supply charge as sensors. Tariff windows are config subentries, one per
window, so the integration page gives add / edit / delete rows for each
direction.
"""

from __future__ import annotations

import logging
from datetime import date
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXPORT_WINDOWS,
    CONF_IMPORT_WINDOWS,
    CONF_LEGACY_WINDOWS,
    CONF_START_DATE,
    CONF_SUPPLY_CHARGE,
    DOMAIN,
    SUBENTRY_TYPE_EXPORT,
    SUBENTRY_TYPE_IMPORT,
)
from .coordinator import TariffCoordinator
from .tariff import TariffWindow, parse_windows, split_legacy_windows, window_from_dict

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

WINDOW_SUBENTRY_TYPES = (SUBENTRY_TYPE_IMPORT, SUBENTRY_TYPE_EXPORT)


def _has_subentries(entry: ConfigEntry, subentry_type: str) -> bool:
    """Return True if any subentry of this type exists."""
    return any(
        subentry.subentry_type == subentry_type
        for subentry in entry.subentries.values()
    )


def windows_for(entry: ConfigEntry, subentry_type: str) -> list[TariffWindow]:
    """Return the configured windows of one direction, in subentry order."""
    windows: list[TariffWindow] = []
    for subentry in entry.subentries.values():
        if subentry.subentry_type != subentry_type:
            continue
        window = window_from_dict(subentry.data)
        if window is None:
            _LOGGER.warning(
                "Ignoring unusable %s subentry %s: %r",
                subentry_type,
                subentry.subentry_id,
                dict(subentry.data),
            )
            continue
        windows.append(window)
    return windows


def _migrate_windows_to_subentries(
    hass: HomeAssistant, entry: ConfigEntry, options: dict
) -> bool:
    """Move windows out of the options and into subentries.

    Handles both earlier storage formats: the oldest one JSON string carrying
    both rates, and the follow-up pair of per-direction lists. Returns True when
    the options were changed and need writing back.
    """
    changed = False

    # Oldest format: one JSON string holding both rates.
    if (legacy := options.pop(CONF_LEGACY_WINDOWS, None)) is not None:
        changed = True
        if CONF_IMPORT_WINDOWS not in options and CONF_EXPORT_WINDOWS not in options:
            import_windows, export_windows = split_legacy_windows(legacy)
            options[CONF_IMPORT_WINDOWS] = import_windows
            options[CONF_EXPORT_WINDOWS] = export_windows

    # Per-direction lists: turn each window into a subentry.
    for subentry_type, option_key in (
        (SUBENTRY_TYPE_IMPORT, CONF_IMPORT_WINDOWS),
        (SUBENTRY_TYPE_EXPORT, CONF_EXPORT_WINDOWS),
    ):
        if (stored := options.pop(option_key, None)) is None:
            continue
        changed = True
        if _has_subentries(entry, subentry_type):
            continue
        for window in parse_windows(stored):
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType(window.as_dict()),
                    subentry_type=subentry_type,
                    title=window.label,
                    unique_id=None,
                ),
            )
        _LOGGER.info(
            "Migrated %s windows into subentries for %s",
            subentry_type,
            entry.entry_id,
        )

    return changed


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Tariff Helper from a config entry."""
    options = dict(entry.options)
    changed = _migrate_windows_to_subentries(hass, entry, options)

    if CONF_START_DATE not in options:
        # Persist the setup date so the cumulative supply charge total never
        # resets across restarts (required by the TOTAL statistic).
        options[CONF_START_DATE] = dt_util.now().date().isoformat()
        changed = True

    if changed:
        hass.config_entries.async_update_entry(entry, options=options)

    coordinator = TariffCoordinator(
        hass,
        entry,
        import_windows=windows_for(entry, SUBENTRY_TYPE_IMPORT),
        export_windows=windows_for(entry, SUBENTRY_TYPE_EXPORT),
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
    """Rebuild both schedules when subentries or options change."""
    coordinator: TariffCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_set_windows(
        windows_for(entry, SUBENTRY_TYPE_IMPORT),
        windows_for(entry, SUBENTRY_TYPE_EXPORT),
    )
    coordinator.async_set_supply_charge(entry.options.get(CONF_SUPPLY_CHARGE, 0.0))
