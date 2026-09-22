"""The Energy Tariff Helper integration.

Publishes the current electricity import and export tariff rates plus the fixed
daily supply charge as sensors. Tariff windows are config subentries, one per
window, so the integration page gives add / edit / delete rows for each
direction.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime, time as dt_time, timedelta
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXPORT_WINDOWS,
    CONF_GST_EXPORT,
    CONF_GST_IMPORT,
    CONF_GST_PERCENT,
    CONF_GST_SUPPLY_CHARGE,
    CONF_IMPORT_WINDOWS,
    CONF_LEGACY_WINDOWS,
    CONF_START_DATE,
    CONF_SUPPLY_CHARGE,
    DEFAULT_GST_EXPORT,
    DEFAULT_GST_IMPORT,
    DEFAULT_GST_PERCENT,
    DEFAULT_GST_SUPPLY_CHARGE,
    DOMAIN,
    STORAGE_VERSION,
    SUBENTRY_TITLE_PREFIX,
    SUBENTRY_TYPE_EXPORT,
    SUBENTRY_TYPE_IMPORT,
)
from .coordinator import TariffCoordinator
from .tariff import (
    GstSettings,
    TariffWindow,
    parse_windows,
    split_legacy_windows,
    window_from_dict,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

WINDOW_SUBENTRY_TYPES = (SUBENTRY_TYPE_IMPORT, SUBENTRY_TYPE_EXPORT)

# Accrual ledger keys, persisted in one Store per config entry.
KEY_ACCRUED_TOTAL = "accrued_total"
KEY_ACCRUED_THROUGH = "accrued_through"

# Migration only: 0.4.x billed whole days and stepped the total at 00:30 local.
_LEGACY_DAY_CHARGE_AFTER = dt_time(0, 30)


def gst_from_options(options: Mapping[str, Any]) -> GstSettings:
    """Build the tax settings from the config entry options."""
    return GstSettings(
        percent=float(options.get(CONF_GST_PERCENT, DEFAULT_GST_PERCENT)),
        apply_to_import=bool(options.get(CONF_GST_IMPORT, DEFAULT_GST_IMPORT)),
        apply_to_export=bool(options.get(CONF_GST_EXPORT, DEFAULT_GST_EXPORT)),
        apply_to_supply_charge=bool(
            options.get(CONF_GST_SUPPLY_CHARGE, DEFAULT_GST_SUPPLY_CHARGE)
        ),
    )


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
                    title=window.title(
                        SUBENTRY_TITLE_PREFIX[subentry_type], hass.config.currency
                    ),
                    unique_id=None,
                ),
            )
        _LOGGER.info(
            "Migrated %s windows into subentries for %s",
            subentry_type,
            entry.entry_id,
        )

    return changed


def _seed_accrual(
    options: Mapping[str, Any], stored: Mapping[str, Any] | None, now: datetime
) -> tuple[float, datetime]:
    """Return the opening accrual ledger for a config entry.

    Preference order: the persisted ledger; the 0.4.x whole-day formula, so an
    upgrade never steps the total; zero for a fresh meter.
    """
    if stored and KEY_ACCRUED_TOTAL in stored and KEY_ACCRUED_THROUGH in stored:
        through = dt_util.parse_datetime(str(stored[KEY_ACCRUED_THROUGH]))
        if through is not None:
            return float(stored[KEY_ACCRUED_TOTAL]), through

    if CONF_START_DATE not in options:
        return 0.0, now

    # 0.4.x counted whole days and stepped the total at 00:30 local; replicate
    # it once so recorded history and the ledger meet at the same value.
    today = dt_util.now().date()
    billing = today
    if dt_util.now().time() < _LEGACY_DAY_CHARGE_AFTER:
        billing -= timedelta(days=1)
    days = max(1, (billing - date.fromisoformat(options[CONF_START_DATE])).days + 1)
    charge = float(options.get(CONF_SUPPLY_CHARGE, 0.0)) * gst_from_options(
        options
    ).supply_charge_multiplier()
    return days * charge, now


def _normalize_subentry_titles(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rewrite window titles to the current format.

    Titles decide the row order on the integration page, so older formats are
    upgraded in place (also picking up a changed Home Assistant currency).
    """
    currency = hass.config.currency
    for subentry in entry.subentries.values():
        window = window_from_dict(subentry.data)
        if window is None:
            continue
        title = window.title(
            SUBENTRY_TITLE_PREFIX.get(subentry.subentry_type, subentry.subentry_type),
            currency,
        )
        if title != subentry.title:
            hass.config_entries.async_update_subentry(entry, subentry, title=title)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Tariff Helper from a config entry."""
    options = dict(entry.options)
    changed = _migrate_windows_to_subentries(hass, entry, options)
    _normalize_subentry_titles(hass, entry)

    # Seed the accrual ledger before the setup date is stamped below: a fresh
    # meter starts at zero, an upgraded one is seeded from the 0.4.x formula.
    store: Store[dict[str, Any]] = Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
    )
    stored = await store.async_load()
    accrued_total, accrued_through = _seed_accrual(
        options, stored, dt_util.now(dt_util.UTC)
    )

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
        store=store,
        accrued_total=accrued_total,
        accrued_through=accrued_through,
        gst=gst_from_options(options),
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
        coordinator: TariffCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_flush_ledger()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rebuild both schedules when subentries or options change."""
    coordinator: TariffCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_set_windows(
        windows_for(entry, SUBENTRY_TYPE_IMPORT),
        windows_for(entry, SUBENTRY_TYPE_EXPORT),
    )
    coordinator.async_set_supply_charge(entry.options.get(CONF_SUPPLY_CHARGE, 0.0))
    coordinator.async_set_gst(gst_from_options(entry.options))
