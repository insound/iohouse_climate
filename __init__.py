"""Инициализация интеграции iOhouse Climate с полной миграцией entity_id и поддержкой шага температуры."""
from __future__ import annotations
import logging
import re
import time

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import entity_registry as er
from homeassistant.const import Platform

from .const import (
    DOMAIN, 
    CONF_ZONE_MIN_TEMP, 
    CONF_ZONE_MAX_TEMP, 
    CONF_ZONE_TEMP_STEP,
    DEFAULT_MIN_TEMP, 
    DEFAULT_MAX_TEMP,
    DEFAULT_ZONE_TEMP_STEP,
    DEFAULT_ZONES
)
from .coordinator import IOhouseDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Поддерживаемые платформы
PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.VALVE,
    Platform.SWITCH,
    Platform.UPDATE,
]

# Версия конфигурации для миграции
CONFIG_VERSION = 2

# Карта транслитерации кириллицы в латиницу
CYRILLIC_TO_LATIN = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    # Заглавные буквы
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
    'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
    'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
    'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
    'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
}

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Настройка интеграции через YAML (не требуется)."""
    return True

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Миграция старой конфигурационной записи на новую версию."""
    _LOGGER.info("Запуск миграции конфигурации с версии %s на %s", 
                config_entry.version, CONFIG_VERSION)
    
    # Создаем новые данные на основе существующих
    new_data = dict(config_entry.data)
    new_options = dict(config_entry.options)
    
    # Миграция с версии 1 на 2
    if config_entry.version == 1:
        # Добавляем температурные диапазоны по умолчанию если отсутствуют
        zones = new_data.get("zones", [])
        
        if CONF_ZONE_MIN_TEMP not in new_data and zones:
            new_data[CONF_ZONE_MIN_TEMP] = {zone: DEFAULT_MIN_TEMP for zone in zones}
            _LOGGER.debug("Добавлены минимальные температуры для зон: %s", zones)
            
        if CONF_ZONE_MAX_TEMP not in new_data and zones:
            new_data[CONF_ZONE_MAX_TEMP] = {zone: DEFAULT_MAX_TEMP for zone in zones}
            _LOGGER.debug("Добавлены максимальные температуры для зон: %s", zones)
        
        # НОВОЕ: Добавляем шаг температуры для зон по умолчанию если отсутствует
        if CONF_ZONE_TEMP_STEP not in new_data and zones:
            new_data[CONF_ZONE_TEMP_STEP] = {zone: DEFAULT_ZONE_TEMP_STEP for zone in zones}
            _LOGGER.debug("Добавлены шаги температуры для зон: %s", zones)
        
        # КЛЮЧЕВОЕ ДОПОЛНЕНИЕ: Миграция entity_id для сохранения пользовательских настроек
        try:
            await _async_migrate_entities(hass, config_entry)
            _LOGGER.info("Миграция entity успешно завершена")
        except Exception as err:
            _LOGGER.error("Ошибка миграции entity: %s", err)
            # Не прерываем миграцию из-за ошибок с entity
    
    # Обновляем версию конфигурации
    hass.config_entries.async_update_entry(
        config_entry,
        data=new_data,
        options=new_options,
        version=CONFIG_VERSION
    )
    
    _LOGGER.info("Миграция конфигурации завершена успешно")
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Инициализация конфигурационной записи."""
    _LOGGER.debug("Настройка интеграции для %s (версия %s)", 
                 entry.data.get("name", "Unknown"), entry.version)
    
    # Инициализация доменных данных
    hass.data.setdefault(DOMAIN, {})
    
    # Создание HTTP сессии
    session = async_get_clientsession(hass)
    
    # Создание координатора данных
    coordinator = IOhouseDataUpdateCoordinator(hass, session, entry)
    
    # Сохранение координатора в данных домена
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }
    
    # Первичная загрузка данных
    await coordinator.async_config_entry_first_refresh()
    
    # Загрузка всех платформ
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    _LOGGER.info("Интеграция iOhouse Climate настроена для %s с зонами: %s", 
                entry.data.get("name"), list(coordinator.zones))
    
    return True

async def _async_migrate_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Миграция сущностей на новые unique_id с сохранением старых entity_id."""
    entity_registry = er.async_get(hass)
    device_name = entry.data.get("name", "iOhouse")
    zones = entry.data.get("zones", [])
    
    # Получаем все сущности интеграции
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    
    migration_count = 0
    removal_count = 0
    
    _LOGGER.info("Начинаем миграцию %d entity для entry %s", len(entities), entry.entry_id)
    
    for entity in entities:
        old_unique_id = entity.unique_id
        old_entity_id = entity.entity_id
        platform = entity.domain
        
        # Определяем новый unique_id на основе старого паттерна
        new_unique_id = _convert_old_to_new_unique_id(old_unique_id, entry.entry_id, platform)
        
        if new_unique_id is None:
            # Не удалось конвертировать - возможно это уже новый формат или неизвестный паттерн
            _LOGGER.debug("Пропускаем entity %s - не удалось определить новый unique_id", old_entity_id)
            continue
        
        if new_unique_id == old_unique_id:
            # unique_id уже в новом формате
            _LOGGER.debug("Entity %s уже в новом формате", old_entity_id)
            continue
        
        # Проверяем не существует ли уже entity с новым unique_id
        existing_entity = entity_registry.async_get_entity_id(platform, DOMAIN, new_unique_id)
        if existing_entity:
            # Entity с новым unique_id уже существует - удаляем старый
            _LOGGER.info("Удаляем дублирующий старый entity: %s", old_entity_id)
            entity_registry.async_remove(old_entity_id)
            removal_count += 1
            continue
        
        # Выполняем миграцию unique_id с сохранением entity_id
        try:
            entity_registry.async_update_entity(
                old_entity_id, 
                new_unique_id=new_unique_id
            )
            _LOGGER.info("Мигрирован entity: %s (unique_id: %s -> %s)", 
                        old_entity_id, old_unique_id, new_unique_id)
            migration_count += 1
            
        except ValueError as err:
            _LOGGER.warning("Не удалось мигрировать entity %s: %s", old_entity_id, err)
    
    _LOGGER.info("Миграция entity завершена: обновлено %d, удалено %d", 
                migration_count, removal_count)

