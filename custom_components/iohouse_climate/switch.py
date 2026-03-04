"""Controller-level switches for ioHouse Climate."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_CONTROLLER_IO_CHANGED
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import get_controller_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up controller-level switches."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: dict[str, SwitchEntity] = {}

    def _create_entities() -> list[SwitchEntity]:
        new_entities: list[SwitchEntity] = []

        if "summer_mode" not in entities:
            summer_mode_entity = SummerModeSwitch(coordinator, entry)
            entities["summer_mode"] = summer_mode_entity
            new_entities.append(summer_mode_entity)

        for output_id in coordinator.output_ids:
            entity_key = f"output:{output_id}"
            if entity_key in entities:
                continue
            output_entity = OutputSwitch(coordinator, entry, output_id)
            entities[entity_key] = output_entity
            new_entities.append(output_entity)

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

    entry.async_on_unload(hass.bus.async_listen(EVENT_CONTROLLER_IO_CHANGED, handle_controller_io_changed))


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
        return super().available and not bool(self._output_data.get("busy", 0))

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
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._output_data.get("busy", 0):
            return
        await self.coordinator.send_output_command(self.output_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._output_data.get("busy", 0):
            return
        await self.coordinator.send_output_command(self.output_id, False)

    @property
    def _output_data(self) -> dict[str, Any]:
        return self.coordinator.get_output_data(self.output_id)
