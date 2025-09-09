"""Climate platform для термостатов iOhouse с быстрым откликом."""
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

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_ZONE_MIN_TEMP,
    CONF_ZONE_MAX_TEMP,
    CONF_ZONE_TEMP_STEP,  # НОВОЕ
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    DEFAULT_ZONE_TEMP_STEP,  # НОВОЕ
    TEMPERATURE_STEP,  # Оставляем как fallback
    SUPPORT_MODES,
    SUPPORT_PRESETS,
)
from .coordinator import IOhouseDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация платформы климата."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Создаем климатические сущности для всех активных зон
    entities = []
    for zone in coordinator.zones:
        entities.append(IOhouseClimateEntity(coordinator, entry, zone))
    
    async_add_entities(entities, update_before_add=True)
    
    # Обработчик изменения зон
    @callback
    def handle_zones_changed(event):
        """Обработка изменения списка зон."""
        if event.data.get("entry_id") == entry.entry_id:
            new_zones = set(event.data.get("zones", []))
            existing_zones = {entity.zone for entity in entities if hasattr(entity, 'zone')}
            
            # Добавляем новые зоны
            added_zones = new_zones - existing_zones
            if added_zones:
                new_entities = [
                    IOhouseClimateEntity(coordinator, entry, zone)
                    for zone in added_zones
                ]
                async_add_entities(new_entities, update_before_add=True)
                entities.extend(new_entities)
                _LOGGER.info("Добавлены климатические сущности для зон: %s", added_zones)
    
    # Подписка на события изменения зон
    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_zones_changed", handle_zones_changed)
    )

