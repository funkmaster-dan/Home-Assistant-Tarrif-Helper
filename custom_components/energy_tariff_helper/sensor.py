"""Sensor platform for the Energy Tariff Helper integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ACTIVE_WINDOW,
    ATTR_WINDOWS,
    CONF_METER_NAME,
    DOMAIN,
    KEY_EXPORT_RATE,
    KEY_IMPORT_RATE,
    KEY_SUPPLY_CHARGE,
    KEY_SUPPLY_CHARGE_TOTAL,
)
from .coordinator import TariffCoordinator


@dataclass(frozen=True, kw_only=True)
class TariffSensorEntityDescription(SensorEntityDescription):
    """Describes a tariff sensor and how to read its value."""

    value_fn: Callable[[TariffCoordinator], float]
    include_window_attributes: bool = False


RATE_SENSORS: tuple[TariffSensorEntityDescription, ...] = (
    TariffSensorEntityDescription(
        key=KEY_IMPORT_RATE,
        translation_key=KEY_IMPORT_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=None,
        suggested_display_precision=4,
        value_fn=lambda coordinator: coordinator.import_rate,
        include_window_attributes=True,
    ),
    TariffSensorEntityDescription(
        key=KEY_EXPORT_RATE,
        translation_key=KEY_EXPORT_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=None,
        suggested_display_precision=4,
        value_fn=lambda coordinator: coordinator.export_rate,
        include_window_attributes=True,
    ),
)

SUPPLY_SENSORS: tuple[TariffSensorEntityDescription, ...] = (
    TariffSensorEntityDescription(
        key=KEY_SUPPLY_CHARGE,
        translation_key=KEY_SUPPLY_CHARGE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=None,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda coordinator: coordinator.supply_charge,
    ),
    TariffSensorEntityDescription(
        key=KEY_SUPPLY_CHARGE_TOTAL,
        translation_key=KEY_SUPPLY_CHARGE_TOTAL,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda coordinator: coordinator.supply_charge_total,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the tariff sensors."""
    coordinator: TariffCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TariffSensor(coordinator, entry, description)
            for description in (*RATE_SENSORS, *SUPPLY_SENSORS)
        ]
    )


class TariffSensor(CoordinatorEntity[TariffCoordinator], SensorEntity):
    """A sensor backed by the tariff coordinator."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: TariffSensorEntityDescription

    def __init__(
        self,
        coordinator: TariffCoordinator,
        entry: ConfigEntry,
        description: TariffSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_METER_NAME],
            manufacturer="Energy Tariff Helper",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit, derived from the HA currency configuration."""
        currency = self.hass.config.currency
        if self.entity_description.key == KEY_SUPPLY_CHARGE:
            return f"{currency}/day"
        if self.entity_description.key == KEY_SUPPLY_CHARGE_TOTAL:
            return currency
        return f"{currency}/kWh"

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the active window and the full schedule on rate sensors."""
        if not self.entity_description.include_window_attributes:
            return None

        active = self.coordinator.active
        return {
            ATTR_ACTIVE_WINDOW: (
                f"{active.start:%H:%M}-{active.end:%H:%M}" if active else None
            ),
            ATTR_WINDOWS: [
                {
                    "start": f"{window.start:%H:%M}",
                    "end": f"{window.end:%H:%M}",
                    "import_rate": window.import_rate,
                    "export_rate": window.export_rate,
                }
                for window in self.coordinator.windows
            ],
        }
