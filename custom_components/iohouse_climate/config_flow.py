"""Config flow for ioHouse Climate api v2."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import async_timeout
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow, FlowResult

from .api_v2 import build_api_url, parse_climate_payload
from .const import (
    API_CLIMATE_ENDPOINT,
    CONF_API_KEY,
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_ZONE_MAX_TEMP,
    CONF_ZONE_MIN_TEMP,
    CONF_ZONE_TEMP_STEP,
    CONF_ZONES,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_ZONE_TEMP_STEP,
    DOMAIN,
)
from .entity_helpers import get_unit_label

_LOGGER = logging.getLogger(__name__)

FIELD_MIN_TEMP = "min_temp"
FIELD_MAX_TEMP = "max_temp"
FIELD_TEMP_STEP = "temp_step"


def _normalize_temp_step(value: Any) -> float:
    """Clamp UI-configurable temperature step to controller-visible values."""
    return max(0.1, float(value))


class IOhouseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for ioHouse Climate."""

    VERSION = 3
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        self.host = ""
        self.port = DEFAULT_PORT
        self.name = DEFAULT_NAME
        self.api_key = ""
        self.discovered_units: dict[str, dict[str, Any]] = {}
        self._unit_order: list[str] = []
        self._zone_min_temp: dict[str, float] = {}
        self._zone_max_temp: dict[str, float] = {}
        self._zone_temp_step: dict[str, float] = {}
        self._unit_index = 0

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle manual setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.host = user_input[CONF_HOST].strip()
            self.port = user_input.get(CONF_PORT, DEFAULT_PORT)
            self.name = user_input[CONF_NAME].strip()
            self.api_key = user_input.get(CONF_API_KEY, "").strip()

            try:
                self.discovered_units = await self._discover_units()
                self._prepare_unit_settings()
                await self.async_set_unique_id(f"{DOMAIN}-{self.host}-{self.port}")
                self._abort_if_unique_id_configured()
                return await self.async_step_zone_config()
            except AbortFlow as err:
                return self.async_abort(reason=getattr(err, "reason", "already_in_progress"))
            except Exception as err:
                _LOGGER.error("ioHouse discovery failed for %s:%s: %s", self.host, self.port, err)
                errors["base"] = "discovery_failed"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Optional(CONF_API_KEY, default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_zone_config(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure temperature limits one unit at a time."""
        if not self._unit_order:
            self._prepare_unit_settings()

        if user_input is not None:
            current_unit_id = self._unit_order[self._unit_index]
            self._zone_min_temp[current_unit_id] = float(user_input.get(FIELD_MIN_TEMP, DEFAULT_MIN_TEMP))
            self._zone_max_temp[current_unit_id] = float(user_input.get(FIELD_MAX_TEMP, DEFAULT_MAX_TEMP))
            self._zone_temp_step[current_unit_id] = _normalize_temp_step(
                user_input.get(FIELD_TEMP_STEP, DEFAULT_ZONE_TEMP_STEP)
            )
            self._unit_index += 1

            if self._unit_index >= len(self._unit_order):
                data = {
                    CONF_HOST: self.host,
                    CONF_PORT: self.port,
                    CONF_NAME: self.name,
                    CONF_ZONES: list(self._unit_order),
                    CONF_ZONE_MIN_TEMP: dict(self._zone_min_temp),
                    CONF_ZONE_MAX_TEMP: dict(self._zone_max_temp),
                    CONF_ZONE_TEMP_STEP: dict(self._zone_temp_step),
                }
                if self.api_key:
                    data[CONF_API_KEY] = self.api_key
                return self.async_create_entry(title=self.name, data=data)

        return self._show_unit_config_form()

    async def async_step_ssdp(self, discovery_info: Any) -> FlowResult:
        """Handle SSDP discovery."""
        try:
            manufacturer = getattr(discovery_info, "upnp_manufacturer", "") or ""
            model = getattr(discovery_info, "upnp_model_name", "") or ""
            model_number = getattr(discovery_info, "upnp_model_number", "") or ""
            friendly_name = getattr(discovery_info, "upnp_friendly_name", "") or ""
            location = getattr(discovery_info, "ssdp_location", "") or ""
        except (AttributeError, TypeError):
            from homeassistant.components import ssdp

            manufacturer = discovery_info.get(ssdp.ATTR_UPNP_MANUFACTURER, "")
            model = discovery_info.get(ssdp.ATTR_UPNP_MODEL_NAME, "")
            model_number = discovery_info.get(ssdp.ATTR_UPNP_MODEL_NUMBER, "")
            friendly_name = discovery_info.get(ssdp.ATTR_UPNP_FRIENDLY_NAME, "")
            location = discovery_info.get(ssdp.ATTR_SSDP_LOCATION, "")

        if not any(
            (
                "iohouse ltd" in manufacturer.lower(),
                model.lower() == "iohouse",
                model_number == "929000226503",
                "iohouse" in friendly_name.lower(),
            )
        ):
            return self.async_abort(reason="not_iohouse_device")

        from urllib.parse import urlparse

        parsed = urlparse(location)
        if not parsed.hostname:
            return self.async_abort(reason="invalid_discovery_info")

        self.host = parsed.hostname
        self.port = parsed.port or DEFAULT_PORT
        self.name = friendly_name or f"iOhouse {self.host}"

        await self.async_set_unique_id(f"{DOMAIN}-{self.host}-{self.port}")
        self._abort_if_unique_id_configured()
        return await self.async_step_discovery_confirm()

    async def async_step_dhcp(self, discovery_info: Any) -> FlowResult:
        """Handle DHCP discovery."""
        try:
            hostname = getattr(discovery_info, "hostname", "") or ""
            ip_address = getattr(discovery_info, "ip", "") or ""
        except (AttributeError, TypeError):
            from homeassistant.components import dhcp

            hostname = discovery_info.get(dhcp.HOSTNAME, "")
            ip_address = discovery_info.get(dhcp.IP_ADDRESS, "")

        if "iohouse" not in hostname.lower():
            return self.async_abort(reason="not_iohouse_device")
        if not ip_address:
            return self.async_abort(reason="invalid_discovery_info")

        self.host = ip_address
        self.port = DEFAULT_PORT
        self.name = hostname or f"iOhouse {ip_address}"

        await self.async_set_unique_id(f"{DOMAIN}-{self.host}-{self.port}")
        self._abort_if_unique_id_configured()
        return await self.async_step_discovery_confirm()

    async def async_step_zeroconf(self, discovery_info: Any) -> FlowResult:
        """Handle Zeroconf discovery."""
        try:
            host = discovery_info.host
            port = discovery_info.port or DEFAULT_PORT
            hostname = discovery_info.hostname or ""
            name = discovery_info.name or ""
        except AttributeError:
            from homeassistant.components import zeroconf

            host = discovery_info.get(zeroconf.ATTR_HOST)
            port = discovery_info.get(zeroconf.ATTR_PORT, DEFAULT_PORT)
            hostname = discovery_info.get(zeroconf.ATTR_HOSTNAME, "")
            name = discovery_info.get(zeroconf.ATTR_NAME, "")

        if not host or not any("iohouse" in value.lower() for value in (hostname, name) if value):
            return self.async_abort(reason="not_iohouse_device")

        self.host = host
        self.port = port
        self.name = hostname or name or f"iOhouse {host}"

        await self.async_set_unique_id(f"{DOMAIN}-{host}-{port}")
        self._abort_if_unique_id_configured()
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Ask the user to confirm discovered controller."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get("add_device"):
                return self.async_abort(reason="user_rejected")
            try:
                self.discovered_units = await self._discover_units()
                self._prepare_unit_settings()
                return await self.async_step_discovery_setup()
            except Exception as err:
                _LOGGER.error("ioHouse discovery confirm failed for %s:%s: %s", self.host, self.port, err)
                errors["base"] = "discovery_failed"

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema({vol.Required("add_device", default=False): bool}),
            description_placeholders={
                "name": self.name,
                "host": self.host,
                "port": str(self.port),
            },
            errors=errors,
        )

    async def async_step_discovery_setup(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Allow the user to override name/API key before unit settings."""
        if user_input is not None:
            self.name = user_input.get(CONF_NAME, self.name).strip()
            self.api_key = user_input.get(CONF_API_KEY, "").strip()
            self.discovered_units = await self._discover_units()
            self._prepare_unit_settings()
            return await self.async_step_zone_config()

        return self.async_show_form(
            step_id="discovery_setup",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=self.name): str,
                    vol.Optional(CONF_API_KEY, default=self.api_key): str,
                }
            ),
            description_placeholders={
                "host": self.host,
                "port": str(self.port),
            },
        )

    def _prepare_unit_settings(self) -> None:
        """Initialize per-unit config state for the wizard."""
        self._unit_order = list(self.discovered_units.keys())
        self._zone_min_temp = {
            unit_id: self._zone_min_temp.get(unit_id, DEFAULT_MIN_TEMP)
            for unit_id in self._unit_order
        }
        self._zone_max_temp = {
            unit_id: self._zone_max_temp.get(unit_id, DEFAULT_MAX_TEMP)
            for unit_id in self._unit_order
        }
        self._zone_temp_step = {
            unit_id: _normalize_temp_step(self._zone_temp_step.get(unit_id, DEFAULT_ZONE_TEMP_STEP))
            for unit_id in self._unit_order
        }
        self._unit_index = min(self._unit_index, max(len(self._unit_order) - 1, 0))

    def _show_unit_config_form(self) -> FlowResult:
        """Render the current per-unit configuration form."""
        current_unit_id = self._unit_order[self._unit_index]
        current_unit = self.discovered_units[current_unit_id]
        current_label = get_unit_label(current_unit_id, current_unit)

        return self.async_show_form(
            step_id="zone_config",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_MIN_TEMP, default=self._zone_min_temp[current_unit_id]): vol.All(
                        vol.Coerce(float),
                        vol.Range(min=0, max=200),
                    ),
                    vol.Required(FIELD_MAX_TEMP, default=self._zone_max_temp[current_unit_id]): vol.All(
                        vol.Coerce(float),
                        vol.Range(min=0, max=200),
                    ),
                    vol.Required(FIELD_TEMP_STEP, default=self._zone_temp_step[current_unit_id]): vol.All(
                        vol.Coerce(float),
                        vol.Range(min=0.1, max=1.0),
                    ),
                }
            ),
            description_placeholders={
                "unit_name": current_label,
                "unit_index": str(self._unit_index + 1),
                "unit_total": str(len(self._unit_order)),
            },
        )

    async def _discover_units(self) -> dict[str, dict[str, Any]]:
        """Call api_climate v2 and return discovered units."""
        params: dict[str, Any] = {"scope": "full"}
        if self.api_key:
            params["apikey_rest"] = self.api_key

        url = build_api_url(self.host, self.port, API_CLIMATE_ENDPOINT, params)

        async with aiohttp.ClientSession() as session:
            async with async_timeout.timeout(10):
                response = await session.get(url)
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}")

                payload = await response.json()
                normalized = parse_climate_payload(payload)
                units = normalized.get("units", {})
                if not units:
                    raise ValueError("No active units found")
                return {
                    unit_id: units[unit_id]
                    for unit_id in normalized.get("unit_order", list(units.keys()))
                    if unit_id in units
                }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Create the options flow."""
        return IOhouseOptionsFlowHandler(config_entry)


class IOhouseOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for per-unit temperature constraints."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._unit_order = list(config_entry.data.get(CONF_ZONES, []))
        self._unit_index = 0
        self._zone_min_temp = dict(config_entry.data.get(CONF_ZONE_MIN_TEMP, {}))
        self._zone_max_temp = dict(config_entry.data.get(CONF_ZONE_MAX_TEMP, {}))
        self._zone_temp_step = dict(config_entry.data.get(CONF_ZONE_TEMP_STEP, {}))
        self._zone_temp_step = {
            unit_id: _normalize_temp_step(value)
            for unit_id, value in self._zone_temp_step.items()
        }
        self._unit_labels = {unit_id: unit_id for unit_id in self._unit_order}

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage options one unit at a time."""
        if not self._unit_order:
            return self.async_create_entry(title="", data={})

        if user_input is not None:
            current_unit_id = self._unit_order[self._unit_index]
            self._zone_min_temp[current_unit_id] = float(user_input.get(FIELD_MIN_TEMP, DEFAULT_MIN_TEMP))
            self._zone_max_temp[current_unit_id] = float(user_input.get(FIELD_MAX_TEMP, DEFAULT_MAX_TEMP))
            self._zone_temp_step[current_unit_id] = _normalize_temp_step(
                user_input.get(FIELD_TEMP_STEP, DEFAULT_ZONE_TEMP_STEP)
            )
            self._unit_index += 1

            if self._unit_index >= len(self._unit_order):
                new_data = dict(self._config_entry.data)
                new_data[CONF_ZONE_MIN_TEMP] = dict(self._zone_min_temp)
                new_data[CONF_ZONE_MAX_TEMP] = dict(self._zone_max_temp)
                new_data[CONF_ZONE_TEMP_STEP] = dict(self._zone_temp_step)
                self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
                return self.async_create_entry(title="", data={})

        await self._refresh_unit_labels()
        return self._show_unit_options_form()

    async def _refresh_unit_labels(self) -> None:
        """Fetch current unit labels for the options flow."""
        if self._unit_labels and all(label != unit_id for unit_id, label in self._unit_labels.items()):
            return

        host = self._config_entry.data[CONF_HOST]
        port = self._config_entry.data.get(CONF_PORT, DEFAULT_PORT)
        api_key = self._config_entry.data.get(CONF_API_KEY, "")

        params: dict[str, Any] = {"scope": "config"}
        if api_key:
            params["apikey_rest"] = api_key

        url = build_api_url(host, port, API_CLIMATE_ENDPOINT, params)

        try:
            async with aiohttp.ClientSession() as session:
                async with async_timeout.timeout(10):
                    response = await session.get(url)
                    if response.status != 200:
                        return
                    payload = await response.json()
                    normalized = parse_climate_payload(payload)
                    units = normalized.get("units", {})
                    self._unit_labels = {
                        unit_id: get_unit_label(unit_id, units.get(unit_id, {}))
                        for unit_id in self._unit_order
                    }
        except Exception as err:
            _LOGGER.debug("Could not refresh ioHouse unit labels for options flow: %s", err)

    def _show_unit_options_form(self) -> FlowResult:
        """Render the current unit options form."""
        current_unit_id = self._unit_order[self._unit_index]
        current_label = self._unit_labels.get(current_unit_id, current_unit_id)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_MIN_TEMP, default=self._zone_min_temp.get(current_unit_id, DEFAULT_MIN_TEMP)): vol.All(
                        vol.Coerce(float),
                        vol.Range(min=0, max=200),
                    ),
                    vol.Required(FIELD_MAX_TEMP, default=self._zone_max_temp.get(current_unit_id, DEFAULT_MAX_TEMP)): vol.All(
                        vol.Coerce(float),
                        vol.Range(min=0, max=200),
                    ),
                    vol.Required(FIELD_TEMP_STEP, default=self._zone_temp_step.get(current_unit_id, DEFAULT_ZONE_TEMP_STEP)): vol.All(
                        vol.Coerce(float),
                        vol.Range(min=0.1, max=1.0),
                    ),
                }
            ),
            description_placeholders={
                "unit_name": current_label,
                "unit_index": str(self._unit_index + 1),
                "unit_total": str(len(self._unit_order)),
            },
        )