class IOhouseClimateEntity(CoordinatorEntity, ClimateEntity):
    """Климатическая сущность iOhouse с быстрым откликом."""
    
    _attr_icon = "mdi:thermostat"
    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_hvac_modes = SUPPORT_MODES
    _attr_preset_modes = SUPPORT_PRESETS

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        zone: str,
    ) -> None:
        """Инициализация климатической сущности."""
        super().__init__(coordinator)
        
        self.coordinator = coordinator
        self.entry = entry
        self.zone = zone
        self._device_name = entry.data[CONF_NAME]
        
        # Получаем температурные диапазоны из конфигурации
        zone_min_temps = entry.data.get(CONF_ZONE_MIN_TEMP, {})
        zone_max_temps = entry.data.get(CONF_ZONE_MAX_TEMP, {})
        zone_temp_steps = entry.data.get(CONF_ZONE_TEMP_STEP, {})  # НОВОЕ
        
        self._attr_min_temp = zone_min_temps.get(zone, DEFAULT_MIN_TEMP)
        self._attr_max_temp = zone_max_temps.get(zone, DEFAULT_MAX_TEMP)
        
        # НОВОЕ: Устанавливаем индивидуальный шаг температуры для зоны
        self._zone_temp_step = zone_temp_steps.get(zone, DEFAULT_ZONE_TEMP_STEP)
        self._attr_target_temperature_step = self._zone_temp_step
        
        # Получаем имя зоны из данных контроллера
        zone_data = coordinator.get_zone_data(zone)
        zone_name = zone_data.get("name", f"Zone {zone.upper()}")
        
        # Уникальный ID и имя
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{zone}"
        self._zone_name = zone_name
        
        _LOGGER.debug("Создана климатическая сущность %s для зоны %s (%s) с диапазоном %.1f-%.1f°C, шаг %.3f°C", 
                     self._attr_unique_id, zone, zone_name, self._attr_min_temp, self._attr_max_temp, self._zone_temp_step)

    @property
    def device_info(self) -> dict[str, Any]:
        """Информация об устройстве."""
        return {
            "identifiers": {(DOMAIN, f"{self.entry.entry_id}_{self.zone}")},
            "name": f"{self.zone.upper()} {self._zone_name}",
            "manufacturer": "iOhouse",
            "model": "Thermozone Controller",
        }

    @property
    def available(self) -> bool:
        """Доступность сущности."""
        return (
            self.coordinator.last_update_success
            and self.zone in self.coordinator.available_zones
        )

    @property
    def current_temperature(self) -> float | None:
        """Текущая температура с точностью по шагу зоны."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        temp = zone_data.get("temperature")
        
        if temp is not None:
            # ИЗМЕНЕНО: Округляем до шага зоны вместо глобального TEMPERATURE_STEP
            return round(float(temp) / self._zone_temp_step) * self._zone_temp_step
        
        return None

    @property
    def target_temperature(self) -> float | None:
        """Целевая температура."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        target_temp = zone_data.get("target_temp")
        
        if target_temp is not None:
            # ИЗМЕНЕНО: Округляем до шага зоны вместо глобального TEMPERATURE_STEP
            return round(float(target_temp) / self._zone_temp_step) * self._zone_temp_step
        
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Текущий режим HVAC."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        power_state = zone_data.get("power_state", 0)
        return HVACMode.HEAT if power_state else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Текущее действие HVAC."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        power_state = zone_data.get("power_state", 0)
        
        if not power_state:
            return HVACAction.OFF
        
        burner = zone_data.get("burner", 0)
        return HVACAction.HEATING if burner else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Текущий режим пресета."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        
        nightmode = zone_data.get("nightmode", 0)
        away_mode = zone_data.get("away_mode", 0)
        eco_mode = zone_data.get("eco_mode", 0)
        
        if nightmode:
            return "sleep"
        elif away_mode:
            return "away"
        elif eco_mode:
            return "eco"
        else:
            return "comfort"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Дополнительные атрибуты состояния."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        
        return {
            "zone": self.zone,
            "zone_name": self._zone_name,
            "modulation_level": zone_data.get("pwm", 0),
            "power_state": zone_data.get("power_state", 0),
            "burner": zone_data.get("burner", 0),
            "nightmode": zone_data.get("nightmode", 0),
            "away_mode": zone_data.get("away_mode", 0),
            "eco_mode": zone_data.get("eco_mode", 0),
            "min_temp": self._attr_min_temp,
            "max_temp": self._attr_max_temp,
            "temp_step": self._zone_temp_step,  # НОВОЕ: Добавляем шаг в атрибуты
        }

    async def async_set_temperature(self, **kwargs) -> None:
        """Установка целевой температуры с мгновенным откликом."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        
        # ИЗМЕНЕНО: Округляем до шага зоны вместо глобального TEMPERATURE_STEP
        temperature = round(temperature / self._zone_temp_step) * self._zone_temp_step
        
        # Проверяем диапазон температуры
        if not (self._attr_min_temp <= temperature <= self._attr_max_temp):
            _LOGGER.warning(
                "Температура %.3f вне диапазона %.1f-%.1f для зоны %s",
                temperature, self._attr_min_temp, self._attr_max_temp, self.zone
            )
            return
        
        # БЫСТРЫЙ вызов команды - координатор сам обновит UI мгновенно
        command = f"{self.zone}_target_temp={temperature}"
        
        if await self.coordinator.send_command(command):
            _LOGGER.debug("Установлена температура %.3f для зоны %s", temperature, self.zone)
        else:
            _LOGGER.error("Ошибка установки температуры для зоны %s", self.zone)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Установка режима HVAC с мгновенным откликом."""
        power_state = 1 if hvac_mode != HVACMode.OFF else 0
        
        # БЫСТРЫЙ вызов команды - координатор сам обновит UI мгновенно
        command = f"{self.zone}_power={power_state}"
        
        if await self.coordinator.send_command(command):
            _LOGGER.debug("Установлен режим %s для зоны %s", hvac_mode, self.zone)
        else:
            _LOGGER.error("Ошибка установки режима HVAC для зоны %s", self.zone)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Установка режима пресета с мгновенным откликом."""
        commands = []
        
        # Определяем команды для каждого пресета
        if preset_mode == "away":
            commands = [f"{self.zone}_away_mode=1", f"{self.zone}_nightmode=0"]
            
        elif preset_mode == "eco":
            commands = [f"{self.zone}_eco_mode=1"]
            
        elif preset_mode == "comfort":
            commands = [
                f"{self.zone}_away_mode=0",
                f"{self.zone}_eco_mode=0", 
                f"{self.zone}_nightmode=0"
            ]
            
        elif preset_mode == "home":
            commands = [f"{self.zone}_away_mode=0"]
            
        elif preset_mode == "sleep":
            commands = [f"{self.zone}_nightmode=1"]
            
        else:
            _LOGGER.error("Неизвестный режим пресета: %s", preset_mode)
            return
        
        # БЫСТРЫЙ вызов команды - координатор сам обновит UI мгновенно
        command = "&".join(commands)
        
        if await self.coordinator.send_command(command):
            _LOGGER.debug("Установлен пресет %s для зоны %s", preset_mode, self.zone)
        else:
            _LOGGER.error("Ошибка установки пресета для зоны %s", self.zone)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Обработка обновления от координатора."""
        # Обновляем имя зоны если оно изменилось
        zone_data = self.coordinator.get_zone_data(self.zone)
        new_zone_name = zone_data.get("name", f"Zone {self.zone.upper()}")
        
        if new_zone_name != self._zone_name:
            self._zone_name = new_zone_name
            _LOGGER.debug("Обновлено имя зоны %s: %s", self.zone, new_zone_name)
        
        super()._handle_coordinator_update()