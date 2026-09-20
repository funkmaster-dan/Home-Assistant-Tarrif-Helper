"""Constants for the Energy Tariff Helper integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "energy_tariff_helper"

# Config entry data (set once at initial config flow)
CONF_METER_NAME: Final = "meter_name"

# Subentry type for a tariff window (one subentry per window)
SUBENTRY_TYPE_WINDOW: Final = "window"

# Window subentry keys
CONF_START: Final = "start"  # "HH:MM:SS" from TimeSelector
CONF_END: Final = "end"  # "HH:MM:SS" from TimeSelector
CONF_IMPORT_RATE: Final = "import_rate"  # float, AUD/kWh
CONF_EXPORT_RATE: Final = "export_rate"  # float, AUD/kWh

# Options keys
CONF_SUPPLY_CHARGE: Final = "supply_charge"  # float, AUD/day
CONF_START_DATE: Final = "start_date"  # ISO "YYYY-MM-DD"; set once, persisted

# Entity unique-id suffixes
KEY_IMPORT_RATE: Final = "import_rate"
KEY_EXPORT_RATE: Final = "export_rate"
KEY_SUPPLY_CHARGE: Final = "supply_charge"
KEY_SUPPLY_CHARGE_TOTAL: Final = "supply_charge_total"

# Default (fallback) rate when no window covers the current instant.
# Deliberately 0.0 for both directions, so an unconfigured or misconfigured
# window can never silently charge a non-zero rate.
DEFAULT_RATE: Final = 0.0

ATTR_ACTIVE_WINDOW: Final = "active_window"  # "HH:MM-HH:MM" or None
ATTR_WINDOWS: Final = "windows"  # full schedule, for templates
