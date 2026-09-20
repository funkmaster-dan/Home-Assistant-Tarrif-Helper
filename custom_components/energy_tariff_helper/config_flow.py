"""Config and options flows for the Energy Tariff Helper integration.

The initial config flow names the meter. The options flow is a menu that
manages the daily supply charge and the tariff windows using real time and
number pickers.

Import and export tariffs are separate schedules, so each direction has its own
list of windows and its own add/edit/remove actions.
"""

from __future__ import annotations

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
    CONF_EXPORT_WINDOWS,
    CONF_IMPORT_WINDOWS,
    CONF_METER_NAME,
    CONF_SUPPLY_CHARGE,
    DIRECTION_EXPORT,
    DIRECTION_IMPORT,
    DOMAIN,
)
from .tariff import (
    FIELD_END,
    FIELD_RATE,
    FIELD_START,
    TariffWindow,
    parse_windows,
)

MENU_SUPPLY = "supply_charge"
MENU_ADD_IMPORT = "add_import_window"
MENU_EDIT_IMPORT = "edit_import_window"
MENU_REMOVE_IMPORT = "remove_import_window"
MENU_ADD_EXPORT = "add_export_window"
MENU_EDIT_EXPORT = "edit_export_window"
MENU_REMOVE_EXPORT = "remove_export_window"

_OPTION_KEY = {
    DIRECTION_IMPORT: CONF_IMPORT_WINDOWS,
    DIRECTION_EXPORT: CONF_EXPORT_WINDOWS,
}


def _to_time(value: str) -> time:
    """Convert a TimeSelector value into a ``datetime.time``."""
    return time.fromisoformat(value)


def _window_label(window: TariffWindow) -> str:
    """Return a human label for a window, used as the select option."""
    return f"{window.start:%H:%M}-{window.end:%H:%M} (rate {window.rate:g})"


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

    def _windows(self, direction: str) -> list[TariffWindow]:
        """Return the configured windows for one direction."""
        return parse_windows(self.config_entry.options.get(_OPTION_KEY[direction]))

    def _save(self, direction: str, windows: list[TariffWindow]) -> ConfigFlowResult:
        """Persist one direction's windows, preserving the other options."""
        options = dict(self.config_entry.options)
        options[_OPTION_KEY[direction]] = [window.as_dict() for window in windows]
        return self.async_create_entry(data=options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        menu = [MENU_SUPPLY, MENU_ADD_IMPORT, MENU_ADD_EXPORT]
        if self._windows(DIRECTION_IMPORT):
            menu += [MENU_EDIT_IMPORT, MENU_REMOVE_IMPORT]
        if self._windows(DIRECTION_EXPORT):
            menu += [MENU_EDIT_EXPORT, MENU_REMOVE_EXPORT]

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

    # -- window forms ------------------------------------------------------

    def _window_schema(self, defaults: dict[str, Any] | None = None) -> vol.Schema:
        """Build the window form, optionally pre-filled.

        ``default`` is only attached when a value exists: a ``None`` default on a
        required time/number selector is rejected by HA's schema serialiser.
        """
        defaults = defaults or {}
        currency = self.hass.config.currency
        number = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=100,
                # HA's NumberSelector rejects step < 1e-3, so 0.001 is the
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
                field(FIELD_START): selector.TimeSelector(),
                field(FIELD_END): selector.TimeSelector(),
                field(FIELD_RATE): number,
            }
        )

    async def _async_add(
        self,
        direction: str,
        step_id: str,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        """Add a window for one direction."""
        if user_input is None:
            return self.async_show_form(
                step_id=step_id, data_schema=self._window_schema()
            )

        if user_input[FIELD_START] == user_input[FIELD_END]:
            return self.async_show_form(
                step_id=step_id,
                data_schema=self._window_schema(user_input),
                errors={"base": "zero_length_window"},
            )

        window = TariffWindow(
            start=_to_time(user_input[FIELD_START]),
            end=_to_time(user_input[FIELD_END]),
            rate=float(user_input[FIELD_RATE]),
        )
        return self._save(direction, [*self._windows(direction), window])

    async def _async_edit_pick(
        self, direction: str, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Pick which window of a direction to edit."""
        windows = self._windows(direction)
        if not windows:
            return self.async_abort(reason="no_windows")

        labels = [_window_label(window) for window in windows]
        if user_input is not None:
            self._edit_direction = direction
            self._edit_index = labels.index(user_input["window"])
            return await self._async_edit_details(
                direction, f"{step_id}_details", None
            )

        return self.async_show_form(
            step_id=step_id,
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

    async def _async_edit_details(
        self, direction: str, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Edit the window picked in the previous step."""
        windows = self._windows(direction)
        index = self._edit_index
        window = windows[index]

        if user_input is not None:
            if user_input[FIELD_START] == user_input[FIELD_END]:
                return self.async_show_form(
                    step_id=step_id,
                    data_schema=self._window_schema(user_input),
                    errors={"base": "zero_length_window"},
                )
            updated = list(windows)
            updated[index] = TariffWindow(
                start=_to_time(user_input[FIELD_START]),
                end=_to_time(user_input[FIELD_END]),
                rate=float(user_input[FIELD_RATE]),
            )
            return self._save(direction, updated)

        defaults = {
            FIELD_START: window.start.strftime("%H:%M:%S"),
            FIELD_END: window.end.strftime("%H:%M:%S"),
            FIELD_RATE: window.rate,
        }
        return self.async_show_form(
            step_id=step_id, data_schema=self._window_schema(defaults)
        )

    async def _async_remove(
        self, direction: str, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Pick which window of a direction to remove."""
        windows = self._windows(direction)
        if not windows:
            return self.async_abort(reason="no_windows")

        labels = [_window_label(window) for window in windows]
        if user_input is not None:
            index = labels.index(user_input["window"])
            return self._save(
                direction, [w for i, w in enumerate(windows) if i != index]
            )

        return self.async_show_form(
            step_id=step_id,
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

    # -- import windows ----------------------------------------------------

    async def async_step_add_import_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add an import window."""
        return await self._async_add(DIRECTION_IMPORT, MENU_ADD_IMPORT, user_input)

    async def async_step_edit_import_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit an import window."""
        return await self._async_edit_pick(
            DIRECTION_IMPORT, MENU_EDIT_IMPORT, user_input
        )

    async def async_step_edit_import_window_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the picked import window."""
        return await self._async_edit_details(
            DIRECTION_IMPORT, "edit_import_window_details", user_input
        )

    async def async_step_remove_import_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove an import window."""
        return await self._async_remove(
            DIRECTION_IMPORT, MENU_REMOVE_IMPORT, user_input
        )

    # -- export windows ----------------------------------------------------

    async def async_step_add_export_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add an export window."""
        return await self._async_add(DIRECTION_EXPORT, MENU_ADD_EXPORT, user_input)

    async def async_step_edit_export_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit an export window."""
        return await self._async_edit_pick(
            DIRECTION_EXPORT, MENU_EDIT_EXPORT, user_input
        )

    async def async_step_edit_export_window_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the picked export window."""
        return await self._async_edit_details(
            DIRECTION_EXPORT, "edit_export_window_details", user_input
        )

    async def async_step_remove_export_window(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove an export window."""
        return await self._async_remove(
            DIRECTION_EXPORT, MENU_REMOVE_EXPORT, user_input
        )
