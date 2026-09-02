"""Binary sensors for ioHouse controller-level runtime states."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_UNITS_CHANGED
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import (
    get_controller_device_id,
    get_controller_device_info,
    get_group_device_info,
    get_unit_device_info,
    is_exhaust_ventilation_unit,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up controller and ventilation binary sensors."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    controller_device_id = get_controller_device_id(hass, entry)
    entities: dict[str, BinarySensorEntity] = {}

    def _create_entities() -> list[BinarySensorEntity]:
        new_entities: list[BinarySensorEntity] = []
        if "legionella_work" not in entities:
            entity = IOhouseLegionellaWorkBinarySensor(coordinator, entry)
            entities["legionella_work"] = entity
            new_entities.append(entity)

        for entity_id in coordinator.group_entities:
            group_data = coordinator.get_group_entity_data(entity_id)
            group_id = str(group_data.get("group_id") or "")
            kind = group_data.get("kind")
            if not group_id:
                continue

            opening_key = f"opening:{group_id}"
            if (
                kind == "g"
                and opening_key not in entities
                and (
                    group_data.get("opening_guard_enabled")
                    or group_data.get("opening_sensor_id")
                )
            ):
                entity = IOhouseGroupOpeningGuardBinarySensor(
                    coordinator,
                    entry,
                    entity_id,
                    controller_device_id,
                )
                entities[opening_key] = entity
                new_entities.append(entity)

            fallback_key = f"ventilation_fallback:{group_id}"
            if kind == "v" and fallback_key not in entities:
                entity = IOhouseVentilationFallbackBinarySensor(
                    coordinator,
                    entry,
                    entity_id,
                    controller_device_id,
                )
                entities[fallback_key] = entity
                new_entities.append(entity)

        for unit_id in coordinator.units:
            exhaust_key = f"exhaust:{unit_id}"
            if exhaust_key in entities:
                continue
            if not is_exhaust_ventilation_unit(coordinator.get_unit_data(unit_id)):
                continue
            entity = IOhouseExhaustVentilationBinarySensor(
                coordinator,
                entry,
                unit_id,
                controller_device_id,
            )
            entities[exhaust_key] = entity
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

    @callback
    def handle_coordinator_update() -> None:
        new_entities = _create_entities()
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)

    entry.async_on_unload(hass.bus.async_listen(EVENT_UNITS_CHANGED, handle_units_changed))
    entry.async_on_unload(coordinator.async_add_listener(handle_coordinator_update))


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


class BaseGroupBinarySensor(
    CoordinatorEntity[IOhouseDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Base binary sensor attached to a controller group device."""

    _attr_has_entity_name = True

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


class IOhouseGroupOpeningGuardBinarySensor(BaseGroupBinarySensor):
    """Opening guard state for a controller room/group."""

    _attr_name = "Opening Guard"
    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_icon = "mdi:window-open-variant"

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        entity_key: str,
        controller_device_id: str | None,
    ) -> None:
        super().__init__(coordinator, entry, entity_key, controller_device_id)
        group_id = entity_key.split(":", 1)[0]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{group_id}_opening_guard"

    @property
    def is_on(self) -> bool:
        return bool(self._group_data.get("opening_blocked", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "opening_sensor_id": self._group_data.get("opening_sensor_id"),
            "guard_enabled": self._group_data.get("opening_guard_enabled"),
        }


class IOhouseVentilationFallbackBinarySensor(BaseGroupBinarySensor):
    """Warn when ventilation is using minimum demand without valid CO2."""

    _attr_name = "Ventilation CO2 Fallback"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:molecule-co2"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        entity_key: str,
        controller_device_id: str | None,
    ) -> None:
        super().__init__(coordinator, entry, entity_key, controller_device_id)
        group_id = entity_key.split(":", 1)[0]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{group_id}_ventilation_fallback"

    @property
    def is_on(self) -> bool:
        return bool(self._group_data.get("fallback", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"co2_sensor_id": self._group_data.get("co2_sensor_id")}


class IOhouseExhaustVentilationBinarySensor(
    CoordinatorEntity[IOhouseDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Read-only active state of a fan-coil follower exhaust zone."""

    _attr_has_entity_name = True
    _attr_name = "Exhaust Ventilation"
    _attr_icon = "mdi:fan-chevron-up"

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
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}_exhaust_ventilation"

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
            and is_exhaust_ventilation_unit(self._unit_data)
        )

    @property
    def is_on(self) -> bool:
        return bool(
            int(self._unit_data.get("output_logical") or 0) > 0
            or int(self._unit_data.get("pwm") or 0) > 0
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pwm = float(self._unit_data.get("pwm") or 0)
        speed = 0 if pwm <= 0 else min(3, max(1, round(pwm * 3 / 100)))
        return {
            "source_unit_id": self._unit_data.get("fancoil_source_unit_id"),
            "speed": speed,
            "pwm": self._unit_data.get("pwm"),
        }

    @property
    def _unit_data(self) -> dict[str, Any]:
        return self.coordinator.get_unit_data(self.unit_id)