def _convert_old_to_new_unique_id(old_unique_id: str, entry_id: str, platform: str) -> str | None:
    """Конвертация старого unique_id в новый формат."""
    
    # Паттерны старых unique_id для разных платформ
    if platform == "climate":
        # Старый: iohouse_climate_{device_name}_{zone}
        # Новый: iohouse_climate_{entry_id}_{zone}
        pattern = rf"^{DOMAIN}_(.+)_([ab][12])$"
        match = re.match(pattern, old_unique_id.lower())
        if match:
            zone = match.group(2)
            return f"{DOMAIN}_{entry_id}_{zone}"
    
    elif platform == "sensor":
        if "pwm" in old_unique_id or "modulation" in old_unique_id:
            # Старый: iohouse_climate-{entry_id}-{zone}-pwm
            # Новый: iohouse_climate_{entry_id}_{zone}_pwm
            pattern = rf"^{DOMAIN}-([^-]+)-([ab][12])-pwm$"
            match = re.match(pattern, old_unique_id)
            if match:
                zone = match.group(2)
                return f"{DOMAIN}_{entry_id}_{zone}_pwm"
        
        elif "firmware" in old_unique_id or "fw" in old_unique_id:
            # Старый: iohouse_climate-fw-version-{entry_id}
            # Новый: iohouse_climate_{entry_id}_firmware_version
            return f"{DOMAIN}_{entry_id}_firmware_version"
    
    elif platform == "switch":
        if "summer" in old_unique_id:
            # Старый: iohouse_climate-summer-mode-{entry_id}
            # Новый: iohouse_climate_{entry_id}_summer_mode
            return f"{DOMAIN}_{entry_id}_summer_mode"
        
        elif "out" in old_unique_id:
            # Старый: iohouse_climate-out{num}-{entry_id}
            # Новый: iohouse_climate_{entry_id}_out{num}
            pattern = rf"^{DOMAIN}-out(\d+)-([^-]+)$"
            match = re.match(pattern, old_unique_id)
            if match:
                out_num = match.group(1)
                return f"{DOMAIN}_{entry_id}_out{out_num}"
    
    elif platform == "valve":
        # Старый: iohouse_climate-{entry_id}-{zone}-valve
        # Новый: iohouse_climate_{entry_id}_{zone}_valve
        pattern = rf"^{DOMAIN}-([^-]+)-([ab][12])-valve$"
        match = re.match(pattern, old_unique_id)
        if match:
            zone = match.group(2)
            return f"{DOMAIN}_{entry_id}_{zone}_valve"
    
    elif platform == "update":
        # Старый: iohouse_climate-firmware-{entry_id}
        # Новый: iohouse_climate_{entry_id}_firmware_update
        if "firmware" in old_unique_id:
            return f"{DOMAIN}_{entry_id}_firmware_update"
    
    return None

