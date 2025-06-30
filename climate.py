"""Climate platform для интеграции термостатов ioHouse."""
from __future__ import annotations
import asyncio 
import logging
from datetime import timedelta
from typing import Any, Callable
import traceback  # Добавьте эту строку
import aiohttp
import async_timeout
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, CONF_HOST, CONF_NAME, CONF_PORT, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    CONF_API_KEY,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_ZONES,
    MAX_TEMP,
    MIN_TEMP,
    SUPPORT_MODES,
    SUPPORT_PRESETS,
    ERROR_MESSAGES,
)

_LOGGER = logging.getLogger(__name__)
BASE_URL = "http://{0}:{1}{2}"
SCAN_INTERVAL = timedelta(seconds=10)
try_counter = 0

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация платформы через конфигурационную запись."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    session = entry_data["session"]
    coordinator = entry_data["coordinator"]  # Используем существующий
  
    await coordinator.async_discover_zones()
    
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            coordinator.async_discover_zones,
            SCAN_INTERVAL
        )
    )

class IOhouseClimateCoordinator:
    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback
        
    ):
        self._available = False
        self.hass = hass
        self.session = session
        self.entry = entry
        self.async_add_entities = async_add_entities
        self.active_zones: set[str] = set()
        self.entities: dict[str, IOhouseClimateEntity] = {}
        self.data: dict[str, Any] = {}
        self._listeners = []
        self._ready_event = asyncio.Event()
        self._sensor_platform_handler = None
        self._valve_handler = None  # Добавляем инициализацию
        self.common_data = {}  # Отдельный словарь для общих данных
        self.common_listeners = []  # Отдельные слушатели для common_data
        self.common_request_counter = 0  # Счетчик для управления common=read


    def async_add_common_listener(self, listener: Callable[[], Coroutine]):
        """Безопасное добавление слушателей с проверкой типа."""
        if listener is None:
            _LOGGER.error("Попытка добавить None в качестве слушателя!")
            return
            
        if not asyncio.iscoroutinefunction(listener):
            raise TypeError("Слушатель должен быть корутиной!")
            
        self.common_listeners.append(listener)


    def update_zone_data(self, zone: str, data: dict):
        """Обновление данных конкретной зоны."""
        self.data[zone].update(data)
        self._notify_listeners()

    def async_add_listener(self, listener):
        self._listeners.append(listener)

    def async_remove_listener(self, listener):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify_listeners(self):
        for listener in self._listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    self.hass.async_create_background_task(listener())
                else:
                    self.hass.add_job(listener)
            except Exception as e:
                _LOGGER.error("Error in listener: %s", str(e))

    def set_sensor_platform_handler(self, handler: Callable[[set[str]], None]):
        self._sensor_platform_handler = handler

    def set_valve_platform_handler(self, handler: Callable[[set[str]], None]):
        self._valve_handler = handler


    async def async_discover_zones(self, now=None):
        """Обнаружение и обновление зон термостатов."""
        try:
            new_zones = await self._check_available_zones()
            _LOGGER.debug("new_zones: %s (тип: %s)", new_zones, type(new_zones))

            if self.common_request_counter % 2 == 0:
                await self._update_common_data()
            
            self.common_request_counter += 1

            # Обработка зон и уведомление слушателей
