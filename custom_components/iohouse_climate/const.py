"""Constants for the ioHouse Climate integration."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.climate import HVACMode


DOMAIN = "iohouse_climate"

DEFAULT_NAME = "iOhouse Thermozone"
DEFAULT_PORT = 80

CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"
CONF_API_KEY = "api_key"
CONF_ZONES = "zones"
CONF_ZONE_MIN_TEMP = "zone_min_temp"
CONF_ZONE_MAX_TEMP = "zone_max_temp"
CONF_ZONE_TEMP_STEP = "zone_temp_step"

API_CLIMATE_ENDPOINT = "/api_climate"
API_ACTION_ENDPOINT = "/apiaction"

EVENT_UNITS_CHANGED = f"{DOMAIN}_units_changed"

DEFAULT_MIN_TEMP = 1.0
DEFAULT_MAX_TEMP = 100.0
DEFAULT_ZONE_TEMP_STEP = 0.1

SUPPORT_MODES = [HVACMode.HEAT, HVACMode.OFF]
SUPPORT_PRESETS = ["comfort", "away", "eco", "home", "sleep"]

REGULAR_UPDATE_INTERVAL = timedelta(seconds=20)
FULL_REFRESH_INTERVAL = timedelta(minutes=5)

ERROR_MESSAGES = {
    "auth_required": "This action requires API key authentication",
    "invalid_key": "Invalid API key provided",
    "no_units_found": "No active units found on controller",
    "connection_failed": "Failed to connect to controller",
    "discovery_failed": "Failed to discover units",
}
