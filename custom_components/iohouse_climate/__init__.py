"""ioHouse Climate integration bootstrap."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CONF_NAME, DOMAIN
from .coordinator import IOhouseDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.VALVE,
    Platform.SWITCH,
    Platform.UPDATE,
]

CONFIG_VERSION = 3
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration from YAML."""
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current version."""
    if config_entry.version >= CONFIG_VERSION:
        return True

    hass.config_entries.async_update_entry(
        config_entry,
        data=dict(config_entry.data),
        options=dict(config_entry.options),
        version=CONFIG_VERSION,
    )
    _LOGGER.info(
        "Migrated iOhouse Climate config entry %s from version %s to %s",
        config_entry.entry_id,
        config_entry.version,
        CONFIG_VERSION,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ioHouse Climate from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = IOhouseDataUpdateCoordinator(
        hass,
        async_get_clientsession(hass),
        entry,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}
    _async_register_controller_device(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "Configured iOhouse Climate for %s with units: %s",
        entry.title,
        coordinator.units,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            hass.data.pop(DOMAIN, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_controller_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ensure the controller device exists before child devices reference it."""
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="iOhouse",
        model="Thermozone Controller",
        name=entry.data.get(CONF_NAME, "iOhouse Thermozone"),
    )
