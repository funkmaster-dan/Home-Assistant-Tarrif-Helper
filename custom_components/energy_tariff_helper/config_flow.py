"""Config, options and subentry flows for the Energy Tariff Helper integration.

* ``ConfigFlow`` names the meter.
* ``TariffOptionsFlow`` sets the daily supply charge.
* ``TariffWindowSubentryFlow`` adds and edits a single tariff window. It serves
  both directions — Home Assistant supplies the subentry type, so the same form
  is labelled "import" or "export" from the matching translations.

Each window is a config subentry, which is what gives the integration page its
add / edit / delete rows.
"""

from __future__ import annotations

from datetime import time
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
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_END,
    CONF_GST_EXPORT,
    CONF_GST_IMPORT,
    CONF_GST_PERCENT,
    CONF_GST_SUPPLY_CHARGE,
    CONF_METER_NAME,
    CONF_RATE,
    CONF_START,
    CONF_SUPPLY_CHARGE,
    DEFAULT_GST_EXPORT,
    DEFAULT_GST_IMPORT,
    DEFAULT_GST_PERCENT,
    DEFAULT_GST_SUPPLY_CHARGE,
    DOMAIN,
    SUBENTRY_TYPE_EXPORT,
    SUBENTRY_TYPE_IMPORT,
)
from .tariff import TariffWindow


def _window_schema(
    currency: str, defaults: dict[str, Any] | None = None
) -> vol.Schema:
    """Build the window form, optionally pre-filled.

    ``default`` is only attached when a value exists: a ``None`` default on a
    required time/number selector is rejected by HA's schema serialiser.
    """
    defaults = defaults or {}
    number = selector.NumberSelector(
        selector.NumberSelectorConfig(
            # Negative rates are real on wholesale plans (you can be paid to
            # import or forced to pay to export), so only the ceiling is capped.
            min=-100,
            max=100,
            # HA's NumberSelector rejects a step below 1e-3, so 0.001 is the
            # finest granularity a rate can be entered with.
            step=0.001,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=f"{currency}/kWh",
        )
    )

    def field(name: str) -> Any:
        if (value := defaults.get(name)) is None:
            return vol.Required(name)
        return vol.Required(name, default=value)

    return vol.Schema(
        {
            field(CONF_START): selector.TimeSelector(),
            field(CONF_END): selector.TimeSelector(),
            field(CONF_RATE): number,
        }
    )


def _to_window(user_input: dict[str, Any]) -> TariffWindow:
    """Build a ``TariffWindow`` from submitted form data."""
    return TariffWindow(
        start=time.fromisoformat(user_input[CONF_START]),
        end=time.fromisoformat(user_input[CONF_END]),
        rate=float(user_input[CONF_RATE]),
    )


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
        return {
            SUBENTRY_TYPE_IMPORT: TariffWindowSubentryFlow,
            SUBENTRY_TYPE_EXPORT: TariffWindowSubentryFlow,
        }


class TariffOptionsFlow(OptionsFlow):
    """Manage the daily supply charge and tax settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the supply charge and tax settings."""
        if user_input is not None:
            options = dict(self.config_entry.options)
            options.update(user_input)
            return self.async_create_entry(data=options)

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
                    CONF_GST_PERCENT,
                    default=options.get(CONF_GST_PERCENT, DEFAULT_GST_PERCENT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=100,
                        step=0.1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="%",
                    )
                ),
                vol.Required(
                    CONF_GST_IMPORT,
                    default=options.get(CONF_GST_IMPORT, DEFAULT_GST_IMPORT),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_GST_EXPORT,
                    default=options.get(CONF_GST_EXPORT, DEFAULT_GST_EXPORT),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_GST_SUPPLY_CHARGE,
                    default=options.get(
                        CONF_GST_SUPPLY_CHARGE, DEFAULT_GST_SUPPLY_CHARGE
                    ),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class TariffWindowSubentryFlow(ConfigSubentryFlow):
    """Add or edit one tariff window.

    The same class backs both the import and export subentry types; Home
    Assistant tells us which via ``self._subentry_type``, and the translations
    for that type supply the matching labels.
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a window."""
        if user_input is not None:
            window = _to_window(user_input)
            return self.async_create_entry(title=window.label, data=window.as_dict())

        return self.async_show_form(
            step_id="user", data_schema=_window_schema(self.hass.config.currency)
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing window."""
        subentry: ConfigSubentry = self._get_reconfigure_subentry()

        if user_input is not None:
            window = _to_window(user_input)
            # async_update_and_abort, not async_update_reload_and_abort: this
            # entry registers update listeners, which the reload variant
            # refuses to work with. The listener rebuilds the schedule.
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data=window.as_dict(),
                title=window.label,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_window_schema(
                self.hass.config.currency, dict(subentry.data)
            ),
        )
