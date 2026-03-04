"""Read-only valve entities for ioHouse 2-pin zones."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.valve import ValveDeviceClass, ValveEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_UNITS_CHANGED
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import get_unit_device_info, get_unit_label, has_valve_data

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up valve entities for units with valve telemetry."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: dict[str, IOhouseValveEntity] = {}

    def _create_entities() -> list[IOhouseValveEntity]:
        new_entities: list[IOhouseValveEntity] = []
        for unit_id in coordinator.units:
            if unit_id in entities:
                continue
            unit_data = coordinator.get_unit_data(unit_id)
            if not has_valve_data(unit_data):
                continue
            entity = IOhouseValveEntity(coordinator, entry, unit_id)
            entities[unit_id] = entity
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
            _LOGGER.info(
                "Added ioHouse valve entities for units: %s",
                [entity.unit_id for entity in new_entities],
            )

    entry.async_on_unload(hass.bus.async_listen(EVENT_UNITS_CHANGED, handle_units_changed))


class IOhouseValveEntity(CoordinatorEntity[IOhouseDataUpdateCoordinator], ValveEntity):
    """Diagnostic valve entity."""

    _attr_has_entity_name = True
    _attr_name = "Valve"
    _attr_icon = "mdi:valve"
    _attr_device_class = ValveDeviceClass.WATER
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        unit_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.unit_id = unit_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}_valve"

    @property
    def device_info(self) -> dict[str, Any]:
        return get_unit_device_info(self.entry, self.unit_id, self._unit_data)

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.unit_id in self.coordinator.available_units
            and has_valve_data(self._unit_data)
        )

    @property
    def reports_position(self) -> bool:
        return self._unit_data.get("valve_position") is not None

    @property
    def current_valve_position(self) -> int | None:
        return self._unit_data.get("valve_position")

    @property
    def is_opening(self) -> bool | None:
        value = self._unit_data.get("valve_opening")
        return None if value is None else bool(value)

    @property
    def is_closing(self) -> bool | None:
        value = self._unit_data.get("valve_closing")
        return None if value is None else bool(value)

    @property
    def is_closed(self) -> bool | None:
        if self._unit_data.get("valve_closed") is not None:
            return bool(self._unit_data.get("valve_closed"))
        if self.current_valve_position is not None:
            return self.current_valve_position == 0
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "label": get_unit_label(self.unit_id, self._unit_data),
            "group_name": self._unit_data.get("group_name"),
            "valve_opened": self._unit_data.get("valve_opened"),
        }

    @property
    def _unit_data(self) -> dict[str, Any]:
        return self.coordinator.get_unit_data(self.unit_id)
