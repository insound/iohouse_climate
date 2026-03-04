"""DataUpdateCoordinator for ioHouse api_climate/apiaction v2."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_v2 import build_api_url, parse_climate_payload
from .const import (
    API_ACTION_ENDPOINT,
    API_CLIMATE_ENDPOINT,
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
    EVENT_CONTROLLER_IO_CHANGED,
    EVENT_UNITS_CHANGED,
    FULL_REFRESH_INTERVAL,
    REGULAR_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class IOhouseDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for grouped api_climate v2 payloads."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=REGULAR_UPDATE_INTERVAL,
        )
        self.session = session
        self.entry = entry
        self.host = entry.data[CONF_HOST]
        self.port = entry.data.get(CONF_PORT, 80)
        self.api_key = entry.data.get(CONF_API_KEY, "")

        self._cfg_hash = ""
        self._unit_order: list[str] = []
        self._units: dict[str, dict[str, Any]] = {}
        self._common: dict[str, Any] = {}
        self._last_full_refresh = 0.0
        self._last_commands: dict[tuple[tuple[str, str], ...], float] = {}
        self._command_debounce = 1.5

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and normalize controller data."""
        try:
            needs_full_refresh = not self._cfg_hash or self._needs_periodic_full_refresh()
            payload = await self._fetch_climate_payload(
                scope="full" if needs_full_refresh else "state",
                cfg_hash=None if needs_full_refresh else self._cfg_hash,
            )

            if (
                payload.get("cfg_changed") == 1
                and "cfg" not in payload
                and not needs_full_refresh
            ):
                payload = await self._fetch_climate_payload(scope="full")

            return self._apply_payload(payload)
        except ConfigEntryAuthFailed:
            raise
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout while talking to controller") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"HTTP error while talking to controller: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected update error: {err}") from err

    async def _fetch_climate_payload(
        self,
        scope: str,
        cfg_hash: str | None = None,
    ) -> dict[str, Any]:
        """Read api_climate payload."""
        params: dict[str, Any] = {"scope": scope}
        if cfg_hash:
            params["cfg_hash"] = cfg_hash
        if self.api_key:
            params["apikey_rest"] = self.api_key

        url = build_api_url(self.host, self.port, API_CLIMATE_ENDPOINT, params)
        timeout_seconds = 10 if scope == "full" else 6

        async with async_timeout.timeout(timeout_seconds):
            response = await self.session.get(url)
            if response.status == 401:
                raise ConfigEntryAuthFailed("Invalid API key")
            if response.status != 200:
                raise UpdateFailed(f"HTTP {response.status}")
            return await response.json()

    def _apply_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize payload and keep local caches in sync."""
        previous_units = set(self._units)
        previous_output_ids = set(self._common.get("output_order", []))
        previous_ds_ids = set(self._common.get("ds_order", []))
        previous_dht_ids = set(self._common.get("dht_order", []))
        data = parse_climate_payload(
            payload,
            previous_units=self._units,
            previous_order=self._unit_order,
            previous_common=self._common,
        )

        self._cfg_hash = data.get("cfg_hash", "") or self._cfg_hash
        self._unit_order = data.get("unit_order", [])
        self._units = data.get("units", {})
        self._common = data.get("common", {})
        if "cfg" in payload:
            self._last_full_refresh = time.time()

        current_units = set(self._units)
        if previous_units != current_units:
            self.hass.bus.async_fire(
                EVENT_UNITS_CHANGED,
                {
                    "entry_id": self.entry.entry_id,
                    "unit_ids": self.units,
                },
            )

        current_output_ids = set(self._common.get("output_order", []))
        current_ds_ids = set(self._common.get("ds_order", []))
        current_dht_ids = set(self._common.get("dht_order", []))
        if (
            previous_output_ids != current_output_ids
            or previous_ds_ids != current_ds_ids
            or previous_dht_ids != current_dht_ids
        ):
            self.hass.bus.async_fire(
                EVENT_CONTROLLER_IO_CHANGED,
                {
                    "entry_id": self.entry.entry_id,
                    "output_ids": self.output_ids,
                    "ds_ids": self.ds_sensor_ids,
                    "dht_ids": self.dht_sensor_ids,
                },
            )

        return data

    def _needs_periodic_full_refresh(self) -> bool:
        """Refresh full config periodically even if cfg_hash did not change."""
        return (time.time() - self._last_full_refresh) >= FULL_REFRESH_INTERVAL.total_seconds()

    async def send_zone_command(self, unit_id: str, params: dict[str, Any]) -> bool:
        """Send a device-level v2 action command."""
        payload = dict(params)
        payload["uid"] = unit_id
        return await self._send_action_command(payload)

    async def send_system_command(self, params: dict[str, Any]) -> bool:
        """Send a controller-level v2 action command."""
        return await self._send_action_command(dict(params))

    async def send_output_command(self, output_id: str, state: bool) -> bool:
        """Send a manual output command through apiaction v2."""
        return await self._send_action_command(
            {
                "oid": output_id,
                "ov": 1 if state else 0,
            }
        )

    async def send_update_command(self) -> bool:
        """Trigger firmware update."""
        return await self.send_system_command({"flashupdate": 1})

    async def _send_action_command(self, params: dict[str, Any]) -> bool:
        """Send apiaction and apply returned state immediately."""
        command_key = tuple(sorted((key, str(value)) for key, value in params.items()))
        now = time.time()
        last_sent = self._last_commands.get(command_key)
        if last_sent is not None and (now - last_sent) < self._command_debounce:
            return True

        request_params = dict(params)
        if self.api_key:
            request_params["apikey_rest"] = self.api_key

        url = build_api_url(self.host, self.port, API_ACTION_ENDPOINT, request_params)

        try:
            async with async_timeout.timeout(6):
                response = await self.session.get(url)
                if response.status == 401:
                    _LOGGER.error("Authentication failed while sending command: %s", params)
                    return False
                if response.status != 200:
                    _LOGGER.error("HTTP %s while sending command: %s", response.status, params)
                    return False

                payload = await response.json()
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout while sending command: %s", params)
            return False
        except aiohttp.ClientError as err:
            _LOGGER.error("HTTP client error while sending command %s: %s", params, err)
            return False
        except Exception as err:
            _LOGGER.error("Unexpected error while sending command %s: %s", params, err)
            return False

        ok = payload.get("ok") == 1 or payload.get("err") == "noop"
        if not ok:
            _LOGGER.error("Controller rejected command %s: %s", params, payload)
            return False

        self._last_commands[command_key] = now
        self.async_set_updated_data(self._apply_payload(payload))

        if payload.get("cfg_changed") == 1 and "cfg" not in payload:
            await self.async_request_refresh()

        return True

    def get_unit_data(self, unit_id: str) -> dict[str, Any]:
        """Return data for a specific unit."""
        if not self.data:
            return {}
        return self.data.get("units", {}).get(unit_id, {})

    def get_zone_data(self, zone: str) -> dict[str, Any]:
        """Backward-compatible alias used by existing entity code."""
        return self.get_unit_data(zone)

    def get_common_data(self) -> dict[str, Any]:
        """Return system/common state."""
        if not self.data:
            return {}
        return self.data.get("common", {})

    def get_output_data(self, output_id: str) -> dict[str, Any]:
        return self.get_common_data().get("outputs_map", {}).get(output_id, {})

    def get_ds_sensor_data(self, sensor_id: str) -> dict[str, Any]:
        return self.get_common_data().get("ds_map", {}).get(sensor_id, {})

    def get_dht_sensor_data(self, sensor_id: str) -> dict[str, Any]:
        return self.get_common_data().get("dht_map", {}).get(sensor_id, {})

    @property
    def units(self) -> list[str]:
        """Return known unit IDs in controller order."""
        return [unit_id for unit_id in self._unit_order if unit_id in self._units]

    @property
    def zones(self) -> list[str]:
        """Backward-compatible alias for unit IDs."""
        return self.units

    @property
    def available_units(self) -> set[str]:
        """Return unit IDs present in the latest state payload."""
        if not self.data:
            return set()
        return set(self.data.get("active_units", set()))

    @property
    def available_zones(self) -> set[str]:
        """Backward-compatible alias for unit IDs."""
        return self.available_units

    @property
    def output_ids(self) -> list[str]:
        return list(self.get_common_data().get("output_order", []))

    @property
    def ds_sensor_ids(self) -> list[str]:
        return list(self.get_common_data().get("ds_order", []))

    @property
    def dht_sensor_ids(self) -> list[str]:
        return list(self.get_common_data().get("dht_order", []))
