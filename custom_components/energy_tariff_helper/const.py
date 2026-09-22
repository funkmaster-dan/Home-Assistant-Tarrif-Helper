"""Constants for the Energy Tariff Helper integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "energy_tariff_helper"

# Config entry data (set once at initial config flow)
CONF_METER_NAME: Final = "meter_name"

# Options keys
CONF_SUPPLY_CHARGE: Final = "supply_charge"  # float, currency/day (ex-GST)
CONF_START_DATE: Final = "start_date"  # ISO "YYYY-MM-DD"; set once, persisted

# Accrual ledger persistence: one Store per config entry in .storage.
STORAGE_VERSION: Final = 1

# GST options: one rate, applied to whichever components are enabled.
CONF_GST_PERCENT: Final = "gst_percent"  # float, percent
CONF_GST_IMPORT: Final = "gst_import"  # bool
CONF_GST_EXPORT: Final = "gst_export"  # bool
CONF_GST_SUPPLY_CHARGE: Final = "gst_supply_charge"  # bool

# Defaults are opt-in: an upgrade must not silently change reported rates.
DEFAULT_GST_PERCENT: Final = 10.0
DEFAULT_GST_IMPORT: Final = False
DEFAULT_GST_EXPORT: Final = False
DEFAULT_GST_SUPPLY_CHARGE: Final = False

# Subentry types: one subentry per tariff window, grouped by direction.
SUBENTRY_TYPE_IMPORT: Final = "import_window"
SUBENTRY_TYPE_EXPORT: Final = "export_window"

# Window subentry keys
CONF_START: Final = "start"  # "HH:MM:SS" from TimeSelector
CONF_END: Final = "end"  # "HH:MM:SS" from TimeSelector
CONF_RATE: Final = "rate"  # float, currency/kWh

# Pre-subentry storage, migrated on setup.
CONF_IMPORT_WINDOWS: Final = "import_windows"  # list of {start, end, rate}
CONF_EXPORT_WINDOWS: Final = "export_windows"  # list of {start, end, rate}
CONF_LEGACY_WINDOWS: Final = "windows"  # JSON string of combined windows

# Entity unique-id suffixes
KEY_IMPORT_RATE: Final = "import_rate"
KEY_EXPORT_RATE: Final = "export_rate"
KEY_SUPPLY_CHARGE: Final = "supply_charge"
KEY_SUPPLY_CHARGE_TOTAL: Final = "supply_charge_total"
KEY_SUPPLY_CHARGE_ENERGY: Final = "supply_charge_energy"

# The Energy dashboard has no field for a fixed daily charge, so the supply
# charge is attached to a grid source instead: this placeholder provides the
# energy side and supply_charge_total provides the cost side. It always reads
# zero, so it never affects energy totals.
PLACEHOLDER_ENERGY_KWH: Final = 0.0

# Tariff directions
DIRECTION_IMPORT: Final = "import"
DIRECTION_EXPORT: Final = "export"

# Tariff components that can have tax applied independently.
COMPONENT_SUPPLY_CHARGE: Final = "supply_charge"

SUBENTRY_TYPE_BY_DIRECTION: Final = {
    DIRECTION_IMPORT: SUBENTRY_TYPE_IMPORT,
    DIRECTION_EXPORT: SUBENTRY_TYPE_EXPORT,
}

# Default (fallback) rate when no window covers the current instant.
# Deliberately 0.0 for both directions, so an unconfigured or misconfigured
# schedule can never silently charge a non-zero rate.
DEFAULT_RATE: Final = 0.0

ATTR_ACTIVE_WINDOW: Final = "active_window"  # "HH:MM-HH:MM" or None
ATTR_WINDOWS: Final = "windows"  # this sensor's own schedule, for templates
ATTR_GST_MULTIPLIER: Final = "gst_multiplier"  # 1.0 when tax is off