#           await self._update_entities(new_zones)  # Исправлено: вызов существующего метода  // Удаление дубля
            self._notify_listeners()

            if not isinstance(new_zones, set):
                _LOGGER.error("Ожидался set, получен: %s. Принудительное преобразование.", type(new_zones))
                new_zones = set(new_zones)

            # Обновление статуса доступности
            self._available = True


            # Инициализация готовности
            if not self._ready_event.is_set():
                self._ready_event.set()
                self.hass.bus.async_fire("iohouse_climate_ready")

            # Обновление сущностей
            await self._update_entities(new_zones)

            if self._valve_handler:
                self._valve_handler(new_zones)  # <-- Клапаны создаются после климата

            # Уведомление слушателей
            self._notify_listeners()
            self.hass.bus.async_fire("iohouse_climate_update")

        except Exception as e:
            _LOGGER.error("Ошибка: %s\nТрассировка: %s", str(e), traceback.format_exc(), exc_info=True)
            self._available = False
            self._notify_listeners()
            self.hass.bus.async_fire("iohouse_climate_update")

    async def _check_available_zones(self) -> set[str]:
        host = self.entry.data[CONF_HOST]
        port = self.entry.data.get(CONF_PORT, DEFAULT_PORT)
        api_key = self.entry.data.get(CONF_API_KEY, "")
        discovered_zones = set()
        global try_counter
        new_data = {}
        # Формируем параметры для всех зон
        zone_params = "&".join([f"zone_{zone}=1" for zone in DEFAULT_ZONES])
        url = BASE_URL.format(
            host,
            port,
            f"/api_climate?{zone_params}"
        )
        self.common_request_counter += 1
        if api_key:
            url += f"&apikey_rest={api_key}"
        try:
            async with async_timeout.timeout(10):
                response = await self.session.get(url)
                if response.status == 200:
                    try_counter=0
                    raw_data = await response.json()
                    _LOGGER.debug("Combined response data: %s", raw_data)

                    # Обрабатываем данные для всех зон
                    for zone in DEFAULT_ZONES:
                        zone_data = {}
                        try:
                            # Извлекаем данные для текущей зоны
                            zone_prefix = f"{zone}_"
                            zone_items = {k: v for k, v in raw_data.items() if k.startswith(zone_prefix)}
                            



                            if zone_items:
                                discovered_zones.add(zone)
                                zone_data = zone_items
                            else:
                                _LOGGER.debug("No data found for zone %s", zone)
                            
                            zone_items.update({
                                k: v for k, v in raw_data.items()
                                if k.startswith(f"{zone}_valve_")
                            })

                        except KeyError:
                            _LOGGER.debug("Zone %s data not found in response", zone)
                        
                        new_data[zone] = zone_data

        except Exception as e:
            _LOGGER.info("Ошибка запроса данных: %s", str(e))
            try_counter+=1
            if try_counter > 5: 
                self._available = False
                _LOGGER.error("Данные не обнаружены после 5 попыток, отключаем объект: %s", str(e))
                return discovered_zones

        self.data = new_data
        return discovered_zones

    async def _update_common_data(self):
        """Отдельный запрос для common=read."""
        host = self.entry.data[CONF_HOST]
        port = self.entry.data.get(CONF_PORT, DEFAULT_PORT)
        api_key = self.entry.data.get(CONF_API_KEY, "")
        
        url = BASE_URL.format(
            host,
            port,
            f"/api_climate?common=read"
        )
        if api_key:
            url += f"&apikey_rest={api_key}"

        try:
            async with async_timeout.timeout(10):
                response = await self.session.get(url)
                if response.status == 200:
                    raw_data = await response.json()
                    if not isinstance(raw_data, dict):  # Добавлена проверка типа
                        _LOGGER.error("Invalid common data format")
                        return
                        
                    self.common_data.update({
                        "summermode": raw_data.get("summermode", 0),
                        "avalible_update": raw_data.get("avalible_update", 0),
                        "fWversion": raw_data.get("fWversion", ""),
                        "u_version": raw_data.get("u_version", ""),
                        **{f"out{i}": raw_data.get(f"out{i}", 0) for i in range(1, 9)}
                    })
                    
                    # Уведомляем слушателей через асинхронный вызов
            for listener in self.common_listeners:
                if listener is not None:  # Добавлена проверка
                    await listener()  # Теперь безопасно
                else:
                    _LOGGER.warning("Обнаружен None в списке слушателей!")
        except Exception as e:
            _LOGGER.error("Ошибка: %s", str(e), exc_info=True)
                        
        except Exception as e:
            _LOGGER.error("Ошибка common-запроса: %s", str(e), exc_info=True)

    @property
    def available(self) -> bool:
        return self._available

    async def _update_entities(self, new_zones: set[str]):
        added_zones = new_zones - self.active_zones
        removed_zones = self.active_zones - new_zones

        # Фильтрация зон, для которых сущности уже существуют
        if added_zones:
            new_entities = [IOhouseClimateEntity(self, zone) for zone in added_zones]
            self.async_add_entities(new_entities)
            for entity in new_entities:
                self.entities[entity._zone] = entity
            _LOGGER.debug("Добавлены новые сущности: %s", added_zones)

        if self._valve_handler:
            self._valve_handler(new_zones)


        # Удаление сущностей для неактивных зон
        for zone in removed_zones:
            entity = self.entities.pop(zone, None)
            if entity:
                if entity.hass is not None:  # Проверяем, что сущность зарегистрирована
                    await entity.async_remove(force_remove=True)
                    _LOGGER.info("Сущность удалена: %s", zone)
                else:
                    _LOGGER.warning("Попытка удалить незарегистрированную сущность: %s", zone)

        self.active_zones = new_zones

class IOhouseClimateEntity(ClimateEntity):
    _attr_icon = "mdi:thermostat-box-auto"    
    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.1
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_hvac_modes = SUPPORT_MODES
    _attr_preset_modes = SUPPORT_PRESETS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP

    def __init__(self, coordinator: IOhouseClimateCoordinator, zone: str):
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self._zone = zone
        self._device_name = coordinator.entry.data[CONF_NAME]
        self._host = coordinator.entry.data[CONF_HOST]
        self._port = coordinator.entry.data.get(CONF_PORT, DEFAULT_PORT)
