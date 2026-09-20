"""Config and options flows for the Energy Tariff Helper integration.

The initial config flow names the meter. Everything else — the daily supply
charge and the tariff windows — is managed by the options flow, so all
configuration lives in one place and one proven code path.

Windows are edited as a JSON list in the options dialog, e.g.::

    [
      {"start": "07:00", "end": "23:00", "import_rate": 0.35, "export_rate": 0.05},
      {"start": "23:00", "end": "07:00", "import_rate": 0.18, "export_rate": 0.05}
    ]

A window whose end is earlier than its start spans midnight. When windows
overlap, the earliest-listed match wins.
"""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_METER_NAME,
    CONF_SUPPLY_CHARGE,
    CONF_WINDOWS_JSON,
    DOMAIN,
    DEFAULT_WINDOWS_JSON,
)


def _validate_windows(raw: str) -> str:
    """Validate the windows JSON.

    Raises ``vol.Invalid`` with a translated error key when the payload is not
    usable, so the options form can show a precise message.
    """
    try:
        parsed = json.loads(raw)
    except ValueError as err:
        raise vol.Invalid("invalid_json") from err

    if not isinstance(parsed, list):
        raise vol.Invalid("windows_not_a_list")

    for index, window in enumerate(parsed):
        if not isinstance(window, dict):
            raise vol.Invalid("window_not_an_object")
        for field in ("start", "end", "import_rate", "export_rate"):
            if field not in window:
                raise vol.Invalid("window_missing_field")
        # "HH:MM" or "HH:MM:SS", 24-hour.
        for field in ("start", "end"):
            value = window[field]
            if not isinstance(value, str):
                raise vol.Invalid("window_time_not_string")
            parts = value.split(":")
            if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
                raise vol.Invalid("window_time_malformed")
            numbers = [int(p) for p in parts]
            if not (0 <= numbers[0] <= 23 and all(0 <= p <= 59 for p in numbers[1:])):
                raise vol.Invalid("window_time_out_of_range")
        if window["start"] == window["end"]:
            raise vol.Invalid("zero_length_window")
        for field in ("import_rate", "export_rate"):
            value = window[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise vol.Invalid("window_rate_not_number")
            if value < 0:
                raise vol.Invalid("window_rate_negative")

    return raw


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration of a tariff meter."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the meter name."""
        if user_input is not None:
            meter_name = user_input[CONF_METER_NAME]
            await self.async_set_unique_id(meter_name.lower(), raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=meter_name, data={CONF_METER_NAME: meter_name}
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_METER_NAME, default="Electricity"): (
                    selector.TextSelector()
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TariffOptionsFlow:
        """Return the options flow."""
        return TariffOptionsFlow()


class TariffOptionsFlow(OptionsFlow):
    """Manage the daily supply charge and the tariff windows."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                _validate_windows(user_input[CONF_WINDOWS_JSON])
            except vol.Invalid as err:
                errors["base"] = str(err)
            else:
                return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        currency = self.hass.config.currency
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SUPPLY_CHARGE,
                    default=options.get(CONF_SUPPLY_CHARGE, 0.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=100,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement=f"{currency}/day",
                    )
                ),
                vol.Required(
                    CONF_WINDOWS_JSON,
                    default=options.get(CONF_WINDOWS_JSON, DEFAULT_WINDOWS_JSON),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
