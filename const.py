from homeassistant.components.climate import HVACMode

# Основные константы
DOMAIN = "iohouse_climate"
DEFAULT_NAME = "iOhouse Thermozone"
DEFAULT_PORT = 80
DEFAULT_ZONES = ["a1", "a2", "b1", "b2"]
UNIQUE_ID_FORMAT = "{host}:{port}:{zone}"

# Конфигурационные ключи
CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"
CONF_API_KEY = "api_key"
CONF_ZONES = "zones"  # Добавляем недостающую константу

# Параметры температуры
MIN_TEMP = 1.0
MAX_TEMP = 100.0


# Режимы работы
SUPPORT_MODES = [HVACMode.HEAT, HVACMode.OFF]
SUPPORT_PRESETS = ["comfort", "away", "eco"]

# Сообщения об ошибках
ERROR_MESSAGES = {
    "auth_required": "This action requires API key authentication",
    "invalid_key": "Invalid API key provided"
}