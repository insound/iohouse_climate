"""Переключатели для интеграции iOhouse с простыми командами."""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_NAME
from .coordinator import IOhouseDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация платформы переключателей."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Создаем переключатели
    entities = []
    
    # Переключатель летнего режима
    entities.append(SummerModeSwitch(coordinator, entry))
    
    # Переключатели выходов (out1-out8)
    for i in range(1, 9):
        entities.append(OutputSwitch(coordinator, entry, i))
    
    async_add_entities(entities, update_before_add=True)

class BaseIOhouseSwitch(CoordinatorEntity, SwitchEntity):
    """Базовый класс для переключателей iOhouse."""
    
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Инициализация базового переключателя."""
        super().__init__(coordinator)
        
        self.coordinator = coordinator
        self.entry = entry
        self._device_name = entry.data[CONF_NAME]

    @property
    def device_info(self) -> dict[str, Any]:
        """Информация об устройстве."""
        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": self._device_name,
            "manufacturer": "iOhouse",
            "model": "Thermozone Controller",
        }

    @property
    def available(self) -> bool:
        """Доступность переключателя."""
        return self.coordinator.last_update_success

class SummerModeSwitch(BaseIOhouseSwitch):
    """Переключатель летнего режима с простыми командами."""
    
    _attr_icon = "mdi:sun-thermometer"
    _attr_name = "Summer Mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Инициализация переключателя летнего режима."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_summer_mode"
        
        _LOGGER.debug("Создан переключатель летнего режима %s", self._attr_unique_id)

    @property
    def is_on(self) -> bool:
        """Состояние летнего режима."""
        common_data = self.coordinator.get_common_data()
        return common_data.get("summermode", 0) == 1

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Дополнительные атрибуты состояния."""
        return {
            "description": "Enables summer mode operation",
            "device_name": self._device_name,
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Включение летнего режима. Координатор сам создает заморозку."""
        # ПРОСТОЙ вызов команды - координатор сам создаст заморозку
        if await self.coordinator.send_command("summermode=1"):
            _LOGGER.debug("Летний режим включен")
        else:
            _LOGGER.error("Не удалось включить летний режим")

    async def async_turn_off(self, **kwargs) -> None:
        """Выключение летнего режима. Координатор сам создает заморозку."""
        # ПРОСТОЙ вызов команды - координатор сам создаст заморозку
        if await self.coordinator.send_command("summermode=0"):
            _LOGGER.debug("Летний режим выключен")
        else:
            _LOGGER.error("Не удалось выключить летний режим")

class OutputSwitch(BaseIOhouseSwitch):
    """Переключатель выхода с простыми командами."""
    
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:electric-switch"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
        output_num: int,
    ) -> None:
        """Инициализация переключателя выхода."""
        super().__init__(coordinator, entry)
        
        self.output_num = output_num
        self._attr_name = f"Output {output_num}"
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_out{output_num}"
        
        _LOGGER.debug("Создан переключатель выхода %s", self._attr_unique_id)

    @property
    def available(self) -> bool:
        """Доступность переключателя выхода."""
        # Проверяем доступность базового координатора
        if not super().available:
            return False
            
        # Дополнительно проверяем наличие данных об этом выходе
        common_data = self.coordinator.get_common_data()
        return f"out{self.output_num}" in common_data

    @property
    def is_on(self) -> bool:
        """Состояние выхода."""
        common_data = self.coordinator.get_common_data()
        return common_data.get(f"out{self.output_num}", 0) == 1

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Дополнительные атрибуты состояния."""
        return {
            "output_number": self.output_num,
            "description": f"Controls output {self.output_num}",
            "device_name": self._device_name,
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Включение выхода. Координатор сам создает заморозку."""
        # ПРОСТОЙ вызов команды - координатор сам создаст заморозку
        command = f"out{self.output_num}=1"
        
        if await self.coordinator.send_command(command):
            _LOGGER.debug("Включен выход %d", self.output_num)
        else:
            _LOGGER.error("Не удалось включить выход %d", self.output_num)

    async def async_turn_off(self, **kwargs) -> None:
        """Выключение выхода. Координатор сам создает заморозку."""
        # ПРОСТОЙ вызов команды - координатор сам создаст заморозку
        command = f"out{self.output_num}=0"
        
        if await self.coordinator.send_command(command):
            _LOGGER.debug("Выключен выход %d", self.output_num)
        else:
            _LOGGER.error("Не удалось выключить выход %d", self.output_num)