def _extract_zone_from_old_id(entity_id: str) -> str | None:
    """Извлечение зоны из старого entity_id."""
    # Ищем паттерны a1, a2, b1, b2 в entity_id
    match = re.search(r'[ab][12]', entity_id.lower())
    return match.group(0) if match else None

def _extract_output_number(entity_id: str) -> str | None:
    """Извлечение номера выхода из entity_id."""
    match = re.search(r'out(\d+)', entity_id.lower())
    return match.group(1) if match else None

def _transliterate_cyrillic(text: str) -> str:
    """Транслитерация кириллицы в латиницу."""
    result = ""
    for char in text:
        if char in CYRILLIC_TO_LATIN:
            result += CYRILLIC_TO_LATIN[char]
        else:
            result += char
    return result

def _create_safe_entity_name(zone: str, zone_name: str) -> str:
    """Создание безопасного имени сущности без кириллицы."""
    # Транслитерируем кириллицу
    clean_name = _transliterate_cyrillic(zone_name)
    
    # Приводим к нижнему регистру
    clean_name = clean_name.lower()
    
    # Заменяем пробелы и специальные символы на подчеркивания
    clean_name = re.sub(r'[\s\-\.]+', '_', clean_name)
    
    # Убираем символы кроме букв, цифр и подчеркиваний
    clean_name = re.sub(r'[^\w]', '', clean_name)
    
    # Убираем множественные подчёркивания
    clean_name = re.sub(r'_+', '_', clean_name)
    
    # Убираем подчеркивания в начале и конце
    clean_name = clean_name.strip('_')
    
    # Если после очистки ничего не осталось, используем зону
    if not clean_name:
        clean_name = f"zone_{zone}"
    
    return f"{zone}_{clean_name}"

def _create_safe_device_name(device_name: str) -> str:
    """Создание безопасного имени устройства без кириллицы."""
    # Транслитерируем кириллицу
    clean_name = _transliterate_cyrillic(device_name)
    
    # Приводим к нижнему регистру
    clean_name = clean_name.lower()
    
    # Заменяем пробелы и специальные символы на подчеркивания  
    clean_name = re.sub(r'[\s\-\.]+', '_', clean_name)
    
    # Убираем символы кроме букв, цифр и подчеркиваний
    clean_name = re.sub(r'[^\w]', '', clean_name)
    
    # Убираем множественные подчёркивания
    clean_name = re.sub(r'_+', '_', clean_name)
    
    # Убираем подчеркивания в начале и конце
    clean_name = clean_name.strip('_')
    
    # Если после очистки ничего не осталось, используем дефолт
    if not clean_name:
        clean_name = "iOhouse"
    
    return clean_name

def _is_valid_entity_id(entity_id: str) -> bool:
    """Проверка корректности entity_id."""
    # entity_id должен быть формата platform.name
    if '.' not in entity_id:
        return False
    
    platform, name = entity_id.split('.', 1)
    
    # Проверяем что имя содержит только разрешенные символы
    if not re.match(r'^[a-z0-9_]+$', name):
        return False
    
    # Проверяем что не начинается и не заканчивается подчеркиванием
    if name.startswith('_') or name.endswith('_'):
        return False
    
    # Проверяем что нет множественных подчеркиваний
    if '__' in name:
        return False
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузка конфигурационной записи."""
    _LOGGER.debug("Выгрузка интеграции для %s", entry.data.get("name", "Unknown"))
    
    # Выгрузка всех платформ
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    # Удаление данных из домена
    if unload_ok and entry.entry_id in hass.data.get(DOMAIN, {}):
        hass.data[DOMAIN].pop(entry.entry_id)
        
        # Если это была последняя запись, очищаем домен
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    
    _LOGGER.info("Интеграция iOhouse Climate выгружена для %s", entry.data.get("name"))
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Перезагрузка конфигурационной записи."""
    _LOGGER.debug("Перезагрузка интеграции для %s", entry.data.get("name", "Unknown"))
    await hass.config_entries.async_reload(entry.entry_id)