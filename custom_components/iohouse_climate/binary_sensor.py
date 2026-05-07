"""Binary sensors for ioHouse controller-level runtime states."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    """Set up controller-level binary sensors."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([IOhouseLegionellaWorkBinarySensor(coordinator, entry)], update_before_add=True)


class IOhouseLegionellaWorkBinarySensor(
    CoordinatorEntity[IOhouseDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Read-only indicator for the active antilegionella cycle."""

    _attr_has_entity_name = True
    _attr_name = "Legionella Work"
    _attr_icon = "mdi:water-boiler"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_legionella_work"

    @property
    def device_info(self) -> dict[str, Any]:
        return get_controller_device_info(self.entry)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.get_common_data().get("legionella_work", 0))
