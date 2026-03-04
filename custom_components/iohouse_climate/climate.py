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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_UNITS_CHANGED, SUPPORT_MODES, SUPPORT_PRESETS
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import (
    format_target_temperature,
    get_unit_device_info,
    get_unit_label,
    get_unit_settings,
    is_manual_unit,
    unit_supports_presets,
    unit_supports_target_temperature,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities for all discovered units."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: dict[str, IOhouseClimateEntity] = {}

    def _create_entities() -> list[IOhouseClimateEntity]:
        new_entities: list[IOhouseClimateEntity] = []
        for unit_id in coordinator.units:
            if unit_id in entities:
                continue
            entity = IOhouseClimateEntity(coordinator, entry, unit_id)
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
                "Added ioHouse climate entities for units: %s",
                [entity.unit_id for entity in new_entities],
            )

    entry.async_on_unload(hass.bus.async_listen(EVENT_UNITS_CHANGED, handle_units_changed))


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
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.unit_id = unit_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unit_id}"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return unit device info."""
        return get_unit_device_info(self.entry, self.unit_id, self._unit_data)

    @property
    def available(self) -> bool:
        """Entity availability follows the latest state payload."""
        return (
            self.coordinator.last_update_success
            and self.unit_id in self.coordinator.available_units
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
        features = ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
        if unit_supports_target_temperature(self._unit_data):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if unit_supports_presets(self._unit_data):
            features |= ClimateEntityFeature.PRESET_MODE
        return features

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
        if not unit_supports_target_temperature(self._unit_data):
            return None
        return self._unit_data.get("target_temp")

    @property
    def hvac_mode(self) -> HVACMode:
        """Use target power as the user-facing HVAC mode."""
        if int(self._unit_data.get("target_power") or self._unit_data.get("power") or 0):
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Best-effort action based on current state."""
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        if int(self._unit_data.get("burner") or 0):
            return HVACAction.HEATING

        if int(self._unit_data.get("power") or 0):
            return HVACAction.HEATING

        if int(self._unit_data.get("valve_opening") or 0) or int(self._unit_data.get("valve_closing") or 0):
            return HVACAction.HEATING

        return HVACAction.IDLE

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
            "group_id": self._unit_data.get("group_id"),
            "group_name": self._unit_data.get("group_name"),
            "selected_mode": self._unit_data.get("selected_mode"),
            "device_type": self._unit_data.get("device_type"),
            "power": self._unit_data.get("power"),
            "target_power": self._unit_data.get("target_power"),
            "pwm": self._unit_data.get("pwm"),
            "burner": self._unit_data.get("burner"),
            "heat_confirm": self._unit_data.get("heat_confirm"),
            "slave": self._unit_data.get("slave"),
            "manual_mode": is_manual_unit(self._unit_data),
        }

    async def async_set_temperature(self, **kwargs) -> None:
        """Send target temperature through apiaction v2."""
        if not unit_supports_target_temperature(self._unit_data):
            return

        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        min_temp, max_temp, temp_step = get_unit_settings(self.entry, self.unit_id)
        normalized = round(float(temperature) / temp_step) * temp_step
        normalized = min(max(normalized, min_temp), max_temp)

        await self.coordinator.send_zone_command(
            self.unit_id,
            {"tt": format_target_temperature(normalized)},
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Send target power through apiaction v2."""
        await self.coordinator.send_zone_command(
            self.unit_id,
            {"p": 0 if hvac_mode == HVACMode.OFF else 1},
        )

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
