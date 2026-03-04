"""Diagnostic sensors for ioHouse units."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_UNITS_CHANGED
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import get_unit_device_info, get_unit_label

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PWM sensors for all units."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: dict[str, IOhousePwmSensor] = {}

    def _create_entities() -> list[IOhousePwmSensor]:
        new_entities: list[IOhousePwmSensor] = []
        for unit_id in coordinator.units:
            if unit_id in entities:
                continue
            entity = IOhousePwmSensor(coordinator, entry, unit_id)
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
                "Added ioHouse PWM sensors for units: %s",
                [entity.unit_id for entity in new_entities],
            )

    entry.async_on_unload(hass.bus.async_listen(EVENT_UNITS_CHANGED, handle_units_changed))


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
