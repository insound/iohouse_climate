"""Конфигурационный поток для iOhouse Climate с настройкой шага температуры."""
from __future__ import annotations
import logging
import voluptuous as vol
import aiohttp
import async_timeout
from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_API_KEY,
    CONF_ZONES,
    CONF_ZONE_MIN_TEMP,
    CONF_ZONE_MAX_TEMP,
    CONF_ZONE_TEMP_STEP,  # НОВОЕ
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_ZONES,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    DEFAULT_ZONE_TEMP_STEP,  # НОВОЕ
    API_CLIMATE_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)

class IOhouseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Конфигурационный поток для iOhouse Climate."""
    
    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Инициализация."""
        self.discovered_zones: list[str] = []
        self.zone_names: dict[str, str] = {}
        self.host: str = ""
        self.port: int = DEFAULT_PORT
        self.name: str = DEFAULT_NAME
        self.api_key: str = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Первый шаг - ввод базовых настроек."""
        errors = {}
        
        if user_input is not None:
            try:
                self.host = user_input[CONF_HOST]
                self.port = user_input.get(CONF_PORT, DEFAULT_PORT)
                self.name = user_input[CONF_NAME]
                self.api_key = user_input.get(CONF_API_KEY, "")
                
                # Обнаружение активных зон
                zones_data = await self._discover_zones()
                if not zones_data:
                    raise ValueError("No active zones found")

                self.discovered_zones = list(zones_data.keys())
                self.zone_names = {zone: data.get("name", f"Zone {zone.upper()}") 
                                 for zone, data in zones_data.items()}

                # Установка уникального ID
                unique_id = f"{DOMAIN}-{self.host}-{self.port}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Переходим к настройке температурных диапазонов и шага
                return await self.async_step_zone_config()

            except Exception as err:
                _LOGGER.error("Ошибка конфигурации: %s", err)
                errors["base"] = "discovery_failed"

        data_schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
            vol.Optional(CONF_API_KEY): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "zones": ", ".join(DEFAULT_ZONES)
            }
        )

    async def async_step_zone_config(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Второй шаг - настройка температурных диапазонов и шага для зон."""
        if user_input is not None:
            # Сохраняем конфигурацию
            zone_min_temps = {}
            zone_max_temps = {}
            zone_temp_steps = {}  # НОВОЕ
            
            for zone in self.discovered_zones:
                zone_min_temps[zone] = user_input.get(f"{zone}_min_temp", DEFAULT_MIN_TEMP)
                zone_max_temps[zone] = user_input.get(f"{zone}_max_temp", DEFAULT_MAX_TEMP)
                zone_temp_steps[zone] = user_input.get(f"{zone}_temp_step", DEFAULT_ZONE_TEMP_STEP)  # НОВОЕ

            data = {
                CONF_HOST: self.host,
                CONF_PORT: self.port,
                CONF_NAME: self.name,
                CONF_ZONES: self.discovered_zones,
                CONF_ZONE_MIN_TEMP: zone_min_temps,
                CONF_ZONE_MAX_TEMP: zone_max_temps,
                CONF_ZONE_TEMP_STEP: zone_temp_steps,  # НОВОЕ
            }
            
            if self.api_key:
                data[CONF_API_KEY] = self.api_key

            return self.async_create_entry(
                title=self.name,
                data=data
            )

        # Создаем схему для настройки температур и шага каждой зоны
        schema_dict = {}
        for zone in self.discovered_zones:
            zone_name = self.zone_names.get(zone, f"Zone {zone.upper()}")
            
            # Минимальная температура
            schema_dict[vol.Optional(f"{zone}_min_temp", default=DEFAULT_MIN_TEMP)] = vol.All(
                vol.Coerce(float), vol.Range(min=0, max=200)
            )
            
            # Максимальная температура
            schema_dict[vol.Optional(f"{zone}_max_temp", default=DEFAULT_MAX_TEMP)] = vol.All(
                vol.Coerce(float), vol.Range(min=0, max=200)
            )
            
            # НОВОЕ: Шаг температуры
            schema_dict[vol.Optional(f"{zone}_temp_step", default=DEFAULT_ZONE_TEMP_STEP)] = vol.All(
                vol.Coerce(float), vol.Range(min=0.01, max=1.0)
            )

        return self.async_show_form(
            step_id="zone_config",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "zones": ", ".join([f"{zone} ({self.zone_names.get(zone, zone)})" 
                                  for zone in self.discovered_zones])
            }
        )

    async def async_step_ssdp(self, discovery_info: dict[str, Any]) -> FlowResult:
        """Обработка SSDP обнаружения."""
        _LOGGER.debug("SSDP обнаружение: %s", discovery_info)
        
        # ИСПРАВЛЕНО: Совместимость с новыми версиями HA
        try:
            # Новый способ (объект)
            manufacturer = getattr(discovery_info, 'upnp_manufacturer', "") or ""
            model = getattr(discovery_info, 'upnp_model_name', "") or ""  # ИСПРАВЛЕНО: model_name вместо model_number
            model_number = getattr(discovery_info, 'upnp_model_number', "") or ""
            friendly_name = getattr(discovery_info, 'upnp_friendly_name', "") or ""
            location = getattr(discovery_info, 'ssdp_location', "") or ""
        except (AttributeError, TypeError):
            # Старый способ (словарь)
            from homeassistant.components import ssdp
            manufacturer = discovery_info.get(ssdp.ATTR_UPNP_MANUFACTURER, "")
            model = discovery_info.get(ssdp.ATTR_UPNP_MODEL_NAME, "")  # ИСПРАВЛЕНО
            model_number = discovery_info.get(ssdp.ATTR_UPNP_MODEL_NUMBER, "")
            friendly_name = discovery_info.get(ssdp.ATTR_UPNP_FRIENDLY_NAME, "")
            location = discovery_info.get(ssdp.ATTR_SSDP_LOCATION, "")
        
        # ИСПРАВЛЕНО: Проверяем точные значения из кода контроллера
        is_iohouse = any([
            "iohouse ltd" in manufacturer.lower(),           # "iohouse LTD"
            "iohouse" in friendly_name.lower(),              # "ioHouse hostname"
            model.lower() == "iohouse",                      # "iohouse"
            model_number == "929000226503",                  # точный номер модели
        ])
        
        if not is_iohouse:
            _LOGGER.debug("Не iOhouse устройство: manufacturer=%s, model=%s, friendly_name=%s", 
                        manufacturer, model, friendly_name)
            return self.async_abort(reason="not_iohouse_device")
        
        # Извлекаем IP из location URL
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(location)
            host_ip = parsed_url.hostname
            port = parsed_url.port or DEFAULT_PORT
        except Exception as err:
            _LOGGER.error("Ошибка парсинга location URL %s: %s", location, err)
            return self.async_abort(reason="invalid_discovery_info")
        
        if not host_ip:
            _LOGGER.error("Не удалось извлечь IP из location: %s", location)
            return self.async_abort(reason="invalid_discovery_info")
        
        # Устанавливаем уникальный ID
        unique_id = f"{DOMAIN}-{host_ip}-{port}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        
        # Сохраняем данные для последующих шагов
        self.context["title_placeholders"] = {
            "name": friendly_name or f"iOhouse {host_ip}",
            "host": host_ip,
            "port": port,
            "manufacturer": manufacturer,
            "model": model,
        }
        
        self.host = host_ip
        self.port = port
        self.name = friendly_name or f"iOhouse {host_ip}"
        
        _LOGGER.info("Обнаружено iOhouse устройство: %s на %s:%s (manufacturer: %s, model: %s)", 
                    friendly_name or "Unknown", host_ip, port, manufacturer, model)
        
        # Возвращаем форму подтверждения вместо автоматического добавления
        return await self.async_step_discovery_confirm()

    async def async_step_dhcp(self, discovery_info: dict[str, Any]) -> FlowResult:
        """Обработка DHCP обнаружения."""
        _LOGGER.debug("DHCP обнаружение: %s", discovery_info)
        
        # ИСПРАВЛЕНО: Совместимость с новыми версиями HA
        try:
            # Новый способ (объект)
            hostname = getattr(discovery_info, 'hostname', "") or ""
            ip_address = getattr(discovery_info, 'ip', "") or ""
            macaddress = getattr(discovery_info, 'macaddress', "") or ""
        except (AttributeError, TypeError):
            # Старый способ (словарь)
            from homeassistant.components import dhcp
            hostname = discovery_info.get(dhcp.HOSTNAME, "")
            ip_address = discovery_info.get(dhcp.IP_ADDRESS, "")
            macaddress = discovery_info.get(dhcp.MAC_ADDRESS, "")
        
        # Проверяем что это устройство iOhouse по hostname
        if not any(pattern in hostname.lower() for pattern in ["iOhouse", "iOhouse"]):
            return self.async_abort(reason="not_iohouse_device")
        
        if not ip_address:
            return self.async_abort(reason="invalid_discovery_info")
        
        # Устанавливаем уникальный ID по MAC адресу если есть, иначе по IP
        unique_id = f"{DOMAIN}-{macaddress or ip_address}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        
        # Сохраняем данные для отображения в уведомлении
        self.context["title_placeholders"] = {
            "name": hostname or f"iOhouse {ip_address}",
            "host": ip_address,
            "port": DEFAULT_PORT,
        }
        
        self.host = ip_address
        self.port = DEFAULT_PORT
        self.name = hostname or f"iOhouse {ip_address}"
        
        return await self.async_step_discovery_confirm()



    async def async_step_zeroconf(self, discovery_info: dict[str, Any]) -> FlowResult:
        """Обработка Zeroconf обнаружения."""
        _LOGGER.debug("Zeroconf обнаружение: %s", discovery_info)
        
        # ИСПРАВЛЕНО: В новых версиях HA discovery_info это объект ZeroconfServiceInfo
        try:
            # Новый способ - обращение к атрибутам объекта
            host = discovery_info.host
            port = discovery_info.port or DEFAULT_PORT
            hostname = discovery_info.hostname or ""
            name = discovery_info.name or ""
        except AttributeError:
            # Fallback для старых версий HA - как словарь
            from homeassistant.components import zeroconf
            host = discovery_info.get(zeroconf.ATTR_HOST)
            port = discovery_info.get(zeroconf.ATTR_PORT, DEFAULT_PORT)
            hostname = discovery_info.get(zeroconf.ATTR_HOSTNAME, "")
            name = discovery_info.get(zeroconf.ATTR_NAME, "")
        
        # Проверяем что это устройство iOhouse
        if not any("iOhouse" in text.lower() for text in [hostname, name] if text):
            return self.async_abort(reason="not_iohouse_device")
        
        if not host:
            return self.async_abort(reason="invalid_discovery_info")
        
        # Устанавливаем уникальный ID
        unique_id = f"{DOMAIN}-{host}-{port}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        
        # Сохраняем данные для отображения
        self.context["title_placeholders"] = {
            "name": hostname or name or f"iOhouse {host}",
            "host": host,
            "port": port,
        }
        
        self.host = host
        self.port = port
        self.name = hostname or name or f"iOhouse {host}"
        
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Подтверждение обнаруженного устройства."""
        errors = {}
        
        if user_input is not None:
            if user_input.get("add_device"):
                # Пользователь согласился добавить устройство
                try:
                    # Проверяем доступность устройства и обнаруживаем зоны
                    zones_data = await self._discover_zones()
                    if not zones_data:
                        raise ValueError("No active zones found")

                    self.discovered_zones = list(zones_data.keys())
                    self.zone_names = {zone: data.get("name", f"Zone {zone.upper()}") 
                                     for zone, data in zones_data.items()}

                    # Переходим к полной настройке (имя устройства + API ключ)
                    return await self.async_step_discovery_setup()

                except Exception as err:
                    _LOGGER.error("Ошибка при подтверждении обнаружения: %s", err)
                    errors["base"] = "discovery_failed"
            else:
                # Пользователь отказался добавлять устройство
                return self.async_abort(reason="user_rejected")

        # Показываем форму подтверждения с информацией об устройстве
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema({
                vol.Required("add_device", default=False): bool,
            }),
            description_placeholders={
                "name": self.name,
                "host": self.host,
                "port": self.port,
            },
            errors=errors,
        )

    async def async_step_discovery_setup(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Настройка обнаруженного устройства."""
        errors = {}
        
        if user_input is not None:
            # Обновляем данные из формы
            self.name = user_input.get("name", self.name)
            self.api_key = user_input.get("api_key", "")
            
            # Переходим к настройке температурных диапазонов и шага
            return await self.async_step_zone_config()
        
        # Форма для настройки имени и API ключа
        return self.async_show_form(
            step_id="discovery_setup",
            data_schema=vol.Schema({
                vol.Required("name", default=self.name): str,
                vol.Optional("api_key", default=""): str,
            }),
            description_placeholders={
                "host": self.host,
                "port": self.port,
                "zones": ", ".join([f"{zone} ({self.zone_names.get(zone, zone)})" 
                                  for zone in self.discovered_zones]),
            },
            errors=errors,
        )

    async def _discover_zones(self) -> dict[str, dict[str, Any]]:
        """Обнаружение активных зон на контроллере."""
        session = aiohttp.ClientSession()
        discovered_zones = {}
        
        _LOGGER.debug("Подключение к контроллеру: %s:%s", self.host, self.port)
        
        try:
            # Запрос всех возможных зон
            zone_params = "&".join([f"zone_{zone}=1" for zone in DEFAULT_ZONES])
            url = f"http://{self.host}:{self.port}{API_CLIMATE_ENDPOINT}?{zone_params}&common=read"
            
            if self.api_key:
                url += f"&apikey_rest={self.api_key}"

            _LOGGER.debug("URL запроса: %s", url)

            async with async_timeout.timeout(10):
                response = await session.get(url)
                if response.status == 200:
                    raw_data = await response.json()
                    
                    # Анализируем данные для каждой зоны
                    for zone in DEFAULT_ZONES:
                        zone_data = {}
                        for key, value in raw_data.items():
                            if key.startswith(f"{zone}_"):
                                param_name = key[3:]  # Убираем префикс зоны
                                zone_data[param_name] = value
                        
                        # Если есть данные для зоны, считаем её активной
                        if zone_data:
                            discovered_zones[zone] = zone_data
                            _LOGGER.debug("Обнаружена активная зона %s: %s", zone, zone_data)

        except Exception as e:
            _LOGGER.error("Ошибка обнаружения зон на %s:%s - %s", self.host, self.port, str(e))
            raise
        finally:
            await session.close()
        
        return discovered_zones

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Создание потока настроек."""
        return IOhouseOptionsFlowHandler(config_entry)


class IOhouseOptionsFlowHandler(config_entries.OptionsFlow):
    """Обработчик потока настроек с добавлением шага температуры."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Инициализация options flow."""
        # НЕ устанавливаем self.config_entry - это устаревший подход
        # config_entry доступен через self.config_entry автоматически в современных версиях HA
        pass

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Управление настройками с поддержкой шага температуры."""
        # Получаем config_entry через атрибут родительского класса
        config_entry = self.config_entry
        
        if user_input is not None:
            # Обработка данных из формы
            current_zones = config_entry.data.get(CONF_ZONES, [])
            
            zone_min_temps = {}
            zone_max_temps = {}
            zone_temp_steps = {}  # НОВОЕ
            
            # Обновляем температурные диапазоны и шаг
            for zone in current_zones:
                min_key = f"{zone}_min_temp"
                max_key = f"{zone}_max_temp"
                step_key = f"{zone}_temp_step"  # НОВОЕ
                
                zone_min_temps[zone] = user_input.get(min_key, DEFAULT_MIN_TEMP)
                zone_max_temps[zone] = user_input.get(max_key, DEFAULT_MAX_TEMP)
                zone_temp_steps[zone] = user_input.get(step_key, DEFAULT_ZONE_TEMP_STEP)  # НОВОЕ
            
            # Обновляем конфигурацию
            new_data = dict(config_entry.data)
            new_data[CONF_ZONE_MIN_TEMP] = zone_min_temps
            new_data[CONF_ZONE_MAX_TEMP] = zone_max_temps
            new_data[CONF_ZONE_TEMP_STEP] = zone_temp_steps  # НОВОЕ
            
            self.hass.config_entries.async_update_entry(
                config_entry, data=new_data
            )
            
            return self.async_create_entry(title="", data={})

        # Текущие настройки
        current_zones = config_entry.data.get(CONF_ZONES, [])
        current_min_temps = config_entry.data.get(CONF_ZONE_MIN_TEMP, {})
        current_max_temps = config_entry.data.get(CONF_ZONE_MAX_TEMP, {})
        current_temp_steps = config_entry.data.get(CONF_ZONE_TEMP_STEP, {})  # НОВОЕ

        # Создаем схему для настройки температур и шага
        schema_dict = {}
        for zone in current_zones:
            current_min = current_min_temps.get(zone, DEFAULT_MIN_TEMP)
            current_max = current_max_temps.get(zone, DEFAULT_MAX_TEMP)
            current_step = current_temp_steps.get(zone, DEFAULT_ZONE_TEMP_STEP)  # НОВОЕ
            
            zone_display = zone.upper()
            
            min_key = f"{zone}_min_temp"
            max_key = f"{zone}_max_temp"
            step_key = f"{zone}_temp_step"  # НОВОЕ
            
            schema_dict[vol.Optional(min_key, default=current_min)] = vol.All(
                vol.Coerce(float), vol.Range(min=0, max=200)
            )
            schema_dict[vol.Optional(max_key, default=current_max)] = vol.All(
                vol.Coerce(float), vol.Range(min=0, max=200)
            )
            # НОВОЕ: Добавляем поле для шага температуры
            schema_dict[vol.Optional(step_key, default=current_step)] = vol.All(
                vol.Coerce(float), vol.Range(min=0.01, max=1.0)
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "zones": ", ".join([zone.upper() for zone in current_zones])
            }
        )