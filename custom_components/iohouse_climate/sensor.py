"""Sensors for ioHouse climate units and controller IO."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
try:
    from homeassistant.const import (
        CONCENTRATION_PARTS_PER_MILLION,
        UnitOfRatio,
        UnitOfTemperature,
    )

    PERCENTAGE_UNIT = UnitOfRatio.PERCENTAGE
except (AttributeError, ImportError):
    from homeassistant.const import PERCENTAGE as PERCENTAGE_UNIT, UnitOfTemperature

    CONCENTRATION_PARTS_PER_MILLION = "ppm"
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_CONTROLLER_IO_CHANGED, EVENT_UNITS_CHANGED
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import (
    get_controller_device_id,
    get_controller_device_info,
    get_group_device_info,
    get_unit_device_info,
    get_unit_label,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for ioHouse units and controller IO."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    controller_device_id = get_controller_device_id(hass, entry)
    entities: dict[str, SensorEntity] = {}

    def _create_entities() -> list[SensorEntity]:
        new_entities: list[SensorEntity] = []

        for entity_key, factory in (
            ("ctrl:wifi_rssi", lambda: IOhouseWifiRssiSensor(coordinator, entry)),
            ("ctrl:free_heap", lambda: IOhouseFreeHeapSensor(coordinator, entry)),
            ("ctrl:uptime", lambda: IOhouseUptimeSensor(coordinator, entry)),
        ):
            if entity_key not in entities:
                entity = factory()
                entities[entity_key] = entity
                new_entities.append(entity)

        for unit_id in coordinator.units:
            entity_key = f"pwm:{unit_id}"
            if entity_key not in entities:
                entity = IOhousePwmSensor(coordinator, entry, unit_id, controller_device_id)
                entities[entity_key] = entity
                new_entities.append(entity)

            heater_temperature_key = f"fancoil_heater_temperature:{unit_id}"
            if (
                heater_temperature_key not in entities
                and coordinator.get_unit_data(unit_id).get("fancoil_heater_temperature") is not None
            ):
                entity = IOhouseFancoilHeaterTemperatureSensor(
                    coordinator,
                    entry,
                    unit_id,
                    controller_device_id,
                )
                entities[heater_temperature_key] = entity
                new_entities.append(entity)

        for entity_id in coordinator.group_entities:
            group_data = coordinator.get_group_entity_data(entity_id)
            if group_data.get("kind") != "v":
                continue

            demand_key = f"ventilation_demand:{entity_id}"
            if demand_key not in entities:
                entity = IOhouseGroupVentilationDemandSensor(
                    coordinator,
                    entry,
                    entity_id,
                    controller_device_id,
                )
                entities[demand_key] = entity
                new_entities.append(entity)

            co2_key = f"ventilation_co2:{entity_id}"
            if co2_key not in entities:
                entity = IOhouseGroupCo2Sensor(
                    coordinator,
                    entry,
                    entity_id,
                    controller_device_id,
                )
                entities[co2_key] = entity
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

    @callback
    def handle_coordinator_update() -> None:
        new_entities = _create_entities()
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)

    entry.async_on_unload(hass.bus.async_listen(EVENT_UNITS_CHANGED, handle_units_changed))
    entry.async_on_unload(hass.bus.async_listen(EVENT_CONTROLLER_IO_CHANGED, handle_controller_io_changed))
    entry.async_on_unload(coordinator.async_add_listener(handle_coordinator_update))


class IOhousePwmSensor(CoordinatorEntity[IOhouseDataUpdateCoordinator], SensorEntity):
    """PWM diagnostic sensor for a unit."""

    _attr_has_entity_name = True
    _attr_name = "PWM"
    _attr_icon = "mdi:sine-wave"
    _attr_native_unit_of_measurement = PERCENTAGE_UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        unit_id: str,
        controller_device_id: str | None,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.unit_id = unit_id
        self.controller_device_id = controller_device_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}_pwm"

    @property
    def device_info(self) -> dict[str, Any]:
        return get_unit_device_info(
            self.entry,
            self.unit_id,
            self._unit_data,
            self.controller_device_id,
        )

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


class IOhouseFancoilHeaterTemperatureSensor(
    CoordinatorEntity[IOhouseDataUpdateCoordinator],
    SensorEntity,
):
    """Air temperature downstream of the optional fan-coil heater."""

    _attr_has_entity_name = True
    _attr_name = "Fancoil Heater Air Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:heat-wave"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        unit_id: str,
        controller_device_id: str | None,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.unit_id = unit_id
        self.controller_device_id = controller_device_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}_fancoil_heater_temperature"

    @property
    def device_info(self) -> dict[str, Any]:
        return get_unit_device_info(
            self.entry,
            self.unit_id,
            self._unit_data,
            self.controller_device_id,
        )

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.unit_id in self.coordinator.available_units
            and self._unit_data.get("fancoil_heater_temperature") is not None
        )

    @property
    def native_value(self) -> float | None:
        return self._unit_data.get("fancoil_heater_temperature")

    @property
    def _unit_data(self) -> dict[str, Any]:
        return self.coordinator.get_unit_data(self.unit_id)


class BaseGroupVentilationSensor(
    CoordinatorEntity[IOhouseDataUpdateCoordinator],
    SensorEntity,
):
    """Base sensor for a group's CO2-driven ventilation runtime."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        entity_key: str,
        controller_device_id: str | None,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.entity_key = entity_key
        self.controller_device_id = controller_device_id

    @property
    def device_info(self) -> dict[str, Any]:
        return get_group_device_info(
            self.entry,
            str(self._group_data.get("group_id") or self.entity_key),
            self._group_data,
            self.controller_device_id,
        )

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.entity_key in self.coordinator.available_group_entities
        )

    @property
    def _group_data(self) -> dict[str, Any]:
        return self.coordinator.get_group_entity_data(self.entity_key)


