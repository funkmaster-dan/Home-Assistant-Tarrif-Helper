"""Constants for the Energy Tariff Helper integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "energy_tariff_helper"

# Config entry data (set once at initial config flow)
CONF_METER_NAME: Final = "meter_name"

# Options keys
CONF_SUPPLY_CHARGE: Final = "supply_charge"  # float, AUD/day
CONF_START_DATE: Final = "start_date"  # ISO "YYYY-MM-DD"; set once, persisted
CONF_WINDOWS_JSON: Final = "windows"  # JSON list of window objects

# Seeded into the options form so the expected shape is discoverable.
DEFAULT_WINDOWS_JSON: Final = """[
  {"start": "07:00", "end": "23:00", "import_rate": 0.35, "export_rate": 0.05},
  {"start": "23:00", "end": "07:00", "import_rate": 0.18, "export_rate": 0.05}
]"""

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
