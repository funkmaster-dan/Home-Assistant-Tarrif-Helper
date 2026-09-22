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

from collections.abc import Mapping
from datetime import time, timedelta
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
from homeassistant.util import dt as dt_util

from .const import (
    CONF_END,
    CONF_GST_EXPORT,
    CONF_GST_IMPORT,
    CONF_GST_PERCENT,
    CONF_GST_SUPPLY_CHARGE,
    CONF_METER_NAME,
    CONF_RATE,
    CONF_START,
    CONF_START_DATE,
    CONF_SUPPLY_CHARGE,
    DEFAULT_GST_EXPORT,
    DEFAULT_GST_IMPORT,
    DEFAULT_GST_PERCENT,
    DEFAULT_GST_SUPPLY_CHARGE,
    DOMAIN,
    SUBENTRY_TITLE_PREFIX,
    SUBENTRY_TYPE_EXPORT,
    SUBENTRY_TYPE_IMPORT,
)
from .tariff import TariffWindow, window_from_dict, windows_overlap


def _window_schema(
    currency: str, defaults: dict[str, Any] | None = None
) -> vol.Schema:
    """Build the window form, optionally pre-filled.

    Every field carries an explicit default. A required selector without one
    renders its own floor (the rate box showed -100), and two identical time
    defaults silently become an all-day window — so the add form opens with a
    one-hour window starting now and a zero rate instead.
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

    start_now = dt_util.now().replace(second=0, microsecond=0)
    default_start = start_now.time().strftime("%H:%M:%S")
    default_end = (start_now + timedelta(hours=1)).time().strftime("%H:%M:%S")

    return vol.Schema(
        {
            vol.Required(
                CONF_START, default=defaults.get(CONF_START, default_start)
            ): selector.TimeSelector(),
            vol.Required(
                CONF_END, default=defaults.get(CONF_END, default_end)
            ): selector.TimeSelector(),
            vol.Required(CONF_RATE, default=defaults.get(CONF_RATE, 0.0)): number,
        }
    )


def _pricing_schema(currency: str, defaults: Mapping[str, Any]) -> vol.Schema:
    """Build the supply charge and tax form, optionally pre-filled."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SUPPLY_CHARGE,
                default=defaults.get(CONF_SUPPLY_CHARGE, 0.0),
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
                default=defaults.get(CONF_GST_PERCENT, DEFAULT_GST_PERCENT),
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
                default=defaults.get(CONF_GST_IMPORT, DEFAULT_GST_IMPORT),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_GST_EXPORT,
                default=defaults.get(CONF_GST_EXPORT, DEFAULT_GST_EXPORT),
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_GST_SUPPLY_CHARGE,
                default=defaults.get(
                    CONF_GST_SUPPLY_CHARGE, DEFAULT_GST_SUPPLY_CHARGE
                ),
            ): selector.BooleanSelector(),
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
            self._meter_name = meter_name
            return await self.async_step_pricing()

        schema = vol.Schema(
            {
                vol.Required(CONF_METER_NAME, default="Electricity"): (
                    selector.TextSelector()
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_pricing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the daily supply charge and tax settings."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._meter_name,
                data={CONF_METER_NAME: self._meter_name},
                options={
                    CONF_START_DATE: dt_util.now().date().isoformat(),
                    **user_input,
                },
            )

        return self.async_show_form(
            step_id="pricing",
            data_schema=_pricing_schema(self.hass.config.currency, {}),
        )

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
        return self.async_show_form(
            step_id="init",
            data_schema=_pricing_schema(self.hass.config.currency, options),
        )


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
            if not getattr(self, "_overlap_ack", False) and self._find_overlap(
                window, None
            ):
                self._overlap_ack = True
                return self.async_show_form(
                    step_id="user",
                    data_schema=_window_schema(self.hass.config.currency, user_input),
                    errors={"base": "overlaps_existing"},
                )
            return self.async_create_entry(
                title=window.title(
                    SUBENTRY_TITLE_PREFIX[self._subentry_type],
                    self.hass.config.currency,
                ),
                data=window.as_dict(),
            )

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
            if not getattr(self, "_overlap_ack", False) and self._find_overlap(
                window, subentry
            ):
                self._overlap_ack = True
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_window_schema(self.hass.config.currency, user_input),
                    errors={"base": "overlaps_existing"},
                )
            # async_update_and_abort, not async_update_reload_and_abort: this
            # entry registers update listeners, which the reload variant
            # refuses to work with. The listener rebuilds the schedule.
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data=window.as_dict(),
                title=window.title(
                    SUBENTRY_TITLE_PREFIX[self._subentry_type],
                    self.hass.config.currency,
                ),
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_window_schema(
                self.hass.config.currency, dict(subentry.data)
            ),
        )

    def _find_overlap(
        self, window: TariffWindow, exclude: ConfigSubentry | None
    ) -> bool:
        """Return True if ``window`` overlaps another window of its direction."""
        for subentry in self._get_entry().get_subentries_of_type(self._subentry_type):
            if exclude is not None and subentry.subentry_id == exclude.subentry_id:
                continue
            other = window_from_dict(subentry.data)
            if other is not None and windows_overlap(window, other):
                return True
        return False
