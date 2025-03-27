"""Инициализация интеграции iohouse_climate."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .climate import IOhouseClimateCoordinator, SCAN_INTERVAL

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Настройка интеграции через YAML (не требуется)."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Инициализация конфигурационной записи."""
    hass.data.setdefault(DOMAIN, {})
    
    # Инициализация данных записи
    entry_data = hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": None,
        "entities": {},
        "session": async_get_clientsession(hass)
    }
    
    # Создаем координатор с корректным методом добавления сущностей
    coordinator = IOhouseClimateCoordinator(
        hass=hass,
        session=entry_data["session"],
        entry=entry,
        async_add_entities=lambda entities: hass.data[DOMAIN][entry.entry_id]["entities"].update({e.unique_id: e for e in entities}))
    entry_data["coordinator"] = coordinator
    
    # Настройка периодического обновления
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            coordinator.async_discover_zones,
            SCAN_INTERVAL
        )
    )
    
    # Загрузка платформ
    await hass.config_entries.async_forward_entry_setups(entry, ["climate", "sensor", "valve", "switch", "update"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузка конфигурационной записи."""
    if entry.entry_id in hass.data.get(DOMAIN, {}):
        del hass.data[DOMAIN][entry.entry_id]
    
    # Выгрузка платформ
    unload_climate = await hass.config_entries.async_forward_entry_unload(entry, "climate")
    unload_sensor = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    unload_valve = await hass.config_entries.async_forward_entry_unload(entry, "valve")
    unload_switch = await hass.config_entries.async_forward_entry_unload(entry, "switch")
    unload_update = await hass.config_entries.async_forward_entry_unload(entry, "update")
    return unload_climate and unload_sensor and unload_valve and unload_switch and unload_update



async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)