class IOhouseGroupVentilationDemandSensor(BaseGroupVentilationSensor):
    """Effective CO2 ventilation demand for a controller group."""

    _attr_name = "Ventilation Demand"
    _attr_native_unit_of_measurement = PERCENTAGE_UNIT
    _attr_icon = "mdi:fan-auto"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        entity_key: str,
        controller_device_id: str | None,
    ) -> None:
        super().__init__(coordinator, entry, entity_key, controller_device_id)
        group_id = entity_key.split(":", 1)[0]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{group_id}_ventilation_demand"

    @property
    def native_value(self) -> float | None:
        return self._group_data.get("pwm")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "co2_sensor_id": self._group_data.get("co2_sensor_id"),
            "co2_fallback": self._group_data.get("fallback"),
            "ventilation_mode": self.coordinator.get_common_data().get("ventilation_mode"),
        }


class IOhouseGroupCo2Sensor(BaseGroupVentilationSensor):
    """CO2 value used by a controller group's ventilation algorithm."""

    _attr_name = "CO2"
    _attr_device_class = SensorDeviceClass.CO2
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
    _attr_icon = "mdi:molecule-co2"
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        entity_key: str,
        controller_device_id: str | None,
    ) -> None:
        super().__init__(coordinator, entry, entity_key, controller_device_id)
        group_id = entity_key.split(":", 1)[0]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{group_id}_ventilation_co2"

    @property
    def available(self) -> bool:
        return super().available and self._group_data.get("co2") is not None

    @property
    def native_value(self) -> float | None:
        return self._group_data.get("co2")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "co2_sensor_id": self._group_data.get("co2_sensor_id"),
            "fallback_active": self._group_data.get("fallback"),
        }


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


class ControllerDiagnosticSensor(BaseControllerSensor):
    """Base sensor for controller diagnostic values."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC


class IOhouseWifiRssiSensor(ControllerDiagnosticSensor):
    """Controller Wi-Fi RSSI sensor."""

    _attr_name = "WiFi RSSI"
    _attr_native_unit_of_measurement = "dBm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:wifi"

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_wifi_rssi"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.get_common_data().get("wifi_rssi")


class IOhouseFreeHeapSensor(ControllerDiagnosticSensor):
    """Controller free heap sensor."""

    _attr_name = "Free Heap"
    _attr_native_unit_of_measurement = "B"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:memory"

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_free_heap"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.get_common_data().get("free_heap")


class IOhouseUptimeSensor(ControllerDiagnosticSensor):
    """Controller uptime sensor."""

    _attr_name = "Uptime"
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_uptime"

    @property
    def native_value(self) -> int | None:
        uptime_ms = self.coordinator.get_common_data().get("uptime_ms")
        if uptime_ms is None:
            return None
        return int(uptime_ms // 1000)


class IOhouseDallasTemperatureSensor(BaseControllerSensor):
    """DS18B20 temperature sensor exposed by the controller."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 2

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
    _attr_suggested_display_precision = 2

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
    _attr_native_unit_of_measurement = PERCENTAGE_UNIT
    _attr_suggested_display_precision = 2

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
