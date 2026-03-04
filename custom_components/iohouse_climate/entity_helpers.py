"""Shared entity helpers for ioHouse Climate."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

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
) -> dict[str, Any]:
    """Build device info for a thermostat unit."""
    return {
        "identifiers": {(DOMAIN, f"{entry.entry_id}_{unit_id}")},
        "name": get_unit_name(unit_id, unit_data),
        "manufacturer": "iOhouse",
        "model": get_unit_model(unit_data),
        "via_device": (DOMAIN, entry.entry_id),
    }


def get_controller_device_info(entry: ConfigEntry) -> dict[str, Any]:
    """Build device info for controller-level entities."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.data.get(CONF_NAME, "iOhouse Thermozone"),
        "manufacturer": "iOhouse",
        "model": "Thermozone Controller",
    }


def get_unit_model(unit_data: dict[str, Any]) -> str:
    """Return a best-effort device model label."""
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


def unit_supports_target_temperature(unit_data: dict[str, Any]) -> bool:
    """Only climate algorithm units expose target temperature control."""
    return not is_manual_unit(unit_data) and not bool(unit_data.get("slave"))


def unit_supports_presets(unit_data: dict[str, Any]) -> bool:
    """Manual devices do not have preset semantics in HA."""
    return not is_manual_unit(unit_data)


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
