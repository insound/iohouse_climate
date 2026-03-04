"""Controller-level switches for ioHouse Climate."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import get_controller_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up controller-level switches."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([SummerModeSwitch(coordinator, entry)], update_before_add=True)


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
