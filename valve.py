"""Valve platform для клапанов ioHouse."""
from __future__ import annotations
import logging

from homeassistant.components.valve import ValveEntity, ValveEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .climate import IOhouseClimateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация платформы клапанов с проверкой дублирования."""
    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    
    # Проверяем, была ли платформа уже инициализирована
    if "valve_init" in entry_data:
        _LOGGER.debug("Valve platform already initialized for entry %s", entry.entry_id)
        return
    
    coordinator = entry_data.get("coordinator")
    if not coordinator:
        _LOGGER.error("Coordinator not available")
        return

    # Помечаем платформу как инициализированную
    entry_data["valve_init"] = True

    # Добавляем существующие клапаны
    initial_valves = [
        IOhouseValveEntity(coordinator, zone)
        for zone in coordinator.active_zones
        if _has_valve_data(coordinator.data.get(zone, {}))
    ]
    async_add_entities(initial_valves, update_before_add=True)

    # Регистрируем обработчик с привязкой к жизненному циклу
    def _valve_update_handler(new_zones: set[str]):
        """Обработчик обновления зон для клапанов."""
        hass.async_create_task(
            _async_add_new_valves(hass, async_add_entities, coordinator, new_zones, entry)  # Добавляем entry
        )

    # Удаляем обработчик при выгрузке конфига
    entry.async_on_unload(
        lambda: coordinator.set_valve_platform_handler(None)
    )
    coordinator.set_valve_platform_handler(_valve_update_handler)

async def _async_add_new_valves(
    hass: HomeAssistant,
    async_add_entities: AddEntitiesCallback,
    coordinator: IOhouseClimateCoordinator,
    new_zones: set[str],
    entry: ConfigEntry  # Добавляем параметр entry
) -> None:
    """Добавление новых клапанов при обнаружении зон."""
    _LOGGER.debug("Processing new zones for valves: %s", new_zones)

    existing_ids = {
        entity.unique_id
        for entity in hass.data[DOMAIN][entry.entry_id].get("valves", [])
    }

    valves = []
    for zone in new_zones:  # Область видимости переменной zone - только внутри цикла
        zone_data = coordinator.data.get(zone, {})
        _LOGGER.debug("Zone data for %s: %s", zone, zone_data)  # <-- Исправлено
        if not _has_valve_data(zone_data):
            continue
        
        unique_id = f"{DOMAIN}-{coordinator.entry.entry_id}-{zone}-valve"
        if unique_id in existing_ids:
            continue
            
        _LOGGER.info("Creating new valve entity: %s", unique_id)
        valves.append(IOhouseValveEntity(coordinator, zone))
    
    if valves:
        hass.data[DOMAIN][entry.entry_id].setdefault("valves", []).extend(valves)
        async_add_entities(valves, update_before_add=True)

def _has_valve_data(zone_data: dict) -> bool:
    """Проверяет наличие данных о клапане в зоне."""
    _LOGGER.debug("Checking valve data in zone: %s", zone_data)
    return any("_valve" in key for key in zone_data.keys())  # Ищем "_valve" в любом месте ключа


class IOhouseValveEntity(ValveEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC  # Теперь импортировано
    _attr_icon = "mdi:valve"
    _attr_supported_features = ValveEntityFeature(0)

    def __init__(self, coordinator: IOhouseClimateCoordinator, zone: str):
        if zone not in coordinator.entities:
            raise ValueError(f"Climate entity for zone {zone} not found")
        climate_entity = coordinator.entities[zone]

        if not climate_entity:
            _LOGGER.error(
                "Не удалось создать клапан для зоны %s: климатическая сущность отсутствует. "
                "Проверьте порядок инициализации платформ.", 
                zone
            )
            raise ValueError(f"Climate entity missing for zone {zone}")
        
        # Привязка к устройству через климатическую сущность
        self._attr_device_info = climate_entity.device_info
        self._attr_name = f"{climate_entity.name} Valve"
        self._attr_unique_id = f"{DOMAIN}-{coordinator.entry.entry_id}-{zone}-valve"
        self._zone = zone
        self.coordinator = coordinator


    @property
    def reports_position(self) -> bool:
        """Указывает, поддерживает ли клапан отображение позиции."""
        return True  # Если есть данные вроде a1_valve_pos, иначе False

    @property
    def current_valve_position(self) -> int | None:
        """Возвращает текущую позицию клапана (0-100)."""
        return self.coordinator.data[self._zone].get(f"{self._zone}_valve_pos")

    @property
    def is_opening(self) -> bool:
        return bool(self.coordinator.data[self._zone].get(f"{self._zone}_valve_opening"))

    @property
    def is_closing(self) -> bool:
        return bool(self.coordinator.data[self._zone].get(f"{self._zone}_valve_closing"))

    @property
    def is_closed(self) -> bool:
        return bool(self.coordinator.data[self._zone].get(f"{self._zone}_valve_closed"))

    @property
    def available(self) -> bool:
        return (
            self.coordinator.available
            and self._zone in self.coordinator.active_zones
            and _has_valve_data(self.coordinator.data.get(self._zone, {}))
        )
        if not self.coordinator.available:
            return self._last_available and (time.time() - self._last_unavailable < 30)
        return True

    async def async_update(self) -> None:
        await self.coordinator.async_discover_zones()