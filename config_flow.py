from __future__ import annotations
import logging
import voluptuous as vol
import aiohttp
import async_timeout
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.components import ssdp

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_NAME,
    CONF_API_KEY,
    CONF_ZONES,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_ZONES
)

_LOGGER = logging.getLogger(__name__)

class IOhouseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iOhouse Climate."""
    
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                host = user_input[CONF_HOST]
                port = user_input.get(CONF_PORT, DEFAULT_PORT)
                api_key = user_input.get(CONF_API_KEY, "")
                
                # Discover zones
                zones = await self._discover_zones(host, port, api_key)
                if not zones:
                    raise ValueError("No active zones found")

                # Set unique ID
                unique_id = f"{DOMAIN}-{host}-{port}-{'-'.join(zones)}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Prepare data
                data = {
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_ZONES: zones
                }
                if api_key:
                    data[CONF_API_KEY] = api_key

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=data
                )

            except Exception as err:
                _LOGGER.error("Configuration error: %s", err)
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
            errors=errors
        )

    async def _discover_zones(self, host: str, port: int, api_key: str) -> list[str]:
        """Discover active zones."""
        session = aiohttp.ClientSession()
        discovered_zones = []
        
        try:
            for zone in DEFAULT_ZONES:
                try:
                    url = f"http://{host}:{port}/api_climate?zone_{zone}=1"
                    if api_key:
                        url += f"&apikey_rest={api_key}"

                    async with async_timeout.timeout(5):
                        response = await session.get(url)
                        if response.status == 200:
                            data = await response.json()
                            if any(key.startswith(f"{zone}_") for key in data.keys()):
                                discovered_zones.append(zone)
                except Exception as e:
                    _LOGGER.debug("Zone %s check failed: %s", zone, str(e))
                    continue
        finally:
            await session.close()
        
        return discovered_zones

    async def async_step_ssdp(self, discovery_info):
        """Handle SSDP discovery."""
        model = discovery_info.get(ssdp.ATTR_UPNP_MODEL_NUMBER)
        name = discovery_info.get(ssdp.ATTR_UPNP_FRIENDLY_NAME, "")
        host = discovery_info[ssdp.ATTR_SSDP_LOCATION]

        if model == "929000226503" and name.startswith("ioHouse"):
            # Extract IP from SSDP location
            from urllib.parse import urlparse
            parsed_url = urlparse(host)
            host_ip = parsed_url.hostname
            udn = discovery_info[ssdp.ATTR_UPNP_UDN]
            await self.async_set_unique_id(udn)
            self._abort_if_unique_id_configured()

            return await self.async_step_confirm({
                "udn": udn,
                "host": discovery_info[ssdp.ATTR_SSDP_LOCATION],
                "name": discovery_info[ssdp.ATTR_UPNP_FRIENDLY_NAME]
            })

        return self.async_abort(reason="not_iohouse_device")

    async def async_step_confirm(self, user_input=None):
        """Confirm discovered device."""
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                description_placeholders={
                    "name": self.context["name"],
                    "host": self.context["host"]
                }
            )
            
        return self.async_create_entry(
            title=f"ioHouse Thermostat ({user_input['name']})",
            data={
                CONF_HOST: user_input["host"],
                CONF_NAME: user_input["name"],
                CONF_PORT: DEFAULT_PORT
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return IOhouseOptionsFlowHandler


class IOhouseOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow updates."""

    @property
    def config_entry(self):
        return self.hass.config_entries.async_get_entry(self.handler)

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_PORT,
                    default=self.config_entry.options.get(
                        CONF_PORT, 
                        self.config_entry.data.get(CONF_PORT, DEFAULT_PORT)
                    )
                ): int
            })
        )
    

async def async_step_zeroconf(self, discovery_info: zeroconf.ZeroconfServiceInfo) -> FlowResult:
    """Обработка Zeroconf-обнаружения."""
    host = discovery_info.host
    port = discovery_info.port
    
    # Проверка наличия устройства
    if not await self._is_device_valid(host, port):
        return self.async_abort(reason="not_iohouse_device")
    
    # Установка уникального ID
    unique_id = discovery_info.properties.get("id", host)
    await self.async_set_unique_id(unique_id)
    self._abort_if_unique_id_configured()
    
    return self.async_create_entry(
        title=f"ioHouse {host}",
        data={"host": host, "port": port}
    )


async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo) -> FlowResult:
    """Обработка DHCP-обнаружения."""
    host = discovery_info.ip

    
    # Проверка MAC-адреса
    if host.startswith(("ioHouse", "iOHouse")):
        return self.async_abort(reason="invalid_name")
    
    # Установка уникального ID
    await self.async_set_unique_id(mac)
    self._abort_if_unique_id_configured()
    
    return self.async_create_entry(
        title=f"ioHouse {mac}",
        data={"host": host}
    )