#        self._attr_unique_id = f"{DOMAIN}-{self.coordinator.entry.entry_id}-{zone}".lower()
#        self.entity_id = f"climate.{self._attr_unique_id}"
        zone_name = self.coordinator.data.get(self._zone, {}).get(
            f"{self._zone}_name", 
            f"zone_{self._zone}"
        ).replace(" ", "_").lower()
        
        self._attr_unique_id = f"{self._device_name}_{zone_name}".lower()
        self.entity_id = f"climate.{self._zone}_{self._attr_unique_id}"
        self._update_internal_state()

    def _update_internal_state(self):
        data = self.coordinator.data.get(self._zone, {})
        if not isinstance(data, dict):
            data = {}
        self._zone_name = data.get(
            f"{self._zone}_name", 
            f"Zone {self._zone.upper()}"
        ).strip().replace(" ", "_")

        self._zone_name = data.get(f"{self._zone}_name", f"Zone {self._zone.upper()}")        
        self._power_state = bool(data.get(f"{self._zone}_power_state", 0))
        self._burner = bool(data.get(f"{self._zone}_burner", 0))  
        self._nightmode = bool(data.get(f"{self._zone}_nightmode", 0))  
        self._pwm = float(data.get(f"{self._zone}_pwm", 0))
        self._target_temp = float(data.get(f"{self._zone}_target_temp", 0))
        self._current_temp = float(data.get(f"{self._zone}_temperature", 0))
        self.away_mode = bool(data.get(f"{self._zone}_away_mode", 0))
        self.eco_mode = bool(data.get(f"{self._zone}_eco_mode", 0))
        self._attr_hvac_mode = HVACMode.OFF if self._power_state == 0 else HVACMode.HEAT
        self._attr_available = True

    @property
    def name(self):
        return self._zone_name

    async def async_update(self):
        await self.coordinator.async_discover_zones()
        self._update_internal_state()

    @property
    def current_temperature(self) -> float | None:
        return self._current_temp

    @property
    def target_temperature(self) -> float | None:
        return self._target_temp

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.entry.entry_id}_{self._zone}")},
            "name": f"{self._zone.upper()}_{self._zone_name}", # вот тут имя модификатор
            "manufacturer": "ioHouse",
            "model": "Thermozone Controller"
        }

    async def async_set_temperature(self, **kwargs) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self._send_command(f"{self._zone}_target_temp={temperature}", temperature)

    async def _send_command(self, command: str, context: Any):
        url = BASE_URL.format(
            self._host,
            self._port,
            f"/apiaction?{command}"
        )
        if api_key := self.coordinator.entry.data.get(CONF_API_KEY):
            url += f"&apikey_rest={api_key}"

        try:
            async with async_timeout.timeout(10):
                response = await self.coordinator.session.get(url)
                if response.status == 200:
                    response_data = await response.json()
                    _LOGGER.debug("API Response: %s", response_data)
                    
                    # Обновляем только полученные параметры
                    if response_data.get("status") == "ok":
                        updated_params = {
                            k: v for k, v in response_data.items() 
                            if k.startswith(f"{self._zone}_") and v is not None
                        }
                        
                        # Синхронизируем состояние с API ответом
                        self.coordinator.data[self._zone].update(updated_params)
                        self._update_internal_state()
                        self.async_write_ha_state()
                        
                    elif "invalid_key" in response_data:
                        _LOGGER.error("Authentication failed")
                        
                else:
                    _LOGGER.error("HTTP Error: %s", response.status)
                    
        except Exception as e:
            _LOGGER.error("Command failed: %s", str(e))

    @property
    def hvac_action(self) -> HVACAction | None:
        if self._power_state == 0:
            return HVACAction.OFF
        return HVACAction.HEATING if self._burner > 0 else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        if self._nightmode:
            return "sleep"
        if self.away_mode:
            return "away"
        if self.eco_mode == 0 and self.away_mode == 0:
            return "comfort"
        if self.eco_mode == 0 and self.away_mode == 1:
            return "away"
        if self.eco_mode == 1 and self.away_mode == 1:
            return "away"
        if self._nightmode == 0 and self.away_mode == 0 and self.eco_mode == 0:
            return "comfort"
        if self._nightmode == 0 and self.away_mode == 0 and self.eco_mode == 1:
            return "home"
        return "home"

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Установка пресета с раздельной отправкой команд для пресетов."""
        command = None
        
        if preset_mode == "away":
            command = f"{self._zone}_away_mode=1&{self._zone}_nightmode=0"
        elif preset_mode == "eco":
            command = f"{self._zone}_eco_mode=1"
        elif preset_mode == "comfort":
            command = f"{self._zone}_away_mode=0&{self._zone}_eco_mode=0&{self._zone}_nightmode=0"
        elif preset_mode == "home":
            command = f"{self._zone}_away_mode=0"
        elif preset_mode == "sleep":
            command = f"{self._zone}_nightmode=1"
        else:
            _LOGGER.error("Unknown preset mode: %s", preset_mode)
            return

        await self._send_command(command, preset_mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        power_state = 1 if hvac_mode != HVACMode.OFF else 0
        await self._send_command(f"{self._zone}_power={power_state}", hvac_mode)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "zone": self._zone,
            "modulation_level": self._pwm,
            "power_state": self._power_state,
            "host": self._host,
            "port": self._port
        }

    @property
    def available(self) -> bool:
        return (
            self.coordinator.available 
            and self._zone in self.coordinator.active_zones 
            and bool(self.coordinator.data.get(self._zone)))