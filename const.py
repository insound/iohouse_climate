"""Константы для интеграции iOhouse Climate."""
from datetime import timedelta
from homeassistant.components.climate import HVACMode

# Основные константы
DOMAIN = "iohouse_climate"
DEFAULT_NAME = "iOhouse Thermozone"
DEFAULT_PORT = 80
DEFAULT_ZONES = ["a1", "a2", "b1", "b2"]

# Конфигурационные ключи
CONF_HOST = "host"
CONF_PORT = "port" 
CONF_NAME = "name"
CONF_API_KEY = "api_key"
CONF_ZONES = "zones"
CONF_ZONE_MIN_TEMP = "zone_min_temp"
CONF_ZONE_MAX_TEMP = "zone_max_temp"
CONF_ZONE_TEMP_STEP = "zone_temp_step"  # НОВОЕ: шаг температуры для зон

# URL endpoints
API_CLIMATE_ENDPOINT = "/api_climate"
API_ACTION_ENDPOINT = "/apiaction"
API_UPDATE_ENDPOINT = "/intapi"

# Параметры температуры по умолчанию
DEFAULT_MIN_TEMP = 1.0
DEFAULT_MAX_TEMP = 100.0
TEMPERATURE_STEP = 0.05  # Детализация 0.05 градуса (глобальная по умолчанию)
DEFAULT_ZONE_TEMP_STEP = 0.05  # НОВОЕ: шаг температуры по умолчанию для зон

# Режимы работы
SUPPORT_MODES = [HVACMode.HEAT, HVACMode.OFF]
SUPPORT_PRESETS = ["comfort", "away", "eco", "home", "sleep"]

# Интервалы обновления
DISCOVERY_INTERVAL = timedelta(minutes=5)  # Поиск зон
REGULAR_UPDATE_INTERVAL = timedelta(seconds=20)  # Обычные обновления
FAST_UPDATE_INTERVAL = timedelta(seconds=5)  # После команд
ERROR_RETRY_DELAY = timedelta(seconds=60)  # Задержка при ошибках

# Сообщения об ошибках
ERROR_MESSAGES = {
    "auth_required": "This action requires API key authentication",
    "invalid_key": "Invalid API key provided",
    "no_zones_found": "No active zones found on controller",
    "connection_failed": "Failed to connect to controller",
    "discovery_failed": "Failed to discover zones"
}

# Настройки по умолчанию для зон
DEFAULT_ZONE_SETTINGS = {
    "min_temp": DEFAULT_MIN_TEMP,
    "max_temp": DEFAULT_MAX_TEMP,
    "temp_step": DEFAULT_ZONE_TEMP_STEP  # НОВОЕ
}