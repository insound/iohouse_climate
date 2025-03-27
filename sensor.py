"""Sensor platform для отображения уровня PWM термостатов ioHouse."""
from __future__ import annotations
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from .const import (
    DOMAIN,
    CONF_ZONES,
    DEFAULT_ZONES,
)
from .climate import IOhouseClimateEntity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация сенсоров PWM."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]

    coordinator.set_sensor_platform_handler(
        lambda new_zones: hass.async_create_task(
            _async_add_new_sensors(hass, async_add_entities, coordinator, new_zones)

        )
    )
#    await _async_add_new_sensors(hass, async_add_entities, coordinator, coordinator.active_zones)
    await coordinator.async_discover_zones()





    # Создаем сенсоры для всех существующих зон
    sensors = [
        IOhousePwmSensor(coordinator, zone)
        for zone in coordinator.entry.data.get(CONF_ZONES, DEFAULT_ZONES)
    ]
    async_add_entities(sensors, update_before_add=True)

    def _sensor_handler(new_zones: set[str]):
        existing_zones = {s._zone for s in sensors}
        added_zones = new_zones - existing_zones
        if added_zones:
            new_sensors = [IOhousePwmSensor(coordinator, z) for z in added_zones]
            async_add_entities(new_sensors, update_before_add=True)
            async_add_entities([FirmwareVersionSensor(coordinator)])

    coordinator.set_sensor_platform_handler(_sensor_handler)


async def _async_add_new_sensors(
    hass: HomeAssistant,
    async_add_entities: AddEntitiesCallback,
    coordinator: IOhouseClimateCoordinator,
    new_zones: set[str]
) -> None:
    """Добавление новых сенсоров."""
    sensors = [
        IOhousePwmSensor(coordinator, zone)
        for zone in new_zones
        if zone not in coordinator.entities
    ]

    if sensors:
        async_add_entities(sensors, update_before_add=True)
        _LOGGER.info("Added %d new PWM sensors", len(sensors))
    else:
        _LOGGER.info("No new zones found for PWM sensors")




class FirmwareVersionSensor(SensorEntity):
    _attr_icon = "mdi:chip"
    
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_name = "Firmware Version"
        self._attr_unique_id = f"{DOMAIN}-fw-version-{coordinator.entry.entry_id}"
        self._attr_device_info = {"identifiers": {(DOMAIN, coordinator.entry.entry_id)}}

    @property
    def native_value(self):
        return self.coordinator.common_data.get("fWversion", "unknown")







class IOhousePwmSensor(SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:percent"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, zone: str):
        self.coordinator = coordinator
        self._zone = zone
        climate_entity = coordinator.entities.get(zone)
        if not climate_entity:
            self._attr_device_info = None
        else:
            self._attr_device_info = climate_entity.device_info        
        self._zone_name = getattr(climate_entity, "name", f"Zone {zone.upper()}")
        self._unsub_update = None  # Добавляем переменную для хранения отписки

        self._attr_name = f"{zone.upper()} {self._zone_name} PWM Level"   # Имя с зоной
        
        self._attr_device_info = climate_entity.device_info if climate_entity else None
        self._attr_unique_id = f"{DOMAIN}-{coordinator.entry.entry_id}-{zone}-pwm".lower()

        self.coordinator.async_add_listener(self._handle_update)  # Оставляем как есть
        # Привязка к устройству


    async def async_will_remove_from_hass(self) -> None:
        """Отписка при удалении."""
        if self._unsub_update:
            self._unsub_update()
        await super().async_will_remove_from_hass()
        
    async def async_update(self) -> None:
        try:
            if self.coordinator.available:
                self._attr_native_value = self.coordinator.entities[self._zone].extra_state_attributes.get("modulation_level")
                self._attr_available = True
            else:
                self._attr_available = False
        except KeyError:
            self._attr_available = False

    @property
    def native_value(self) -> float:
        """Получение значения PWM из климатической сущности."""
        if not self.coordinator.available:
            return None
        if entity := self.coordinator.entities.get(self._zone):
            return entity.extra_state_attributes.get("modulation_level", 0)
        return 0
    
    @property
    def available(self) -> bool:
        return (
            self.coordinator.available 
            and self._zone in self.coordinator.active_zones 
            and self.coordinator.data.get(self._zone) is not None
        )

    def _handle_update(self, _event=None):
        """Потокобезопасное обновление через add_job."""
        if self.hass and self.entity_id:
            self.hass.add_job(self.async_write_ha_state)  # Обернуть вызов в async_create_background_task


    async def async_added_to_hass(self) -> None:
        """Исправленная подписка на события."""
        """Безопасная подписка на события с обработкой в основном потоке."""
        await super().async_added_to_hass()
        
        # Асинхронный обработчик события
        async def _event_handler(event):
            await self.async_update_ha_state(force_refresh=True)
        
        # Подписка через add_job для потокобезопасности
        self._unsub_update = self.hass.bus.async_listen(
            "iohouse_climate_update",
            lambda event: self.hass.add_job(_event_handler, event)
        )



    
