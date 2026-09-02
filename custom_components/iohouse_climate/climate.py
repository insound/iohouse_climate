"""Climate entities for ioHouse units."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_UNITS_CHANGED, SUPPORT_MODES, SUPPORT_PRESETS
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import (
    format_target_temperature,
    get_controller_device_id,
    get_group_device_info,
    get_unit_device_info,
    get_unit_label,
    get_unit_settings,
    is_climate_unit,
    is_exhaust_ventilation_unit,
    is_heatcool_fancoil_unit,
    is_manual_unit,
    unit_supports_power_control,
    unit_supports_presets,
    unit_supports_target_temperature,
    unit_supports_ventilation,
)

_LOGGER = logging.getLogger(__name__)

ATTR_HVAC_MODE = "hvac_mode"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities for all discovered units."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    controller_device_id = get_controller_device_id(hass, entry)
    entities: dict[str, IOhouseClimateEntity] = {}
    group_entities: dict[str, IOhouseGroupClimateEntity] = {}
    entity_registry = er.async_get(hass)

    def _remove_obsolete_exhaust_climate_entities() -> None:
        for unit_id in coordinator.units:
            if not is_exhaust_ventilation_unit(coordinator.get_unit_data(unit_id)):
                continue
            unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}"
            entity_id = entity_registry.async_get_entity_id("climate", DOMAIN, unique_id)
            if entity_id:
                entity_registry.async_remove(entity_id)

    def _create_entities() -> list[ClimateEntity]:
        _remove_obsolete_exhaust_climate_entities()
        new_entities: list[ClimateEntity] = []
        for unit_id in coordinator.units:
            if unit_id in entities:
                continue
            if not is_climate_unit(coordinator.get_unit_data(unit_id)):
                continue
            entity = IOhouseClimateEntity(coordinator, entry, unit_id, controller_device_id)
            entities[unit_id] = entity
            new_entities.append(entity)
        for entity_id in coordinator.group_entities:
            if entity_id in group_entities:
                continue
            group_data = coordinator.get_group_entity_data(entity_id)
            if group_data.get("kind") not in {"c", "f"}:
                continue
            entity = IOhouseGroupClimateEntity(coordinator, entry, entity_id, controller_device_id)
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
                "Added ioHouse climate entities for units: %s",
                [getattr(entity, "unit_id", getattr(entity, "entity_key", "")) for entity in new_entities],
            )

    @callback
    def handle_coordinator_update() -> None:
        new_entities = _create_entities()
        if new_entities:
            async_add_entities(new_entities, update_before_add=True)
            _LOGGER.info(
                "Added ioHouse climate entities after runtime refresh: %s",
                [getattr(entity, "unit_id", getattr(entity, "entity_key", "")) for entity in new_entities],
            )

    entry.async_on_unload(hass.bus.async_listen(EVENT_UNITS_CHANGED, handle_units_changed))
    entry.async_on_unload(coordinator.async_add_listener(handle_coordinator_update))


class IOhouseClimateEntity(CoordinatorEntity[IOhouseDataUpdateCoordinator], ClimateEntity):
    """Climate entity backed by ioHouse unit_id."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = SUPPORT_MODES
    _attr_precision = 0.1
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
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}"

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
            and is_climate_unit(self._unit_data)
        )

    @property
    def min_temp(self) -> float:
        """Configured minimum target temperature."""
        return get_unit_settings(self.entry, self.unit_id)[0]

    @property
    def max_temp(self) -> float:
        """Configured maximum target temperature."""
        return get_unit_settings(self.entry, self.unit_id)[1]

    @property
    def target_temperature_step(self) -> float:
        """Configured target temperature step."""
        return get_unit_settings(self.entry, self.unit_id)[2]

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Expose features based on unit type."""
        features = ClimateEntityFeature(0)
        if unit_supports_power_control(self._unit_data):
            features |= ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
        if unit_supports_target_temperature(self._unit_data):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if unit_supports_presets(self._unit_data):
            features |= ClimateEntityFeature.PRESET_MODE
        return features

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Expose the heating, cooling and independent ventilation capabilities."""
        modes = [HVACMode.HEAT]
        if (
            is_heatcool_fancoil_unit(self._unit_data)
            and self.coordinator.get_common_data().get("cooling_modes_enabled")
        ):
            modes.append(HVACMode.COOL)
        if self._supports_ventilation:
            modes.append(HVACMode.FAN_ONLY)
        modes.append(HVACMode.OFF)
        return modes

    @property
    def preset_modes(self) -> list[str] | None:
        """Manual devices do not expose presets."""
        if unit_supports_presets(self._unit_data):
            return SUPPORT_PRESETS
        return None

    @property
    def current_temperature(self) -> float | None:
        """Return raw current temperature from v2 state."""
        return self._unit_data.get("temperature")

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature for climate units."""
        if is_manual_unit(self._unit_data):
            return None
        return self._unit_data.get("target_temp")

    @property
    def hvac_mode(self) -> HVACMode:
        """Use target power as the user-facing HVAC mode."""
        if int(self._unit_data.get("target_power") or self._unit_data.get("power") or 0):
            if (
                is_heatcool_fancoil_unit(self._unit_data)
                and self.coordinator.get_common_data().get("cooling_mode")
            ):
                return HVACMode.COOL
            return HVACMode.HEAT
        if (
            self._supports_ventilation
            and self.coordinator.get_common_data().get("ventilation_mode")
        ):
            return HVACMode.FAN_ONLY
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Reflect the real actuator state, not just the algorithm power flag."""
        current_mode = self.hvac_mode
        if current_mode == HVACMode.OFF:
            return HVACAction.OFF
        if current_mode == HVACMode.FAN_ONLY:
            return HVACAction.FAN if self._ventilation_is_running else HVACAction.IDLE
        if self._ventilation_is_running:
            return HVACAction.FAN

        cooling_runtime = (
            is_heatcool_fancoil_unit(self._unit_data)
            and self.coordinator.get_common_data().get("cooling_mode")
        )

        if int(self._unit_data.get("valve_opening") or 0) or int(self._unit_data.get("valve_closing") or 0):
            return HVACAction.COOLING if cooling_runtime else HVACAction.HEATING

        logical_output = self._unit_data.get("output_logical")
        if logical_output is not None:
            if int(logical_output or 0) > 0:
                return HVACAction.COOLING if cooling_runtime else HVACAction.HEATING
            return HVACAction.FAN if self._ventilation_is_running else HVACAction.IDLE

        burner = self._unit_data.get("burner")
        if burner is not None:
            if int(burner or 0):
                return HVACAction.COOLING if cooling_runtime else HVACAction.HEATING
            return HVACAction.FAN if self._ventilation_is_running else HVACAction.IDLE

        if int(self._unit_data.get("power") or 0):
            return HVACAction.COOLING if cooling_runtime else HVACAction.HEATING

        return HVACAction.FAN if self._ventilation_is_running else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Map v2 flags to HA preset names."""
        if not unit_supports_presets(self._unit_data):
            return None

        if int(self._unit_data.get("night_mode") or 0):
            return "sleep"
        if int(self._unit_data.get("away_mode") or 0):
            return "away"
        if int(self._unit_data.get("eco_mode") or 0):
            return "eco"
        return "comfort"

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
            "target_locked": self._unit_data.get("target_locked"),
            "group_locked": self._unit_data.get("group_locked"),
            "floor_temperature": self._unit_data.get("floor_temperature"),
            "pwm": self._unit_data.get("pwm"),
            "output_logical": self._unit_data.get("output_logical"),
            "cascade_active": self._unit_data.get("cascade_active"),
            "burner": self._unit_data.get("burner"),
            "heat_confirm": self._unit_data.get("heat_confirm"),
            "after_floor": self._unit_data.get("after_floor"),
            "after_floor_go": self._unit_data.get("after_floor_go"),
            "slave": self._unit_data.get("slave"),
            "manual_mode": is_manual_unit(self._unit_data),
            "cooling_modes_enabled": self.coordinator.get_common_data().get("cooling_modes_enabled"),
            "cooling_mode": self.coordinator.get_common_data().get("cooling_mode"),
            "ventilation_modes_enabled": self.coordinator.get_common_data().get("ventilation_modes_enabled"),
            "ventilation_mode": self.coordinator.get_common_data().get("ventilation_mode"),
            "ventilation_supported": unit_supports_ventilation(self._unit_data),
            "ventilation_participation": self._unit_data.get("ventilation_participation"),
            "ventilation_only_active": self._ventilation_is_running,
            "ventilation_demand": self._ventilation_data.get("pwm"),
            "ventilation_co2": self._ventilation_data.get("co2"),
            "ventilation_fallback": self._ventilation_data.get("fallback"),
            "fancoil_source_unit_id": self._unit_data.get("fancoil_source_unit_id"),
            "fancoil_heater_temperature": self._unit_data.get("fancoil_heater_temperature"),
        }

    async def async_set_temperature(self, **kwargs) -> None:
        """Send target temperature and optional HVAC mode through apiaction v2."""
        params: dict[str, Any] = {}

        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None and unit_supports_target_temperature(self._unit_data):
            min_temp, max_temp, temp_step = get_unit_settings(self.entry, self.unit_id)
            normalized = round(float(temperature) / temp_step) * temp_step
            normalized = min(max(normalized, min_temp), max_temp)
            params["tt"] = format_target_temperature(normalized)

        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        normalized_hvac_mode = _normalize_hvac_mode(hvac_mode)
        if normalized_hvac_mode is not None and not unit_supports_power_control(self._unit_data):
            _LOGGER.debug("Ignoring HVAC mode command for group-locked unit %s", self.unit_id)
        elif normalized_hvac_mode == HVACMode.COOL:
            if not (
                is_heatcool_fancoil_unit(self._unit_data)
                and self.coordinator.get_common_data().get("cooling_modes_enabled")
            ):
                _LOGGER.error("Cooling is not supported for %s", self.unit_id)
                return
            await self.coordinator.send_system_command({"cm": 1})
            params["p"] = 1
        elif normalized_hvac_mode == HVACMode.FAN_ONLY:
            if not self._supports_ventilation:
                _LOGGER.error("Ventilation is not supported for %s", self.unit_id)
                return
            await self.coordinator.send_system_command({"vm": 1})
            params["p"] = 0
        elif normalized_hvac_mode == HVACMode.OFF:
            if self._supports_ventilation and self.coordinator.get_common_data().get("ventilation_mode"):
                await self.coordinator.send_system_command({"vm": 0})
            params["p"] = 0
        elif (
            normalized_hvac_mode == HVACMode.HEAT
            and is_heatcool_fancoil_unit(self._unit_data)
            and self.coordinator.get_common_data().get("cooling_mode")
        ):
            await self.coordinator.send_system_command({"cm": 0})
            params["p"] = 1
        else:
            power_value = _hvac_mode_to_power(normalized_hvac_mode)
            if power_value is not None:
                params["p"] = power_value

        if not params:
            return

        await self.coordinator.send_zone_command(self.unit_id, params)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Send target power through apiaction v2."""
        if not unit_supports_power_control(self._unit_data):
            return

        normalized_hvac_mode = _normalize_hvac_mode(hvac_mode)
        if normalized_hvac_mode == HVACMode.COOL:
            if not (
                is_heatcool_fancoil_unit(self._unit_data)
                and self.coordinator.get_common_data().get("cooling_modes_enabled")
            ):
                _LOGGER.error("Cooling is not supported for %s", self.unit_id)
                return

            await self.coordinator.send_system_command({"cm": 1})
            await self.coordinator.send_zone_command(self.unit_id, {"p": 1})
            return

        if normalized_hvac_mode == HVACMode.FAN_ONLY:
            if not self._supports_ventilation:
                _LOGGER.error("Ventilation is not supported for %s", self.unit_id)
                return
            await self.coordinator.send_system_command({"vm": 1})
            await self.coordinator.send_zone_command(self.unit_id, {"p": 0})
            return

        if normalized_hvac_mode == HVACMode.OFF and self._supports_ventilation:
            await self.coordinator.send_system_command({"vm": 0})

        if (
            normalized_hvac_mode == HVACMode.HEAT
            and is_heatcool_fancoil_unit(self._unit_data)
            and self.coordinator.get_common_data().get("cooling_mode")
        ):
            await self.coordinator.send_system_command({"cm": 0})

        power_value = _hvac_mode_to_power(normalized_hvac_mode)
        if power_value is None:
            _LOGGER.error("Unsupported HVAC mode for %s: %s", self.unit_id, hvac_mode)
            return

        await self.coordinator.send_zone_command(
            self.unit_id,
            {"p": power_value},
        )

    async def async_turn_on(self) -> None:
        """Turn the unit on."""
        if (
            is_heatcool_fancoil_unit(self._unit_data)
            and self.coordinator.get_common_data().get("cooling_mode")
        ):
            await self.async_set_hvac_mode(HVACMode.COOL)
            return
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn the unit off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Send preset flags through apiaction v2."""
        if not unit_supports_presets(self._unit_data):
            return

        params: dict[str, int]
        if preset_mode == "away":
            params = {"aw": 1, "ec": 0, "nt": 0}
        elif preset_mode == "eco":
            params = {"aw": 0, "ec": 1, "nt": 0}
        elif preset_mode in {"comfort", "home"}:
            params = {"aw": 0, "ec": 0, "nt": 0}
        elif preset_mode == "sleep":
            params = {"aw": 0, "ec": 0, "nt": 1}
        else:
            _LOGGER.error("Unsupported preset mode for %s: %s", self.unit_id, preset_mode)
            return

        await self.coordinator.send_zone_command(self.unit_id, params)

    @property
    def _unit_data(self) -> dict[str, Any]:
        return self.coordinator.get_unit_data(self.unit_id)

    @property
    def _ventilation_data(self) -> dict[str, Any]:
        group_id = str(self._unit_data.get("group_id") or "")
        return self.coordinator.get_group_entity_data(f"{group_id}:v") if group_id else {}

    @property
    def _supports_ventilation(self) -> bool:
        return bool(
            unit_supports_ventilation(self._unit_data)
            and self.coordinator.get_common_data().get("ventilation_modes_enabled")
        )

    @property
    def _ventilation_is_running(self) -> bool:
        if not (
            self._supports_ventilation
            and self.coordinator.get_common_data().get("ventilation_mode")
            and not int(self._unit_data.get("heat_confirm") or 0)
        ):
            return False
        return bool(
            float(self._unit_data.get("pwm") or 0) > 0.05
            or float(self._ventilation_data.get("pwm") or 0) > 0.05
        )


class IOhouseGroupClimateEntity(
    CoordinatorEntity[IOhouseDataUpdateCoordinator],
    ClimateEntity,
):
    """Climate entity backed by a group-control room."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:home-thermometer-outline"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = 0.1
    _attr_suggested_display_precision = 1

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
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{safe_key}_group_climate"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return group device info."""
        return get_group_device_info(
            self.entry,
            str(self._group_data.get("group_id") or self.entity_key),
            self._group_data,
            self.controller_device_id,
        )

    @property
    def available(self) -> bool:
        """Entity availability follows latest group state."""
        return (
            self.coordinator.last_update_success
            and self.entity_key in self.coordinator.available_group_entities
            and self._group_data.get("kind") in {"c", "f"}
        )

    @property
    def name(self) -> str | None:
        """Use entity name under the group device."""
        return str(self._group_data.get("title") or "Климат")

    @property
    def min_temp(self) -> float:
        if self._group_data.get("kind") == "f":
            return 0.0
        return DEFAULT_MIN_TEMP_FALLBACK

    @property
    def max_temp(self) -> float:
        if self._group_data.get("kind") == "f":
            return 100.0
        return DEFAULT_MAX_TEMP_FALLBACK

    @property
    def target_temperature_step(self) -> float:
        return 1.0 if self._group_data.get("kind") == "f" else 0.1

    @property
    def supported_features(self) -> ClimateEntityFeature:
        kind = self._group_data.get("kind")
        if kind not in {"c", "f"}:
            return ClimateEntityFeature(0)

        features = ClimateEntityFeature.TARGET_TEMPERATURE
        if kind == "c":
            features |= (
                ClimateEntityFeature.TURN_OFF
                | ClimateEntityFeature.TURN_ON
                | ClimateEntityFeature.PRESET_MODE
            )
        return features

    @property
    def hvac_modes(self) -> list[HVACMode]:
        if self._group_data.get("kind") != "c":
            return SUPPORT_MODES

        modes = [HVACMode.HEAT]
        common = self.coordinator.get_common_data()
        if self._group_data.get("supports_cooling") and common.get("cooling_modes_enabled"):
            modes.append(HVACMode.COOL)
        if self._supports_ventilation:
            modes.append(HVACMode.FAN_ONLY)
        modes.append(HVACMode.OFF)
        return modes

    @property
    def preset_modes(self) -> list[str] | None:
        return SUPPORT_PRESETS if self._group_data.get("kind") == "c" else None

    @property
    def current_temperature(self) -> float | None:
        return self._group_data.get("temperature")

    @property
    def target_temperature(self) -> float | None:
        return self._group_data.get("target_temp")

    @property
    def hvac_mode(self) -> HVACMode:
        if int(self._group_data.get("target_power") or self._group_data.get("power") or 0):
            if (
                self._group_data.get("kind") == "c"
                and self._group_data.get("supports_cooling")
                and self.coordinator.get_common_data().get("cooling_mode")
            ):
                return HVACMode.COOL
            return HVACMode.HEAT
        if self._supports_ventilation and self.coordinator.get_common_data().get("ventilation_mode"):
            return HVACMode.FAN_ONLY
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        current_mode = self.hvac_mode
        if current_mode == HVACMode.OFF:
            return HVACAction.OFF
        if current_mode == HVACMode.FAN_ONLY:
            return HVACAction.FAN if self._ventilation_is_running else HVACAction.IDLE
        if int(self._group_data.get("pwm") or 0) > 0 or int(self._group_data.get("heat_confirm") or 0):
            return HVACAction.COOLING if current_mode == HVACMode.COOL else HVACAction.HEATING
        if self._ventilation_is_running:
            return HVACAction.FAN
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        if self._group_data.get("kind") != "c":
            return None
        if int(self._group_data.get("night_mode") or 0):
            return "sleep"
        if int(self._group_data.get("away_mode") or 0):
            return "away"
        if int(self._group_data.get("eco_mode") or 0):
            return "eco"
        return "comfort"

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
            "supports_cooling": self._group_data.get("supports_cooling"),
            "supports_ventilation": self._group_data.get("supports_ventilation"),
            "ventilation_modes_enabled": self.coordinator.get_common_data().get("ventilation_modes_enabled"),
            "ventilation_mode": self.coordinator.get_common_data().get("ventilation_mode"),
            "ventilation_only_active": self._ventilation_is_running,
            "ventilation_demand": self._ventilation_data.get("pwm"),
            "ventilation_co2": self._ventilation_data.get("co2"),
            "ventilation_fallback": self._ventilation_data.get("fallback"),
        }

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        group_id = str(self._group_data.get("group_id") or "")
        kind = str(self._group_data.get("kind") or "")
        if not group_id or kind not in {"c", "f"}:
            return

        params: dict[str, Any] = {}
        if temperature is not None:
            step = self.target_temperature_step
            normalized = round(float(temperature) / step) * step
            normalized = min(max(normalized, self.min_temp), self.max_temp)
            params["tt"] = format_target_temperature(normalized)

        hvac_mode = _normalize_hvac_mode(kwargs.get(ATTR_HVAC_MODE))
        if kind == "c":
            if hvac_mode == HVACMode.COOL:
                if not (
                    self._group_data.get("supports_cooling")
                    and self.coordinator.get_common_data().get("cooling_modes_enabled")
                ):
                    return
                await self.coordinator.send_system_command({"cm": 1})
                params["p"] = 1
            elif hvac_mode == HVACMode.FAN_ONLY:
                if not self._supports_ventilation:
                    return
                await self.coordinator.send_system_command({"vm": 1})
                params["p"] = 0
            else:
                if hvac_mode == HVACMode.OFF and self._supports_ventilation:
                    await self.coordinator.send_system_command({"vm": 0})
                if (
                    hvac_mode == HVACMode.HEAT
                    and self._group_data.get("supports_cooling")
                    and self.coordinator.get_common_data().get("cooling_mode")
                ):
                    await self.coordinator.send_system_command({"cm": 0})
                power_value = _hvac_mode_to_power(hvac_mode)
                if power_value is not None:
                    params["p"] = power_value

        if params:
            await self.coordinator.send_group_command(
                group_id,
                kind,
                params,
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        group_id = str(self._group_data.get("group_id") or "")
        if not group_id or self._group_data.get("kind") != "c":
            return
        normalized_hvac_mode = _normalize_hvac_mode(hvac_mode)
        if normalized_hvac_mode == HVACMode.COOL:
            if not (
                self._group_data.get("supports_cooling")
                and self.coordinator.get_common_data().get("cooling_modes_enabled")
            ):
                return
            await self.coordinator.send_system_command({"cm": 1})
            await self.coordinator.send_group_command(group_id, "c", {"p": 1})
            return
        if normalized_hvac_mode == HVACMode.FAN_ONLY:
            if not self._supports_ventilation:
                return
            await self.coordinator.send_system_command({"vm": 1})
            await self.coordinator.send_group_command(group_id, "c", {"p": 0})
            return
        if normalized_hvac_mode == HVACMode.OFF and self._supports_ventilation:
            await self.coordinator.send_system_command({"vm": 0})
        if (
            normalized_hvac_mode == HVACMode.HEAT
            and self._group_data.get("supports_cooling")
            and self.coordinator.get_common_data().get("cooling_mode")
        ):
            await self.coordinator.send_system_command({"cm": 0})

        power_value = _hvac_mode_to_power(normalized_hvac_mode)
        if power_value is None:
            return
        await self.coordinator.send_group_command(
            group_id,
            "c",
            {"p": power_value},
        )

    async def async_turn_on(self) -> None:
        if (
            self._group_data.get("supports_cooling")
            and self.coordinator.get_common_data().get("cooling_mode")
        ):
            await self.async_set_hvac_mode(HVACMode.COOL)
            return
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        group_id = str(self._group_data.get("group_id") or "")
        if not group_id or self._group_data.get("kind") != "c":
            return
        if preset_mode == "away":
            params = {"aw": 1, "ec": 0, "nt": 0}
        elif preset_mode == "eco":
            params = {"aw": 0, "ec": 1, "nt": 0}
        elif preset_mode in {"comfort", "home"}:
            params = {"aw": 0, "ec": 0, "nt": 0}
        elif preset_mode == "sleep":
            params = {"aw": 0, "ec": 0, "nt": 1}
        else:
            return
        await self.coordinator.send_group_command(
            group_id,
            "c",
            params,
        )

    @property
    def _group_data(self) -> dict[str, Any]:
        return self.coordinator.get_group_entity_data(self.entity_key)

    @property
    def _ventilation_data(self) -> dict[str, Any]:
        group_id = str(self._group_data.get("group_id") or "")
        return self.coordinator.get_group_entity_data(f"{group_id}:v") if group_id else {}

    @property
    def _supports_ventilation(self) -> bool:
        return bool(
            self._group_data.get("kind") == "c"
            and self._group_data.get("supports_ventilation")
            and self.coordinator.get_common_data().get("ventilation_modes_enabled")
        )

    @property
    def _ventilation_is_running(self) -> bool:
        return bool(
            self._supports_ventilation
            and self.coordinator.get_common_data().get("ventilation_mode")
            and float(self._ventilation_data.get("pwm") or 0) > 0.05
            and not int(self._group_data.get("heat_confirm") or 0)
        )


DEFAULT_MIN_TEMP_FALLBACK = 5.0
DEFAULT_MAX_TEMP_FALLBACK = 50.0


def _normalize_hvac_mode(hvac_mode: Any) -> HVACMode | None:
    """Normalize HA HVAC mode values."""
    if hvac_mode is None:
        return None

    try:
        return hvac_mode if isinstance(hvac_mode, HVACMode) else HVACMode(hvac_mode)
    except (TypeError, ValueError):
        return None


def _hvac_mode_to_power(hvac_mode: Any) -> int | None:
    """Map HA HVAC mode values to the controller target power flag."""
    normalized = _normalize_hvac_mode(hvac_mode)
    if normalized is None:
        return None

    if normalized == HVACMode.OFF:
        return 0
    if normalized == HVACMode.HEAT:
        return 1
    return None
