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
SCAN_INTERVAL = timedelta(seconds=30)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация платформы через конфигурационную запись."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    session = entry_data["session"]
    
    coordinator = IOhouseClimateCoordinator(
        hass=hass,
        session=session,
        entry=entry,
        async_add_entities=async_add_entities
    )
    entry_data["coordinator"] = coordinator
    
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

    async def async_discover_zones(self, now=None):
        """Обнаружение и обновление зон термостатов."""
        try:
            new_zones = await self._check_available_zones()
            _LOGGER.debug("new_zones: %s (тип: %s)", new_zones, type(new_zones))
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
        new_data = {}

        for zone in DEFAULT_ZONES:
            try:
                url = BASE_URL.format(
                    host,
                    port,
                    f"/api_climate?zone_{zone}=1"
                )
                if api_key:
                    url += f"&apikey_rest={api_key}"

                async with async_timeout.timeout(10):
                    response = await self.session.get(url)
                    if response.status == 200:
                        raw_data = await response.json()
                        _LOGGER.debug("Raw data (type: %s) for zone %s: %s", type(raw_data), zone, raw_data)

                        data = {}
                        # Обработка разных форматов данных
                        if isinstance(raw_data, list):
                            try:
                                # Если данные в формате [{"key": "a1_temp", "value": 25}, ...]
                                data = {item["key"]: item["value"] for item in raw_data}
                            except KeyError:
                                # Если данные в формате [["a1_temp", 25], ...]
                                data = dict(raw_data)
                            except TypeError:
                                _LOGGER.error("Неподдерживаемый формат списка для зоны %s", zone)
                        elif isinstance(raw_data, dict):
                            data = raw_data
                        else:
                            _LOGGER.warning("Некорректный формат данных для зоны %s", zone)

                        # Проверка наличия ключей зоны
                        if any(key.startswith(f"{zone}_") for key in data):
                            discovered_zones.add(zone)
                            new_data[zone] = data
                        else:
                            new_data[zone] = {}
                    else:
                        new_data[zone] = {}

            except Exception as e:
                _LOGGER.error("Ошибка проверки зоны %s: %s", zone, str(e))
                new_data[zone] = {}
                self._available = False
                continue

        self.data = new_data
        return discovered_zones

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
            "name": f"{self._zone.upper()} ", # вот тут имя модификатор
            "manufacturer": "ioHouse",
            "model": "Thermozone Controller"
        }

    async def async_set_temperature(self, **kwargs) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self._send_command(f"{self._zone}_target_temp={temperature}", temperature)

    async def _send_command(self, command: str, value: Any):
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
                    await self.async_update()
        except Exception as e:
            _LOGGER.error("Ошибка отправки команды: %s", str(e))

    @property
    def hvac_action(self) -> HVACAction | None:
        if self._power_state == 0:
            return HVACAction.OFF
        return HVACAction.HEATING if self._burner > 0 else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        if self.eco_mode:
            return "eco"
        if self.away_mode:
            return "away"
        return "comfort"

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        params = {
            "away_mode": 1 if preset_mode == "away" else 0,
            "eco_mode": 1 if preset_mode == "eco" else 0
        }
        await self._send_command(
            f"{self._zone}_away_mode={params['away_mode']}&{self._zone}_eco_mode={params['eco_mode']}",
            preset_mode
        )

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