"""Constants for the Energy Tariff Helper integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "energy_tariff_helper"

# Config entry data (set once at initial config flow)
CONF_METER_NAME: Final = "meter_name"

# Options keys
CONF_SUPPLY_CHARGE: Final = "supply_charge"  # float, currency/day
CONF_START_DATE: Final = "start_date"  # ISO "YYYY-MM-DD"; set once, persisted
CONF_IMPORT_WINDOWS: Final = "import_windows"  # list of {start, end, rate}
CONF_EXPORT_WINDOWS: Final = "export_windows"  # list of {start, end, rate}

# Pre-split storage format, migrated to the two lists above on setup.
CONF_LEGACY_WINDOWS: Final = "windows"

# Entity unique-id suffixes
KEY_IMPORT_RATE: Final = "import_rate"
KEY_EXPORT_RATE: Final = "export_rate"
KEY_SUPPLY_CHARGE: Final = "supply_charge"
KEY_SUPPLY_CHARGE_TOTAL: Final = "supply_charge_total"

# Tariff directions
DIRECTION_IMPORT: Final = "import"
DIRECTION_EXPORT: Final = "export"

# Default (fallback) rate when no window covers the current instant.
# Deliberately 0.0 for both directions, so an unconfigured or misconfigured
# schedule can never silently charge a non-zero rate.
DEFAULT_RATE: Final = 0.0

ATTR_ACTIVE_WINDOW: Final = "active_window"  # "HH:MM-HH:MM" or None
ATTR_WINDOWS: Final = "windows"  # this sensor's own schedule, for templates
