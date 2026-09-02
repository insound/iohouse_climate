"""Shared entity helpers for ioHouse Climate."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_NAME,
    CONF_ZONE_MAX_TEMP,
    CONF_ZONE_MIN_TEMP,
    CONF_ZONE_TEMP_STEP,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_ZONE_TEMP_STEP,
    DOMAIN,
)

VENTILATION_MODE_MIN = 8
VENTILATION_MODE_MAX = 12
EXHAUST_VENTILATION_MODE = 17
EXHAUST_VENTILATION_DEVICE_TYPE = 5


def get_unit_name(unit_id: str, unit_data: dict[str, Any]) -> str:
    """Return a stable human-readable unit name."""
    name = str(unit_data.get("name") or "").strip()
    return name or unit_id


def get_unit_label(unit_id: str, unit_data: dict[str, Any]) -> str:
    """Return a label including the room/group when available."""
    unit_name = get_unit_name(unit_id, unit_data)
    group_name = str(unit_data.get("group_name") or "").strip()
    if group_name:
        return f"{group_name} / {unit_name}"
    return unit_name


def get_unit_device_info(
    entry: ConfigEntry,
    unit_id: str,
    unit_data: dict[str, Any],
    controller_device_id: str | None = None,
) -> dict[str, Any]:
    """Build device info for a thermostat unit."""
    device_info = {
        "identifiers": {(DOMAIN, f"{entry.entry_id}_{unit_id}")},
        "name": get_unit_name(unit_id, unit_data),
        "manufacturer": "iOhouse",
        "model": get_unit_model(unit_data),
    }
    _add_controller_device_link(device_info, entry, controller_device_id)
    return device_info


def get_group_device_info(
    entry: ConfigEntry,
    group_id: str,
    group_data: dict[str, Any],
    controller_device_id: str | None = None,
) -> dict[str, Any]:
    """Build device info for a group-control room."""
    group_name = str(group_data.get("name") or group_id).strip() or group_id
    device_info = {
        "identifiers": {(DOMAIN, f"{entry.entry_id}_group_{group_id}")},
        "name": group_name,
        "manufacturer": "iOhouse",
        "model": "Thermozone Group Control",
    }
    _add_controller_device_link(device_info, entry, controller_device_id)
    return device_info


def _add_controller_device_link(
    device_info: dict[str, Any],
    entry: ConfigEntry,
    controller_device_id: str | None,
) -> None:
    """Link child devices without using DeviceInfo keys unsupported by older HA."""
    device_info_fields = getattr(dr.DeviceInfo, "__annotations__", {})
    if "via_device_id" in device_info_fields:
        if controller_device_id:
            device_info["via_device_id"] = controller_device_id
        return

    device_info["via_device"] = (DOMAIN, entry.entry_id)


def get_controller_device_info(entry: ConfigEntry) -> dict[str, Any]:
    """Build device info for controller-level entities."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.data.get(CONF_NAME, "iOhouse Thermozone"),
        "manufacturer": "iOhouse",
        "model": "Thermozone Controller",
    }


