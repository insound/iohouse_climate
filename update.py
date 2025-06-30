"""Update platform для ioHouse."""
from __future__ import annotations
import logging

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .climate import IOhouseClimateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([FirmwareUpdate(coordinator, entry)])

class FirmwareUpdate(UpdateEntity):
    _attr_supported_features = UpdateEntityFeature.PROGRESS | UpdateEntityFeature.INSTALL
    
    def __init__(self, coordinator: IOhouseClimateCoordinator, entry: ConfigEntry):
        self.coordinator = coordinator
        self.entry = entry
        self._attr_name = "Firmware Update"
        self._attr_unique_id = f"{DOMAIN}-firmware-{entry.entry_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": "ioHouse",
            "model": "Thermo Controller",
            "name": entry.data["name"]
        }

    async def async_added_to_hass(self) -> None:
        """Подписка на обновления данных."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    def _handle_update(self) -> None:
        """Обновление состояния при изменении данных."""
        if self.hass and self.entity_id:
            self.hass.add_job(self.async_write_ha_state)  # Обернуть вызов в async_create_background_task

    @property
    def installed_version(self) -> str:
        return self.coordinator.common_data.get("fWversion", "unknown")

    @property
    def latest_version(self) -> str:
        if self.coordinator.common_data.get("avalible_update", 0) == 1:
            return self.coordinator.common_data.get("u_version", self.installed_version)
        return self.installed_version

    @property
    def in_progress(self) -> bool:
        return False  # Реализуйте при наличии статуса обновления

    async def async_install(self, version: str, backup: bool) -> None:
        await self.coordinator.session.post("/api_update")