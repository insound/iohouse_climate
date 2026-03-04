"""Sensors for ioHouse climate units and controller IO."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_CONTROLLER_IO_CHANGED, EVENT_UNITS_CHANGED
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import get_controller_device_info, get_unit_device_info, get_unit_label

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for ioHouse units and controller IO."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: dict[str, SensorEntity] = {}

    def _create_entities() -> list[SensorEntity]:
        new_entities: list[SensorEntity] = []

        for unit_id in coordinator.units:
            entity_key = f"pwm:{unit_id}"
            if entity_key not in entities:
                entity = IOhousePwmSensor(coordinator, entry, unit_id)
                entities[entity_key] = entity
                new_entities.append(entity)

        for sensor_id in coordinator.ds_sensor_ids:
            entity_key = f"ds:{sensor_id}"
            if entity_key not in entities:
                entity = IOhouseDallasTemperatureSensor(coordinator, entry, sensor_id)
                entities[entity_key] = entity
                new_entities.append(entity)

        for sensor_id in coordinator.dht_sensor_ids:
            temperature_key = f"dht_t:{sensor_id}"
            if temperature_key not in entities:
                entity = IOhouseDhtTemperatureSensor(coordinator, entry, sensor_id)
                entities[temperature_key] = entity
                new_entities.append(entity)

            humidity_key = f"dht_h:{sensor_id}"
            if humidity_key not in entities:
                entity = IOhouseDhtHumiditySensor(coordinator, entry, sensor_id)
                entities[humidity_key] = entity
                new_entities.append(entity)

        return new_entities

    initial_entities = _create_entities()
    if initial_entities:
        async_add_entities(initial_entities, update_before_add=True)

    @callback
    def handle_units_changed(event) -> None:
        if event.data.get("entry_id") != entry.entry_id:
            return
        new_entities = _create_entities()
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)
            _LOGGER.info("Added ioHouse sensors after unit refresh: %s", [entity.unique_id for entity in new_entities])

    @callback
    def handle_controller_io_changed(event) -> None:
        if event.data.get("entry_id") != entry.entry_id:
            return
        new_entities = _create_entities()
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)
            _LOGGER.info("Added ioHouse controller sensors after IO refresh: %s", [entity.unique_id for entity in new_entities])

    entry.async_on_unload(hass.bus.async_listen(EVENT_UNITS_CHANGED, handle_units_changed))
    entry.async_on_unload(hass.bus.async_listen(EVENT_CONTROLLER_IO_CHANGED, handle_controller_io_changed))


class IOhousePwmSensor(CoordinatorEntity[IOhouseDataUpdateCoordinator], SensorEntity):
    """PWM diagnostic sensor for a unit."""

    _attr_has_entity_name = True
    _attr_name = "PWM"
    _attr_icon = "mdi:sine-wave"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        unit_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.unit_id = unit_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}_pwm"

    @property
    def device_info(self) -> dict[str, Any]:
        return get_unit_device_info(self.entry, self.unit_id, self._unit_data)

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.unit_id in self.coordinator.available_units
        )

    @property
    def native_value(self) -> int | None:
        return self._unit_data.get("pwm")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "label": get_unit_label(self.unit_id, self._unit_data),
            "group_name": self._unit_data.get("group_name"),
            "power": self._unit_data.get("power"),
            "burner": self._unit_data.get("burner"),
        }

    @property
    def _unit_data(self) -> dict[str, Any]:
        return self.coordinator.get_unit_data(self.unit_id)


class BaseControllerSensor(CoordinatorEntity[IOhouseDataUpdateCoordinator], SensorEntity):
    """Base class for controller-level sensors."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry

    @property
    def device_info(self) -> dict[str, Any]:
        return get_controller_device_info(self.entry)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class IOhouseDallasTemperatureSensor(BaseControllerSensor):
    """DS18B20 temperature sensor exposed by the controller."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        sensor_id: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self.sensor_id = sensor_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{sensor_id}"

    @property
    def name(self) -> str | None:
        return self._sensor_data.get("name") or self.sensor_id.upper()

    @property
    def native_value(self) -> float | None:
        return self._sensor_data.get("temperature")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "added": self._sensor_data.get("added"),
            "error": self._sensor_data.get("error"),
        }

    @property
    def _sensor_data(self) -> dict[str, Any]:
        return self.coordinator.get_ds_sensor_data(self.sensor_id)


class IOhouseDhtTemperatureSensor(BaseControllerSensor):
    """DHT temperature sensor exposed by the controller."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        sensor_id: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self.sensor_id = sensor_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{sensor_id}_temperature"

    @property
    def name(self) -> str | None:
        return f"{self._sensor_data.get('name') or self.sensor_id.upper()} Temperature"

    @property
    def available(self) -> bool:
        return super().available and bool(self._sensor_data.get("available", 0))

    @property
    def native_value(self) -> float | None:
        return self._sensor_data.get("temperature")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "available_flag": self._sensor_data.get("available"),
        }

    @property
    def _sensor_data(self) -> dict[str, Any]:
        return self.coordinator.get_dht_sensor_data(self.sensor_id)


class IOhouseDhtHumiditySensor(BaseControllerSensor):
    """DHT humidity sensor exposed by the controller."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        sensor_id: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self.sensor_id = sensor_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{sensor_id}_humidity"

    @property
    def name(self) -> str | None:
        return f"{self._sensor_data.get('name') or self.sensor_id.upper()} Humidity"

    @property
    def available(self) -> bool:
        return super().available and bool(self._sensor_data.get("available", 0))

    @property
    def native_value(self) -> float | None:
        return self._sensor_data.get("humidity")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "available_flag": self._sensor_data.get("available"),
        }

    @property
    def _sensor_data(self) -> dict[str, Any]:
        return self.coordinator.get_dht_sensor_data(self.sensor_id)
