"""Sensor platform для отображения PWM термостатов iOhouse (без дублирования версии прошивки)."""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import PERCENTAGE

from .const import DOMAIN, CONF_NAME
from .coordinator import IOhouseDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация платформы сенсоров."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Создаем только PWM сенсоры для всех активных зон
    entities = []
    for zone in coordinator.zones:
        entities.append(IOhousePwmSensor(coordinator, entry, zone))
    
    # УБРАНО: Сенсор версии прошивки (дублирует update entity)
    # entities.append(IOhouseFirmwareVersionSensor(coordinator, entry))
    
    async_add_entities(entities, update_before_add=True)
    
    # Обработчик изменения зон
    @callback
    def handle_zones_changed(event):
        """Обработка изменения списка зон."""
        if event.data.get("entry_id") == entry.entry_id:
            new_zones = set(event.data.get("zones", []))
            existing_zones = {entity.zone for entity in entities if hasattr(entity, 'zone')}
            
            # Добавляем PWM сенсоры для новых зон
            added_zones = new_zones - existing_zones
            if added_zones:
                new_entities = [
                    IOhousePwmSensor(coordinator, entry, zone)
                    for zone in added_zones
                ]
                async_add_entities(new_entities, update_before_add=True)
                entities.extend(new_entities)
                _LOGGER.info("Добавлены PWM сенсоры для зон: %s", added_zones)
    
    # Подписка на события изменения зон
    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_zones_changed", handle_zones_changed)
    )

class IOhousePwmSensor(CoordinatorEntity, SensorEntity):
    """PWM сенсор для зоны iOhouse."""
    
    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:percent"
    _attr_suggested_display_precision = 1
    _attr_has_entity_name = True
    _attr_name = "PWM Level"

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        zone: str,
    ) -> None:
        """Инициализация PWM сенсора."""
        super().__init__(coordinator)
        
        self.coordinator = coordinator
        self.entry = entry
        self.zone = zone
        
        # Получаем имя зоны из данных контроллера
        zone_data = coordinator.get_zone_data(zone)
        zone_name = zone_data.get("name", f"Zone {zone.upper()}")
        
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{zone}_pwm"
        self._zone_name = zone_name
        
        _LOGGER.debug("Создан PWM сенсор %s для зоны %s (%s)", 
                     self._attr_unique_id, zone, zone_name)

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
        """Доступность сенсора."""
        return (
            self.coordinator.last_update_success
            and self.zone in self.coordinator.available_zones
        )

    @property
    def native_value(self) -> float | None:
        """Текущее значение PWM."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        return zone_data.get("pwm", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Дополнительные атрибуты состояния."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        
        return {
            "zone": self.zone,
            "zone_name": self._zone_name,
            "power_state": zone_data.get("power_state", 0),
            "burner": zone_data.get("burner", 0),
        }

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

