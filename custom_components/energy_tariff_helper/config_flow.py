"""Config and options flows for the Energy Tariff Helper integration.

Two flows live here:

* ``ConfigFlow`` / ``TariffOptionsFlow`` handle the meter name and the daily
  supply charge.
* ``TariffWindowSubentryFlow`` handles individual tariff windows, one config
  subentry per window, so users add, edit and delete them as rows in the UI.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_END,
    CONF_EXPORT_RATE,
    CONF_IMPORT_RATE,
    CONF_METER_NAME,
    CONF_START,
    CONF_SUPPLY_CHARGE,
    DOMAIN,
    SUBENTRY_TYPE_WINDOW,
)


def _time_key(value: str) -> str:
    """Normalise an "HH:MM:SS" selector value to "HH:MM" for display."""
    return value[:5]


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

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types this integration supports."""
        return {SUBENTRY_TYPE_WINDOW: TariffWindowSubentryFlow}


class TariffOptionsFlow(OptionsFlow):
    """Manage the daily supply charge."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the daily supply charge."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        currency = self.hass.config.currency
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SUPPLY_CHARGE,
                    default=self.config_entry.options.get(CONF_SUPPLY_CHARGE, 0.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=100,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement=f"{currency}/day",
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class TariffWindowSubentryFlow(ConfigSubentryFlow):
    """Add or edit a single tariff window."""

    def _rate_schema(self, defaults: dict[str, Any] | None = None) -> vol.Schema:
        """Build the window form, optionally pre-filled."""
        defaults = defaults or {}
        currency = self.hass.config.currency
        number = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=100,
                step=0.0001,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement=f"{currency}/kWh",
            )
        )
        return vol.Schema(
            {
                vol.Required(
                    CONF_START, default=defaults.get(CONF_START)
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_END, default=defaults.get(CONF_END)
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_IMPORT_RATE, default=defaults.get(CONF_IMPORT_RATE)
                ): number,
                vol.Required(
                    CONF_EXPORT_RATE, default=defaults.get(CONF_EXPORT_RATE)
                ): number,
            }
        )

    def _existing_windows(self) -> set[tuple[str, str]]:
        """Return the (start, end) pairs already configured."""
        return {
            (subentry.data[CONF_START], subentry.data[CONF_END])
            for subentry in self._get_entry().subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_WINDOW
        }

    def _validate(
        self, user_input: dict[str, Any], *, current: ConfigSubentry | None = None
    ) -> dict[str, str]:
        """Return form errors for the submitted window."""
        if user_input[CONF_START] == user_input[CONF_END]:
            return {"base": "zero_length_window"}

        pair = (user_input[CONF_START], user_input[CONF_END])
        existing = self._existing_windows()
        if current is not None:
            existing.discard((current.data[CONF_START], current.data[CONF_END]))
        if pair in existing:
            return {"base": "duplicate_window"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a new window."""
        if user_input is not None:
            if errors := self._validate(user_input):
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._rate_schema(user_input),
                    errors=errors,
                )
            title = (
                f"{_time_key(user_input[CONF_START])}-{_time_key(user_input[CONF_END])}"
            )
            return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(step_id="user", data_schema=self._rate_schema())

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing window."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            if errors := self._validate(user_input, current=subentry):
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=self._rate_schema(user_input),
                    errors=errors,
                )
            return self.async_update_reload_and_abort(
                self._get_entry(),
                subentry,
                data=user_input,
                title=(
                    f"{_time_key(user_input[CONF_START])}"
                    f"-{_time_key(user_input[CONF_END])}"
                ),
            )

        return self.async_show_form(
            step_id="reconfigure", data_schema=self._rate_schema(dict(subentry.data))
        )
