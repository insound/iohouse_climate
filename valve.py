"""Valve platform для клапанов iOhouse."""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.valve import (
    ValveEntity,
    ValveEntityFeature,
    ValveDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IOhouseDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация платформы клапанов."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Создаем клапаны для зон, которые имеют данные о клапанах
    entities = []
    for zone in coordinator.zones:
        zone_data = coordinator.get_zone_data(zone)
        if _has_valve_data(zone_data):
            entities.append(IOhouseValveEntity(coordinator, entry, zone))
    
    async_add_entities(entities, update_before_add=True)
    
    # Обработчик изменения зон
    @callback
    def handle_zones_changed(event):
        """Обработка изменения списка зон."""
        if event.data.get("entry_id") == entry.entry_id:
            new_zones = set(event.data.get("zones", []))
            existing_zones = {entity.zone for entity in entities}
            
            # Добавляем клапаны для новых зон с данными о клапанах
            added_zones = new_zones - existing_zones
            if added_zones:
                new_entities = []
                for zone in added_zones:
                    zone_data = coordinator.get_zone_data(zone)
                    if _has_valve_data(zone_data):
                        new_entities.append(IOhouseValveEntity(coordinator, entry, zone))
                
                if new_entities:
                    async_add_entities(new_entities, update_before_add=True)
                    entities.extend(new_entities)
                    _LOGGER.info("Добавлены клапаны для зон: %s", 
                               [entity.zone for entity in new_entities])
    
    # Подписка на события изменения зон
    entry.async_on_unload(
        hass.bus.async_listen(f"{DOMAIN}_zones_changed", handle_zones_changed)
    )

def _has_valve_data(zone_data: dict) -> bool:
    """Проверяет наличие данных о клапане в зоне."""
    valve_keys = [
        "valve_pos", "valve_opening", "valve_closing", "valve_closed"
    ]
    return any(key in zone_data for key in valve_keys)

class IOhouseValveEntity(CoordinatorEntity, ValveEntity):
    """Сущность клапана iOhouse."""
    
    _attr_device_class = ValveDeviceClass.WATER
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:valve"
    _attr_has_entity_name = True
    _attr_name = "Valve"

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        zone: str,
    ) -> None:
        """Инициализация сущности клапана."""
        super().__init__(coordinator)
        
        self.coordinator = coordinator
        self.entry = entry
        self.zone = zone
        
        # Получаем имя зоны из данных контроллера
        zone_data = coordinator.get_zone_data(zone)
        zone_name = zone_data.get("name", f"Zone {zone.upper()}")
        
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{zone}_valve"
        self._zone_name = zone_name
        
        _LOGGER.debug("Создан клапан %s для зоны %s (%s)", 
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
        """Доступность клапана."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        return (
            self.coordinator.last_update_success
            and self.zone in self.coordinator.available_zones
            and _has_valve_data(zone_data)
        )

    @property
    def reports_position(self) -> bool:
        """Указывает, поддерживает ли клапан отображение позиции."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        return "valve_pos" in zone_data

    @property
    def current_valve_position(self) -> int | None:
        """Возвращает текущую позицию клапана (0-100)."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        position = zone_data.get("valve_pos")
        
        if position is not None:
            # Преобразуем в диапазон 0-100 если необходимо
            try:
                pos_int = int(float(position))
                return max(0, min(100, pos_int))
            except (ValueError, TypeError):
                return None
        
        return None

    @property
    def is_opening(self) -> bool | None:
        """Статус открытия клапана."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        opening = zone_data.get("valve_opening")
        
        if opening is not None:
            return bool(opening)
        
        return None

    @property
    def is_closing(self) -> bool | None:
        """Статус закрытия клапана."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        closing = zone_data.get("valve_closing")
        
        if closing is not None:
            return bool(closing)
        
        return None

    @property
    def is_closed(self) -> bool | None:
        """Статус закрытого состояния клапана."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        
        # Проверяем специальный флаг закрытого состояния
        closed = zone_data.get("valve_closed")
        if closed is not None:
            return bool(closed)
        
        # Альтернативно проверяем по позиции
        if self.current_valve_position is not None:
            return self.current_valve_position == 0
        
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Дополнительные атрибуты состояния."""
        zone_data = self.coordinator.get_zone_data(self.zone)
        
        attributes = {
            "zone": self.zone,
            "zone_name": self._zone_name,
        }
        
        # Добавляем все доступные данные о клапане
        valve_data_keys = [
            "valve_pos", "valve_opening", "valve_closing", "valve_closed"
        ]
        
        for key in valve_data_keys:
            if key in zone_data:
                attributes[key] = zone_data[key]
        
        return attributes

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