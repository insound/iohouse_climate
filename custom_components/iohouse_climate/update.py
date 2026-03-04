"""Firmware update entity for ioHouse controllers."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IOhouseDataUpdateCoordinator
from .entity_helpers import get_controller_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the firmware update entity."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([IOhouseFirmwareUpdateEntity(coordinator, entry)], update_before_add=True)


class IOhouseFirmwareUpdateEntity(
    CoordinatorEntity[IOhouseDataUpdateCoordinator],
    UpdateEntity,
):
    """Firmware updater backed by apiaction flashupdate=1."""

    _attr_has_entity_name = True
    _attr_name = "Firmware"
    _attr_icon = "mdi:cloud-download"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_firmware_update"
        self._installing = False
        self._install_started_at: float | None = None
        self._monitor_task: asyncio.Task | None = None

    @property
    def device_info(self) -> dict[str, Any]:
        return get_controller_device_info(self.entry)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def installed_version(self) -> str | None:
        version = self.coordinator.get_common_data().get("firmware_version")
        return str(version) if version else None

    @property
    def latest_version(self) -> str | None:
        common_data = self.coordinator.get_common_data()
        latest = common_data.get("available_firmware_version")
        if latest:
            return str(latest)
        return self.installed_version

    @property
    def update_available(self) -> bool:
        common_data = self.coordinator.get_common_data()
        if int(common_data.get("update_available") or 0) != 1:
            return False
        latest = self.latest_version
        installed = self.installed_version
        if not latest or not installed:
            return False
        return latest != installed

    @property
    def in_progress(self) -> bool:
        return self._installing

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = {
            "cloud_status": self.coordinator.get_common_data().get("cloud_status"),
            "update_flag": self.coordinator.get_common_data().get("update_available"),
        }
        if self._install_started_at is not None:
            attributes["install_seconds"] = int(time.time() - self._install_started_at)
        return attributes

    async def async_install(
        self,
        version: str | None = None,
        backup: bool = False,
        **kwargs: Any,
    ) -> None:
        """Trigger OTA update and keep polling until the controller comes back."""
        if not self.update_available or self._installing:
            return

        self._installing = True
        self._install_started_at = time.time()
        self.async_write_ha_state()

        success = await self.coordinator.send_update_command()
        if not success:
            self._installing = False
            self._install_started_at = None
            self.async_write_ha_state()
            return

        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        self._monitor_task = self.hass.async_create_task(self._monitor_update())

    async def _monitor_update(self) -> None:
        """Poll until the controller reports no pending update."""
        try:
            await asyncio.sleep(20)
            for _ in range(12):
                await self.coordinator.async_request_refresh()
                if not self.update_available:
                    break
                await asyncio.sleep(20)
        finally:
            self._installing = False
            self._install_started_at = None
            self.async_write_ha_state()

    async def async_release_notes(self) -> str | None:
        """Return short release notes."""
        if not self.latest_version:
            return None
        return "\n".join(
            [
                "iOhouse firmware update",
                "",
                f"Current version: {self.installed_version or 'unknown'}",
                f"Available version: {self.latest_version}",
                "",
                "The controller downloads and installs firmware on its own.",
                "During the update the device may be temporarily unavailable.",
            ]
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel background monitor task."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        await super().async_will_remove_from_hass()
