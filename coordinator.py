"""Координатор данных для iOhouse Climate с мгновенным обновлением состояния."""
from __future__ import annotations
import asyncio
import logging
import time
from datetime import timedelta
from typing import Any, Dict, Set

import aiohttp
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_API_KEY,
    CONF_ZONES,
    DEFAULT_ZONES,
    API_CLIMATE_ENDPOINT,
    API_ACTION_ENDPOINT,
    API_UPDATE_ENDPOINT,
    DISCOVERY_INTERVAL,
    REGULAR_UPDATE_INTERVAL,
    FAST_UPDATE_INTERVAL,
    ERROR_RETRY_DELAY,
)

_LOGGER = logging.getLogger(__name__)

class IOhouseDataUpdateCoordinator(DataUpdateCoordinator):
    """Координатор данных для iOhouse с мгновенным обновлением состояния."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        entry: ConfigEntry,
    ) -> None:
        """Инициализация координатора."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=REGULAR_UPDATE_INTERVAL,
        )
        
        self.session = session
        self.entry = entry
        self.host = entry.data[CONF_HOST]
        self.port = entry.data.get(CONF_PORT, 80)
        self.api_key = entry.data.get(CONF_API_KEY, "")
        
        _LOGGER.debug("Координатор инициализирован: host=%s, port=%s", self.host, self.port)
        
        # Фазы обновления
        self.active_zones: set[str] = set(entry.data.get(CONF_ZONES, []))
        self.last_discovery: float = 0
        self.discovery_interval = DISCOVERY_INTERVAL.total_seconds()
        
        # Состояние
        self._error_count = 0
        self._max_errors = 3
        self._fast_mode = False
        self._fast_mode_until: float = 0
        
        # НОВАЯ ЛОГИКА: Кэш подтвержденных значений для мгновенного обновления
        self._confirmed_cache: dict[str, Any] = {}  # Кэш подтвержденных значений
        self._cache_timestamps: dict[str, float] = {}  # Время обновления кэша
        self._cache_ttl = 2.0  # Время жизни кэша: 2 секунды
        
        # Защита от дублирования команд
        self._last_commands: dict[str, float] = {}  # {command: timestamp}
        self._command_debounce = 1.5  # Защита от повтора команды

    async def _async_update_data(self) -> dict[str, Any]:
        """Основной метод обновления данных."""
        try:
            current_time = time.time()
            
            # Проверяем нужна ли фаза обнаружения
            if (current_time - self.last_discovery) > self.discovery_interval:
                _LOGGER.debug("Запуск фазы обнаружения зон")
                discovery_data = await self._discovery_phase()
                self.last_discovery = current_time
                
                # Если обнаружены новые зоны, обновляем активные зоны
                if discovery_data and "zones" in discovery_data:
                    new_active_zones = set(discovery_data["zones"].keys())
                    if new_active_zones != self.active_zones:
                        _LOGGER.info("Обнаружены изменения в зонах: %s -> %s", 
                                   self.active_zones, new_active_zones)
                        self.active_zones = new_active_zones
                        self.hass.bus.async_fire(f"{DOMAIN}_zones_changed", {
                            "entry_id": self.entry.entry_id,
                            "zones": list(self.active_zones)
                        })
                
                return discovery_data
            
            # Фаза регулярного обновления
            return await self._regular_update_phase()
            
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            self._error_count += 1
            
            if self._error_count >= self._max_errors:
                _LOGGER.warning("Множественные ошибки, переход в режим восстановления")
                self.update_interval = ERROR_RETRY_DELAY
                try:
                    return await self._discovery_phase()
                except Exception:
                    pass
            
            raise UpdateFailed(f"Ошибка обновления данных: {err}")

    async def _discovery_phase(self) -> dict[str, Any]:
        """Фаза обнаружения - определение всех активных зон."""
        zone_params = "&".join([f"zone_{zone}=1" for zone in DEFAULT_ZONES])
        url = f"http://{self.host}:{self.port}{API_CLIMATE_ENDPOINT}?{zone_params}&common=read"
        
        if self.api_key:
            url += f"&apikey_rest={self.api_key}"

        try:
            async with async_timeout.timeout(8):
                response = await self.session.get(url)
                
                if response.status == 401:
                    raise ConfigEntryAuthFailed("Invalid API key")
                elif response.status != 200:
                    raise UpdateFailed(f"HTTP {response.status}")
                
                raw_data = await response.json()
                return self._process_data_with_cache(raw_data, DEFAULT_ZONES)
                
        except asyncio.TimeoutError:
            raise UpdateFailed("Timeout during discovery phase")

    async def _regular_update_phase(self) -> dict[str, Any]:
        """Фаза регулярного обновления - только активные зоны."""
        if not self.active_zones:
            _LOGGER.warning("Нет активных зон, переключаемся на обнаружение")
            return await self._discovery_phase()
        
        zone_params = "&".join([f"zone_{zone}=1" for zone in self.active_zones])
        url = f"http://{self.host}:{self.port}{API_CLIMATE_ENDPOINT}?{zone_params}&common=read"
        
        if self.api_key:
            url += f"&apikey_rest={self.api_key}"

        try:
            async with async_timeout.timeout(6):
                response = await self.session.get(url)
                
                if response.status == 401:
                    raise ConfigEntryAuthFailed("Invalid API key")
                elif response.status != 200:
                    raise UpdateFailed(f"HTTP {response.status}")
                
                raw_data = await response.json()
                return self._process_data_with_cache(raw_data, self.active_zones)
                
        except asyncio.TimeoutError:
            raise UpdateFailed("Timeout during regular update")

    def _process_data_with_cache(self, raw_data: dict, zones_to_process: set[str]) -> dict[str, Any]:
        """Обработка данных с применением кэша подтвержденных значений."""
        processed_data = {
            "zones": {},
            "common": {},
            "active_zones": set(),
            "timestamp": time.time()
        }
        
        current_time = time.time()
        
        # Очистка устаревшего кэша
        expired_keys = [k for k, timestamp in self._cache_timestamps.items() 
                       if current_time - timestamp > self._cache_ttl]
        for key in expired_keys:
            if key in self._confirmed_cache:
                del self._confirmed_cache[key]
                del self._cache_timestamps[key]
                _LOGGER.debug("Истек кэш для %s", key)
        
        # Обработка зональных данных
        for zone in zones_to_process:
            zone_data = {}
            for key, value in raw_data.items():
                if key.startswith(f"{zone}_"):
                    param_name = key[3:]  # Убираем префикс зоны
                    cache_key = f"{zone}_{param_name}"
                    
                    # НОВАЯ ЛОГИКА: Используем кэш только если он свежий
                    if cache_key in self._confirmed_cache and cache_key in self._cache_timestamps:
                        if current_time - self._cache_timestamps[cache_key] < self._cache_ttl:
                            zone_data[param_name] = self._confirmed_cache[cache_key]
                            _LOGGER.debug("Использован кэш для %s = %s", 
                                        cache_key, self._confirmed_cache[cache_key])
                        else:
                            # Кэш устарел, используем свежие данные
                            zone_data[param_name] = value
                    else:
                        # Нет кэша, используем актуальные данные
                        zone_data[param_name] = value
            
            if zone_data:
                processed_data["zones"][zone] = zone_data
                processed_data["active_zones"].add(zone)
        
        # Обработка общих данных
        common_keys = [
            "summermode", "avalible_update", "fWversion", "u_version"
        ] + [f"out{i}" for i in range(1, 9)]
        
        for key in common_keys:
            if key in raw_data:
                # Применяем ту же логику кэширования для общих данных
                if key in self._confirmed_cache and key in self._cache_timestamps:
                    if current_time - self._cache_timestamps[key] < self._cache_ttl:
                        processed_data["common"][key] = self._confirmed_cache[key]
                        _LOGGER.debug("Использован кэш для общих данных %s = %s", 
                                    key, self._confirmed_cache[key])
                    else:
                        processed_data["common"][key] = raw_data[key]
                else:
                    processed_data["common"][key] = raw_data[key]
        
        # Сброс счетчика ошибок при успешном обновлении
        self._error_count = 0
        
        # Возврат к нормальному интервалу обновления
        if self.update_interval != REGULAR_UPDATE_INTERVAL:
            self.update_interval = REGULAR_UPDATE_INTERVAL
        
        # Проверяем режим быстрого обновления
        if self._fast_mode and time.time() > self._fast_mode_until:
            self._fast_mode = False
            self.update_interval = REGULAR_UPDATE_INTERVAL
            _LOGGER.debug("Выход из режима быстрого обновления")
        
        return processed_data

    async def send_command(self, command: str) -> bool:
        """Отправка команды на контроллер с мгновенным обновлением состояния."""
        current_time = time.time()
        
        # ЗАЩИТА ОТ ДУБЛИРОВАНИЯ КОМАНД
        if command in self._last_commands:
            time_since_last = current_time - self._last_commands[command]
            if time_since_last < self._command_debounce:
                _LOGGER.debug("Команда %s заблокирована (повтор через %.1f сек)", 
                             command, time_since_last)
                return True
        
        self._last_commands[command] = current_time
        
        url = f"http://{self.host}:{self.port}{API_ACTION_ENDPOINT}?{command}"
        
        if self.api_key:
            url += f"&apikey_rest={self.api_key}"

        _LOGGER.debug("Отправка команды: %s", command)

        try:
            async with async_timeout.timeout(5):
                response = await self.session.get(url)
                
                if response.status == 401:
                    _LOGGER.error("Ошибка аутентификации при отправке команды")
                    return False
                elif response.status != 200:
                    _LOGGER.error("HTTP ошибка %s при отправке команды", response.status)
                    return False
                
                result_data = await response.json()
                
                if result_data.get("status") in ["ok", "ок"]:
                    _LOGGER.debug("Команда выполнена успешно: %s", command)
                    
                    # КЛЮЧЕВАЯ НОВАЯ ЛОГИКА: Мгновенное обновление кэша и состояния
                    await self._apply_confirmed_values(result_data, current_time)
                    
                    # Немедленно обновляем UI
                    await self._trigger_immediate_update()
                    
                    return True
                else:
                    _LOGGER.error("Команда отклонена контроллером: %s", result_data)
                    return False
                    
        except Exception as err:
            _LOGGER.error("Ошибка отправки команды: %s", err)
            return False

    async def _apply_confirmed_values(self, response_data: dict, timestamp: float) -> None:
        """Мгновенное применение подтвержденных значений в кэш."""
        for key, value in response_data.items():
            if key == "status":
                continue
                
            # Сохраняем подтвержденное значение в кэш
            self._confirmed_cache[key] = value
            self._cache_timestamps[key] = timestamp
            
            _LOGGER.debug("Кэширован подтвержденный результат %s = %s", key, value)

    async def _trigger_immediate_update(self) -> None:
        """Немедленное обновление UI после выполнения команды."""
        try:
            # Обновляем данные координатора без сетевого запроса
            if self.data:
                # Создаем обновленную копию данных с применением кэша
                updated_data = dict(self.data)
                current_time = time.time()
                
                # Применяем кэшированные значения к текущим данным
                if "zones" in updated_data:
                    for zone, zone_data in updated_data["zones"].items():
                        for param_name in list(zone_data.keys()):
                            cache_key = f"{zone}_{param_name}"
                            if (cache_key in self._confirmed_cache and 
                                cache_key in self._cache_timestamps and
                                current_time - self._cache_timestamps[cache_key] < self._cache_ttl):
                                zone_data[param_name] = self._confirmed_cache[cache_key]
                
                if "common" in updated_data:
                    for key in list(updated_data["common"].keys()):
                        if (key in self._confirmed_cache and 
                            key in self._cache_timestamps and
                            current_time - self._cache_timestamps[key] < self._cache_ttl):
                            updated_data["common"][key] = self._confirmed_cache[key]
                
                # Принудительно обновляем данные и уведомляем слушателей
                self.data = updated_data
                self.async_update_listeners()
                
                _LOGGER.debug("Выполнено немедленное обновление UI")
        
        except Exception as err:
            _LOGGER.error("Ошибка немедленного обновления UI: %s", err)

    async def send_update_command(self) -> bool:
        """Отправка команды обновления прошивки."""
        url = f"http://{self.host}:{self.port}{API_UPDATE_ENDPOINT}?webio_update_flash=1"
        
        if self.api_key:
            url += f"&apikey_rest={self.api_key}"

        try:
            async with async_timeout.timeout(30):
                response = await self.session.get(url)
                
                if response.status == 200:
                    _LOGGER.info("Команда обновления прошивки отправлена")
                    return True
                else:
                    _LOGGER.error("Ошибка отправки команды обновления: HTTP %s", response.status)
                    return False
                    
        except Exception as err:
            _LOGGER.error("Ошибка отправки команды обновления: %s", err)
            return False

    def get_zone_data(self, zone: str) -> dict[str, Any]:
        """Получение данных конкретной зоны."""
        if not self.data or "zones" not in self.data:
            return {}
        return self.data["zones"].get(zone, {})

    def get_common_data(self) -> dict[str, Any]:
        """Получение общих данных."""
        if not self.data or "common" not in self.data:
            return {}
        return self.data["common"]

    @property
    def zones(self) -> set[str]:
        """Активные зоны."""
        return self.active_zones.copy()

    @property
    def available_zones(self) -> set[str]:
        """Зоны с доступными данными."""
        if not self.data or "active_zones" not in self.data:
            return set()
        return self.data["active_zones"].copy()

    def create_common_freeze(self, param: str, value: Any) -> None:
        """Создание заморозки для общих параметров (для совместимости)."""
        # Используем новую систему кэширования вместо старой заморозки
        current_time = time.time()
        self._confirmed_cache[param] = value
        self._cache_timestamps[param] = current_time
        _LOGGER.debug("Создан кэш для общего параметра %s = %s", param, value)

    def _get_affected_zones_for_preset_commands(self, command: str) -> set[str]:
        """Определение зон, затронутых командами пресета, которые требуют обновления данных."""
        affected_zones = set()
        
        # Команды пресетов, которые могут изменить target_temp и другие параметры
        preset_commands = [
            "away_mode", "nightmode", "eco_mode", 
            "home_mode", "comfort_mode", "sleep_mode"
        ]
        
        # Парсим команду для поиска команд пресетов
        command_parts = command.split('&')
        for part in command_parts:
            if '=' not in part:
                continue
                
            param_name, _ = part.split('=', 1)
            
            # Проверяем каждую зону
            for zone in DEFAULT_ZONES:
                zone_prefix = f"{zone}_"
                if param_name.startswith(zone_prefix):
                    param_suffix = param_name[len(zone_prefix):]
                    
                    # Если это команда пресета для этой зоны
                    if param_suffix in preset_commands:
                        affected_zones.add(zone)
                        _LOGGER.debug("Обнаружена команда пресета для зоны %s: %s", zone, param_name)
        
        return affected_zones

    async def _delayed_refresh_zone_data(self, zones: set[str], delay_seconds: float) -> None:
        """Отложенный запрос данных зон после команды пресета."""
        try:
            _LOGGER.debug("Ожидание %.1f сек перед запросом обновленных данных зон %s", delay_seconds, zones)
            await asyncio.sleep(delay_seconds)
            
            # Создаем запрос только для затронутых зон
            zone_params = "&".join([f"zone_{zone}=1" for zone in zones])
            url = f"http://{self.host}:{self.port}{API_CLIMATE_ENDPOINT}?{zone_params}"
            
            if self.api_key:
                url += f"&apikey_rest={self.api_key}"

            _LOGGER.debug("Запрос обновленных данных зон после пресета: %s", zones)

            async with async_timeout.timeout(6):
                response = await self.session.get(url)
                
                if response.status == 200:
                    fresh_data = await response.json()
                    current_time = time.time()
                    
                    # Обновляем кэш свежими данными для затронутых зон
                    updated_params = []
                    for zone in zones:
                        for key, value in fresh_data.items():
                            if key.startswith(f"{zone}_"):
                                param_name = key[3:]  # Убираем префикс зоны
                                
                                # Особенно важно обновить target_temp и связанные параметры
                                important_params = [
                                    "target_temp", "power_state", "away_mode", 
                                    "nightmode", "eco_mode", "temperature"
                                ]
                                
                                if param_name in important_params:
                                    self._confirmed_cache[key] = value
                                    self._cache_timestamps[key] = current_time
                                    updated_params.append(f"{key}={value}")
                    
                    if updated_params:
                        _LOGGER.info("Обновлены данные после пресета: %s", ", ".join(updated_params))
                        
                        # Обновляем UI с новыми данными
                        await self._trigger_immediate_update()
                    
                else:
                    _LOGGER.warning("Ошибка отложенного запроса зон: HTTP %s", response.status)
                    
        except asyncio.TimeoutError:
            _LOGGER.warning("Таймаут отложенного запроса данных зон")
        except asyncio.CancelledError:
            _LOGGER.debug("Отложенный запрос данных зон отменен")
        except Exception as err:
            _LOGGER.error("Ошибка отложенного запроса данных зон: %s", err)

    async def _refresh_zone_data_after_preset(self, zones: set[str], timestamp: float) -> None:
        """Дополнительный запрос данных зон после команды пресета (старый метод, оставлен для совместимости)."""
        # Этот метод теперь не используется, вместо него используется _delayed_refresh_zone_data
        pass