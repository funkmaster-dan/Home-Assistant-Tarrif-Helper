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
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ACTIVE_WINDOW,
    ATTR_GST_MULTIPLIER,
    ATTR_WINDOWS,
    COMPONENT_SUPPLY_CHARGE,
    CONF_METER_NAME,
    DIRECTION_EXPORT,
    DIRECTION_IMPORT,
    DOMAIN,
    KEY_EXPORT_RATE,
    KEY_IMPORT_RATE,
    KEY_SUPPLY_CHARGE,
    KEY_SUPPLY_CHARGE_ENERGY,
    KEY_SUPPLY_CHARGE_TOTAL,
    PLACEHOLDER_ENERGY_KWH,
)
from .coordinator import TariffCoordinator
from .tariff import TariffWindow


@dataclass(frozen=True, kw_only=True)
class TariffSensorEntityDescription(SensorEntityDescription):
    """Describes a tariff sensor and how to read its value."""

    value_fn: Callable[[TariffCoordinator], float]
    direction: str | None = None
    # Which tax multiplier this sensor reports, or None when tax is not
    # meaningful for it (the energy placeholder carries no charge).
    gst_component: str | None = None


RATE_SENSORS: tuple[TariffSensorEntityDescription, ...] = (
    TariffSensorEntityDescription(
        key=KEY_IMPORT_RATE,
        translation_key=KEY_IMPORT_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=None,
        suggested_display_precision=4,
        value_fn=lambda coordinator: coordinator.import_rate,
        direction=DIRECTION_IMPORT,
        gst_component=DIRECTION_IMPORT,
    ),
    TariffSensorEntityDescription(
        key=KEY_EXPORT_RATE,
        translation_key=KEY_EXPORT_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=None,
        suggested_display_precision=4,
        value_fn=lambda coordinator: coordinator.export_rate,
        direction=DIRECTION_EXPORT,
        gst_component=DIRECTION_EXPORT,
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
        gst_component=COMPONENT_SUPPLY_CHARGE,
    ),
    TariffSensorEntityDescription(
        key=KEY_SUPPLY_CHARGE_TOTAL,
        translation_key=KEY_SUPPLY_CHARGE_TOTAL,
        # MONETARY permits only TOTAL (see DEVICE_CLASS_STATE_CLASSES in
        # homeassistant/components/sensor/const.py). TOTAL_INCREASING is
        # rejected with a warning, so the cumulative supply charge must be
        # declared TOTAL. The Energy dashboard accepts both.
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda coordinator: coordinator.supply_charge_total,
        gst_component=COMPONENT_SUPPLY_CHARGE,
    ),
    TariffSensorEntityDescription(
        key=KEY_SUPPLY_CHARGE_ENERGY,
        translation_key=KEY_SUPPLY_CHARGE_ENERGY,
        # Pinned to zero so the Energy dashboard has an energy entity to hang
        # the supply charge cost on without it affecting energy totals.
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
        value_fn=lambda coordinator: PLACEHOLDER_ENERGY_KWH,
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
    def _own_windows(self) -> list[TariffWindow]:
        """Return the schedule belonging to this sensor's direction."""
        if self.entity_description.direction == DIRECTION_IMPORT:
            return self.coordinator.import_windows
        if self.entity_description.direction == DIRECTION_EXPORT:
            return self.coordinator.export_windows
        return []

    @property
    def _own_active(self) -> TariffWindow | None:
        """Return the active window belonging to this sensor's direction."""
        if self.entity_description.direction == DIRECTION_IMPORT:
            return self.coordinator.active_import
        if self.entity_description.direction == DIRECTION_EXPORT:
            return self.coordinator.active_export
        return None

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit, derived from the HA currency configuration."""
        currency = self.hass.config.currency
        if self.entity_description.key == KEY_SUPPLY_CHARGE:
            return f"{currency}/day"
        if self.entity_description.key == KEY_SUPPLY_CHARGE_TOTAL:
            return currency
        if self.entity_description.key == KEY_SUPPLY_CHARGE_ENERGY:
            return UnitOfEnergy.KILO_WATT_HOUR
        return f"{currency}/kWh"

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def _gst_multiplier(self) -> float | None:
        """Return the tax multiplier applied to this sensor's value."""
        component = self.entity_description.gst_component
        if component == DIRECTION_IMPORT:
            return self.coordinator.gst.import_multiplier()
        if component == DIRECTION_EXPORT:
            return self.coordinator.gst.export_multiplier()
        if component == COMPONENT_SUPPLY_CHARGE:
            return self.coordinator.gst.supply_charge_multiplier()
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the tax multiplier, plus this sensor's own schedule.

        The schedule lists the rates as configured, so the multiplier is what
        explains any difference between those and the sensor's value.
        """
        attributes: dict[str, Any] = {}
        if (multiplier := self._gst_multiplier) is not None:
            attributes[ATTR_GST_MULTIPLIER] = multiplier

        if self.entity_description.direction is None:
            return attributes

        active = self._own_active
        attributes[ATTR_ACTIVE_WINDOW] = (
            f"{active.start:%H:%M}-{active.end:%H:%M}" if active else None
        )
        attributes[ATTR_WINDOWS] = [
            window.as_dict() for window in self._own_windows
        ]
        return attributes
