"""Controller-level switches for ioHouse Climate."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_CONTROLLER_IO_CHANGED, EVENT_UNITS_CHANGED
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import (
    get_controller_device_id,
    get_controller_device_info,
    get_unit_device_info,
    get_unit_label,
    is_manual_unit,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up controller-level switches."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    controller_device_id = get_controller_device_id(hass, entry)
    entities: dict[str, SwitchEntity] = {}

    def _create_entities() -> list[SwitchEntity]:
        new_entities: list[SwitchEntity] = []

        if "summer_mode" not in entities:
            summer_mode_entity = SummerModeSwitch(coordinator, entry)
            entities["summer_mode"] = summer_mode_entity
            new_entities.append(summer_mode_entity)

        common = coordinator.get_common_data()
        if common.get("cooling_modes_enabled") and "cooling_mode" not in entities:
            cooling_mode_entity = CoolingModeSwitch(coordinator, entry)
            entities["cooling_mode"] = cooling_mode_entity
            new_entities.append(cooling_mode_entity)

        if common.get("ventilation_modes_enabled") and "ventilation_mode" not in entities:
            ventilation_mode_entity = VentilationModeSwitch(coordinator, entry)
            entities["ventilation_mode"] = ventilation_mode_entity
            new_entities.append(ventilation_mode_entity)

        for output_id in coordinator.output_ids:
            entity_key = f"output:{output_id}"
            if entity_key in entities:
                continue
            output_entity = OutputSwitch(coordinator, entry, output_id)
            entities[entity_key] = output_entity
            new_entities.append(output_entity)

        for unit_id in coordinator.units:
            entity_key = f"manual:{unit_id}"
            if entity_key in entities:
                continue
            unit_data = coordinator.get_unit_data(unit_id)
            if not is_manual_unit(unit_data):
                continue
            manual_entity = ManualUnitSwitch(coordinator, entry, unit_id, controller_device_id)
            entities[entity_key] = manual_entity
            new_entities.append(manual_entity)

        return new_entities

    initial_entities = _create_entities()
    if initial_entities:
        async_add_entities(initial_entities, update_before_add=True)

    @callback
    def handle_controller_io_changed(event) -> None:
        if event.data.get("entry_id") != entry.entry_id:
            return
        new_entities = _create_entities()
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)

    @callback
    def handle_units_changed(event) -> None:
        if event.data.get("entry_id") != entry.entry_id:
            return
        new_entities = _create_entities()
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)

    @callback
    def handle_coordinator_update() -> None:
        new_entities = _create_entities()
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)

    entry.async_on_unload(hass.bus.async_listen(EVENT_CONTROLLER_IO_CHANGED, handle_controller_io_changed))
    entry.async_on_unload(hass.bus.async_listen(EVENT_UNITS_CHANGED, handle_units_changed))
    entry.async_on_unload(coordinator.async_add_listener(handle_coordinator_update))


class BaseControllerSwitch(CoordinatorEntity[IOhouseDataUpdateCoordinator], SwitchEntity):
    """Base class for controller-level switches."""

    _attr_has_entity_name = True

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


class SummerModeSwitch(BaseControllerSwitch):
    """Global summer mode switch backed by apiaction sm=0|1."""

    _attr_name = "Summer Mode"
    _attr_icon = "mdi:sun-thermometer"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_summer_mode"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.get_common_data().get("summer_mode", 0))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.send_system_command({"sm": 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.send_system_command({"sm": 0})


class CoolingModeSwitch(BaseControllerSwitch):
    """Global cooling mode switch backed by apiaction cm=0|1."""

    _attr_name = "Cooling Mode"
    _attr_icon = "mdi:snowflake-thermometer"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_cooling_mode"

    @property
    def available(self) -> bool:
        return super().available and bool(
            self.coordinator.get_common_data().get("cooling_modes_enabled", 0)
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.get_common_data().get("cooling_mode", 0))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.send_system_command({"cm": 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.send_system_command({"cm": 0})


class VentilationModeSwitch(BaseControllerSwitch):
    """Global ventilation mode switch backed by apiaction vm=0|1."""

    _attr_name = "Ventilation Mode"
    _attr_icon = "mdi:fan"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_ventilation_mode"

    @property
    def available(self) -> bool:
        return super().available and bool(
            self.coordinator.get_common_data().get("ventilation_modes_enabled", 0)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        common = self.coordinator.get_common_data()
        return {
            "co2_off_ppm": common.get("ventilation_co2_off_ppm"),
            "co2_full_ppm": common.get("ventilation_co2_full_ppm"),
        }

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.get_common_data().get("ventilation_mode", 0))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.send_system_command({"vm": 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.send_system_command({"vm": 0})


class OutputSwitch(BaseControllerSwitch):
    """Manual controller output switch."""

    _attr_icon = "mdi:electric-switch"

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        output_id: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self.output_id = output_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{output_id}"

    @property
    def name(self) -> str | None:
        return self._output_data.get("name") or self.output_id.upper()

    @property
    def available(self) -> bool:
        return super().available

    @property
    def is_on(self) -> bool:
        return bool(self._output_data.get("state", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "output_id": self.output_id,
            "busy": self._output_data.get("busy", 0),
            "pwm": self._output_data.get("pwm"),
            "owner_unit_id": self._output_data.get("owner_unit_id"),
            "manual_control_available": not bool(self._output_data.get("busy", 0)),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.send_output_command(self.output_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.send_output_command(self.output_id, False)

    @property
    def _output_data(self) -> dict[str, Any]:
        return self.coordinator.get_output_data(self.output_id)


class ManualUnitSwitch(CoordinatorEntity[IOhouseDataUpdateCoordinator], SwitchEntity):
    """Switch entity for controller units configured as manual mode."""

    _attr_has_entity_name = True
    _attr_name = "Ручной режим"
    _attr_icon = "mdi:electric-switch"

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
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}_manual_switch"

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
            and is_manual_unit(self._unit_data)
        )

    @property
    def is_on(self) -> bool | None:
        if self._unit_data.get("target_power") is not None:
            return bool(self._unit_data.get("target_power"))
        if self._unit_data.get("power") is not None:
            return bool(self._unit_data.get("power"))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "label": get_unit_label(self.unit_id, self._unit_data),
            "legacy_zone": self._unit_data.get("legacy_zone"),
            "group_id": self._unit_data.get("group_id"),
            "group_name": self._unit_data.get("group_name"),
            "selected_mode": self._unit_data.get("selected_mode"),
            "device_type": self._unit_data.get("device_type"),
            "power": self._unit_data.get("power"),
            "target_power": self._unit_data.get("target_power"),
            "pwm": self._unit_data.get("pwm"),
            "output_logical": self._unit_data.get("output_logical"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.send_zone_command(self.unit_id, {"p": 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.send_zone_command(self.unit_id, {"p": 0})

    @property
    def _unit_data(self) -> dict[str, Any]:
        return self.coordinator.get_unit_data(self.unit_id)
