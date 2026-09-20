"""Config and options flows for the Energy Tariff Helper integration.

The initial config flow names the meter. The options flow is a menu that
manages the daily supply charge and the tariff windows using real time and
number pickers — windows are never edited as raw JSON.

Windows are persisted in ``entry.options`` as a JSON string, but that is an
internal detail: the UI exposes one window at a time.
"""

from __future__ import annotations

import json
from datetime import time
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
    CONF_START_DATE,
    CONF_SUPPLY_CHARGE,
    CONF_WINDOWS_JSON,
    DOMAIN,
)
from .tariff import (
    FIELD_END,
    FIELD_EXPORT_RATE,
    FIELD_IMPORT_RATE,
    FIELD_START,
    TariffWindow,
    parse_windows,
)

MENU_ADD = "add_window"
MENU_EDIT = "edit_window"
MENU_REMOVE = "remove_window"
MENU_SUPPLY = "supply_charge"


def _to_time(value: str) -> time:
    """Convert a TimeSelector value into a ``datetime.time``."""
    return time.fromisoformat(value)


def _window_label(window: TariffWindow) -> str:
    """Return a human label for a window, used as the select option."""
    return (
        f"{window.start:%H:%M}-{window.end:%H:%M} "
        f"(import {window.import_rate:g}, export {window.export_rate:g})"
    )


def _serialise(windows: list[TariffWindow]) -> str:
    """Serialise windows back to the stored JSON form."""
    return json.dumps(
        [
            {
                FIELD_START: window.start.strftime("%H:%M"),
                FIELD_END: window.end.strftime("%H:%M"),
                FIELD_IMPORT_RATE: window.import_rate,
                FIELD_EXPORT_RATE: window.export_rate,
            }
            for window in windows
        ]
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


class TariffOptionsFlow(OptionsFlow):
    """Menu-driven management of the supply charge and tariff windows."""

    def _windows(self) -> list[TariffWindow]:
        """Return the currently configured windows."""
        return parse_windows(self.config_entry.options.get(CONF_WINDOWS_JSON))

    def _save(self, windows: list[TariffWindow]) -> ConfigFlowResult:
        """Persist the window list, preserving the other options."""
        options = dict(self.config_entry.options)
        options[CONF_WINDOWS_JSON] = _serialise(windows)
        return self.async_create_entry(data=options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        windows = self._windows()
        menu = [MENU_SUPPLY, MENU_ADD]
        if windows:
            menu += [MENU_EDIT, MENU_REMOVE]

        return self.async_show_menu(step_id="init", menu_options=menu)

    # -- supply charge -----------------------------------------------------

    async def async_step_supply_charge(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the daily supply charge."""
        if user_input is not None:
            options = dict(self.config_entry.options)
            options[CONF_SUPPLY_CHARGE] = user_input[CONF_SUPPLY_CHARGE]
            return self.async_create_entry(data=options)

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
        return self.async_show_form(step_id=MENU_SUPPLY, data_schema=schema)

    # -- add / edit --------------------------------------------------------

    def _window_schema(self, defaults: dict[str, Any] | None = None) -> vol.Schema:
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
                    FIELD_START, default=defaults.get(FIELD_START)
                ): selector.TimeSelector(),
                vol.Required(
                    FIELD_END, default=defaults.get(FIELD_END)
                ): selector.TimeSelector(),
                vol.Required(
                    FIELD_IMPORT_RATE, default=defaults.get(FIELD_IMPORT_RATE)
                ): number,
                vol.Required(
                    FIELD_EXPORT_RATE, default=defaults.get(FIELD_EXPORT_RATE)
                ): number,
            }
        )

    async def _async_save_window(
        self,
        user_input: dict[str, Any],
        windows: list[TariffWindow],
        replace_index: int | None = None,
    ) -> ConfigFlowResult:
        """Validate and store a window, then finish."""
        start, end = user_input[FIELD_START], user_input[FIELD_END]
        if start == end:
            return self.async_show_form(
                step_id=MENU_ADD if replace_index is None else MENU_EDIT,
                data_schema=self._window_schema(user_input),
                errors={"base": "zero_length_window"},
            )

        candidate = TariffWindow(
            start=_to_time(start),
            end=_to_time(end),
            import_rate=float(user_input[FIELD_IMPORT_RATE]),
            export_rate=float(user_input[FIELD_EXPORT_RATE]),
        )

        if replace_index is None:
            updated = [*windows, candidate]
        else:
            updated = list(windows)
            updated[replace_index] = candidate

        return self._save(updated)

    async def async_step_add_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a window."""
        if user_input is not None:
            return await self._async_save_window(user_input, self._windows())
        return self.async_show_form(step_id=MENU_ADD, data_schema=self._window_schema())

    async def async_step_edit_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a window, then edit it."""
        windows = self._windows()
        if not windows:
            return self.async_abort(reason="no_windows")

        labels = [_window_label(window) for window in windows]
        if user_input is not None:
            self._edit_index = labels.index(user_input["window"])
            return await self.async_step_edit_window_details()

        return self.async_show_form(
            step_id=MENU_EDIT,
            data_schema=vol.Schema(
                {
                    vol.Required("window"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=labels,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_window_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the selected window."""
        windows = self._windows()
        index = self._edit_index
        window = windows[index]
        if user_input is not None:
            return await self._async_save_window(user_input, windows, replace_index=index)

        defaults = {
            FIELD_START: window.start.strftime("%H:%M:%S"),
            FIELD_END: window.end.strftime("%H:%M:%S"),
            FIELD_IMPORT_RATE: window.import_rate,
            FIELD_EXPORT_RATE: window.export_rate,
        }
        return self.async_show_form(
            step_id="edit_window_details", data_schema=self._window_schema(defaults)
        )

    async def async_step_remove_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a window and remove it."""
        windows = self._windows()
        if not windows:
            return self.async_abort(reason="no_windows")

        labels = [_window_label(window) for window in windows]
        if user_input is not None:
            index = labels.index(user_input["window"])
            remaining = [w for i, w in enumerate(windows) if i != index]
            return self._save(remaining)

        return self.async_show_form(
            step_id=MENU_REMOVE,
            data_schema=vol.Schema(
                {
                    vol.Required("window"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=labels,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )
