"""Humidifier entities for ioHouse humidity-control units."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.humidifier import (
    HumidifierAction,
    HumidifierDeviceClass,
    HumidifierEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_UNITS_CHANGED
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import (
    format_target_temperature,
    get_controller_device_id,
    get_group_device_info,
    get_unit_device_info,
    get_unit_label,
    is_humidifier_unit,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up dehumidifier entities for humidity-control units."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    controller_device_id = get_controller_device_id(hass, entry)
    entities: dict[str, IOhouseDehumidifierEntity] = {}
    group_entities: dict[str, IOhouseGroupDehumidifierEntity] = {}

    def _create_entities() -> list[HumidifierEntity]:
        new_entities: list[HumidifierEntity] = []
        for unit_id in coordinator.units:
            if unit_id in entities:
                continue
            unit_data = coordinator.get_unit_data(unit_id)
            if not is_humidifier_unit(unit_data):
                continue
            entity = IOhouseDehumidifierEntity(coordinator, entry, unit_id, controller_device_id)
            entities[unit_id] = entity
            new_entities.append(entity)
        for entity_id in coordinator.group_entities:
            if entity_id in group_entities:
                continue
            group_data = coordinator.get_group_entity_data(entity_id)
            if group_data.get("kind") != "h":
                continue
            entity = IOhouseGroupDehumidifierEntity(coordinator, entry, entity_id, controller_device_id)
            group_entities[entity_id] = entity
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
                "Added ioHouse dehumidifier entities for units: %s",
                [getattr(entity, "unit_id", getattr(entity, "entity_key", "")) for entity in new_entities],
            )

    @callback
    def handle_coordinator_update() -> None:
        new_entities = _create_entities()
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)
            _LOGGER.info(
                "Added ioHouse dehumidifier entities after runtime refresh: %s",
                [getattr(entity, "unit_id", getattr(entity, "entity_key", "")) for entity in new_entities],
            )

    entry.async_on_unload(hass.bus.async_listen(EVENT_UNITS_CHANGED, handle_units_changed))
    entry.async_on_unload(coordinator.async_add_listener(handle_coordinator_update))


class IOhouseDehumidifierEntity(
    CoordinatorEntity[IOhouseDataUpdateCoordinator],
    HumidifierEntity,
):
    """Dehumidifier entity backed by an ioHouse humidity unit."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_min_humidity = 0
    _attr_max_humidity = 100
    _attr_target_humidity_step = 1.0

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
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}_humidifier"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return unit device info."""
        return get_unit_device_info(
            self.entry,
            self.unit_id,
            self._unit_data,
            self.controller_device_id,
        )

    @property
    def available(self) -> bool:
        """Entity availability follows the latest state payload."""
        return (
            self.coordinator.last_update_success
            and self.unit_id in self.coordinator.available_units
            and is_humidifier_unit(self._unit_data)
        )

    @property
    def is_on(self) -> bool | None:
        """Return target power as on/off state."""
        if self._unit_data.get("target_power") is not None:
            return bool(self._unit_data.get("target_power"))
        if self._unit_data.get("power") is not None:
            return bool(self._unit_data.get("power"))
        return None

    @property
    def current_humidity(self) -> float | None:
        """Return current humidity measured by the selected controller sensor."""
        return _normalize_humidity_value(self._unit_data.get("temperature"))

    @property
    def target_humidity(self) -> float | None:
        """Return target humidity setpoint."""
        return _normalize_humidity_value(self._unit_data.get("target_temp"))

    @property
    def action(self) -> HumidifierAction | None:
        """Reflect whether the dehumidifier is actively drying."""
        if self.is_on is False:
            return HumidifierAction.OFF

        logical_output = self._unit_data.get("output_logical")
        if logical_output is not None:
            return HumidifierAction.DRYING if int(logical_output or 0) > 0 else HumidifierAction.IDLE

        burner = self._unit_data.get("burner")
        if burner is not None:
            return HumidifierAction.DRYING if int(burner or 0) else HumidifierAction.IDLE

        if self._unit_data.get("power") is not None:
            return HumidifierAction.DRYING if int(self._unit_data.get("power") or 0) else HumidifierAction.IDLE

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose useful v2 metadata and runtime flags."""
        return {
            "unit_id": self.unit_id,
            "label": get_unit_label(self.unit_id, self._unit_data),
            "legacy_zone": self._unit_data.get("legacy_zone"),
            "group_id": self._unit_data.get("group_id"),
            "group_name": self._unit_data.get("group_name"),
            "selected_mode": self._unit_data.get("selected_mode"),
            "device_type": self._unit_data.get("device_type"),
            "capability": self._unit_data.get("capability"),
            "power": self._unit_data.get("power"),
            "target_power": self._unit_data.get("target_power"),
            "group_locked": self._unit_data.get("group_locked"),
            "pwm": self._unit_data.get("pwm"),
            "output_logical": self._unit_data.get("output_logical"),
            "cascade_active": self._unit_data.get("cascade_active"),
            "ventilation_modes_enabled": self.coordinator.get_common_data().get("ventilation_modes_enabled"),
            "ventilation_mode": self.coordinator.get_common_data().get("ventilation_mode"),
            "ventilation_participation": self._unit_data.get("ventilation_participation"),
            "ventilation_demand": self._ventilation_data.get("pwm"),
            "ventilation_co2": self._ventilation_data.get("co2"),
            "ventilation_fallback": self._ventilation_data.get("fallback"),
        }

    async def async_set_humidity(self, humidity: int) -> None:
        """Set target humidity."""
        if self._unit_data.get("group_locked"):
            return
        normalized = max(0, min(100, round(float(humidity))))
        await self.coordinator.send_zone_command(
            self.unit_id,
            {"tt": format_target_temperature(normalized)},
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the dehumidifier on."""
        if self._unit_data.get("group_locked"):
            return
        await self.coordinator.send_zone_command(self.unit_id, {"p": 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the dehumidifier off."""
        if self._unit_data.get("group_locked"):
            return
        await self.coordinator.send_zone_command(self.unit_id, {"p": 0})

    @property
    def _unit_data(self) -> dict[str, Any]:
        return self.coordinator.get_unit_data(self.unit_id)

    @property
    def _ventilation_data(self) -> dict[str, Any]:
        group_id = str(self._unit_data.get("group_id") or "")
        return self.coordinator.get_group_entity_data(f"{group_id}:v") if group_id else {}


class IOhouseGroupDehumidifierEntity(
    CoordinatorEntity[IOhouseDataUpdateCoordinator],
    HumidifierEntity,
):
    """Dehumidifier entity backed by a group-control room."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_min_humidity = 0
    _attr_max_humidity = 100
    _attr_target_humidity_step = 1.0

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
        safe_key = entity_key.replace(":", "_")
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{safe_key}_group_humidifier"

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
            and self._group_data.get("kind") == "h"
        )

    @property
    def name(self) -> str | None:
        return str(self._group_data.get("title") or "Осушение")

    @property
    def is_on(self) -> bool | None:
        if self._group_data.get("target_power") is not None:
            return bool(self._group_data.get("target_power"))
        if self._group_data.get("power") is not None:
            return bool(self._group_data.get("power"))
        return None

    @property
    def current_humidity(self) -> float | None:
        return _normalize_humidity_value(
            self._group_data.get("current_humidity", self._group_data.get("temperature"))
        )

    @property
    def target_humidity(self) -> float | None:
        return _normalize_humidity_value(
            self._group_data.get("target_humidity", self._group_data.get("target_temp"))
        )

    @property
    def action(self) -> HumidifierAction | None:
        if self.is_on is False:
            return HumidifierAction.OFF
        if int(self._group_data.get("active") or 0):
            return HumidifierAction.DRYING
        if self._group_data.get("power") is not None:
            return HumidifierAction.DRYING if int(self._group_data.get("power") or 0) else HumidifierAction.IDLE
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "group_id": self._group_data.get("group_id"),
            "kind": self._group_data.get("kind"),
            "group_cap": self._group_data.get("group_cap"),
            "unit_count": self._group_data.get("unit_count"),
            "power": self._group_data.get("power"),
            "target_power": self._group_data.get("target_power"),
            "pwm": self._group_data.get("pwm"),
            "command_count": self._group_data.get("command_count"),
            "ventilation_modes_enabled": self.coordinator.get_common_data().get("ventilation_modes_enabled"),
            "ventilation_mode": self.coordinator.get_common_data().get("ventilation_mode"),
            "ventilation_demand": self._ventilation_data.get("pwm"),
            "ventilation_co2": self._ventilation_data.get("co2"),
            "ventilation_fallback": self._ventilation_data.get("fallback"),
        }

    async def async_set_humidity(self, humidity: int) -> None:
        group_id = str(self._group_data.get("group_id") or "")
        if not group_id:
            return
        normalized = max(0, min(100, round(float(humidity))))
        await self.coordinator.send_group_command(
            group_id,
            "h",
            {"tt": format_target_temperature(normalized)},
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        group_id = str(self._group_data.get("group_id") or "")
        if not group_id:
            return
        await self.coordinator.send_group_command(
            group_id,
            "h",
            {"p": 1},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        group_id = str(self._group_data.get("group_id") or "")
        if not group_id:
            return
        await self.coordinator.send_group_command(
            group_id,
            "h",
            {"p": 0},
        )

    @property
    def _group_data(self) -> dict[str, Any]:
        return self.coordinator.get_group_entity_data(self.entity_key)

    @property
    def _ventilation_data(self) -> dict[str, Any]:
        group_id = str(self._group_data.get("group_id") or "")
        return self.coordinator.get_group_entity_data(f"{group_id}:v") if group_id else {}


def _normalize_humidity_value(value: Any) -> float | None:
    """Clamp controller percentage values to Home Assistant humidity bounds."""
    if value is None:
        return None
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None