def get_controller_device_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return the controller device registry ID for via-device links."""
    device_registry = dr.async_get(hass)
    if hasattr(device_registry, "async_get_device_by_identifier"):
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, entry.entry_id),
            entry.entry_id,
        )
    else:
        device = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    return device.id if device else None


def get_unit_model(unit_data: dict[str, Any]) -> str:
    """Return a best-effort device model label."""
    if is_exhaust_ventilation_unit(unit_data):
        return "Thermozone Exhaust Ventilation"
    if is_humidifier_unit(unit_data):
        return "Thermozone Dehumidifier"
    if is_heatcool_fancoil_unit(unit_data):
        return "Thermozone Fan Coil"
    if has_valve_data(unit_data):
        return "Thermozone Valve Zone"
    if is_manual_unit(unit_data):
        return "Thermozone Manual Device"
    return "Thermozone Climate Unit"


def get_unit_settings(entry: ConfigEntry, unit_id: str) -> tuple[float, float, float]:
    """Return min, max and step values for a unit."""
    min_temp = entry.data.get(CONF_ZONE_MIN_TEMP, {}).get(unit_id, DEFAULT_MIN_TEMP)
    max_temp = entry.data.get(CONF_ZONE_MAX_TEMP, {}).get(unit_id, DEFAULT_MAX_TEMP)
    temp_step = entry.data.get(CONF_ZONE_TEMP_STEP, {}).get(unit_id, DEFAULT_ZONE_TEMP_STEP)
    normalized_step = max(0.1, float(temp_step))
    return float(min_temp), float(max_temp), normalized_step


def is_manual_unit(unit_data: dict[str, Any]) -> bool:
    """Manual mode is exposed by selected_mode=2."""
    return int(unit_data.get("selected_mode") or 0) == 2


def is_humidifier_unit(unit_data: dict[str, Any]) -> bool:
    """Humidity-control zones are exposed through HA humidifier."""
    return bool(unit_data.get("humidifier")) or int(unit_data.get("selected_mode") or 0) == 12


def is_heatcool_fancoil_unit(unit_data: dict[str, Any]) -> bool:
    """Three-speed heater/cooler fan coils are exposed with heat/cool modes."""
    return int(unit_data.get("selected_mode") or 0) == 11


def is_exhaust_ventilation_unit(unit_data: dict[str, Any]) -> bool:
    """Follower exhaust zones are monitoring-only ventilation devices."""
    return (
        int(unit_data.get("selected_mode") or 0) == EXHAUST_VENTILATION_MODE
        and bool(unit_data.get("slave"))
        and int(unit_data.get("device_type") or 0) == EXHAUST_VENTILATION_DEVICE_TYPE
    )


def unit_supports_ventilation(unit_data: dict[str, Any]) -> bool:
    """Return whether a unit participates in the independent ventilation mode."""
    selected_mode = int(unit_data.get("selected_mode") or 0)
    return (
        VENTILATION_MODE_MIN <= selected_mode <= VENTILATION_MODE_MAX
        and not bool(unit_data.get("slave"))
        and bool(unit_data.get("ventilation_participation", selected_mode == 11))
    )


def is_climate_unit(unit_data: dict[str, Any]) -> bool:
    """Return units represented by Home Assistant climate entities."""
    return (
        not is_humidifier_unit(unit_data)
        and not is_manual_unit(unit_data)
        and not is_exhaust_ventilation_unit(unit_data)
    )


def unit_supports_target_temperature(unit_data: dict[str, Any]) -> bool:
    """Only climate algorithm units expose target temperature control."""
    return (
        not is_humidifier_unit(unit_data)
        and not is_manual_unit(unit_data)
        and not bool(unit_data.get("slave"))
        and not bool(unit_data.get("group_locked"))
        and not bool(unit_data.get("target_locked"))
    )


def unit_supports_power_control(unit_data: dict[str, Any]) -> bool:
    """Group-controlled children keep telemetry but lose direct power control."""
    return not bool(unit_data.get("slave")) and not bool(unit_data.get("group_locked"))


def unit_supports_presets(unit_data: dict[str, Any]) -> bool:
    """Manual devices do not have preset semantics in HA."""
    return (
        not is_humidifier_unit(unit_data)
        and not is_manual_unit(unit_data)
        and not bool(unit_data.get("group_locked"))
        and not bool(unit_data.get("target_locked"))
    )


def has_valve_data(unit_data: dict[str, Any]) -> bool:
    """Two-pin zones expose valve telemetry in v2 state."""
    valve_keys = (
        "valve_position",
        "valve_opening",
        "valve_closing",
        "valve_closed",
        "valve_opened",
    )
    return any(unit_data.get(key) is not None for key in valve_keys)


def format_target_temperature(value: float) -> str:
    """Format setpoint values for apiaction."""
    return f"{round(float(value), 2):.2f}".rstrip("0").rstrip(".")
