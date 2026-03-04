"""Helpers for ioHouse api_climate/apiaction v2 payloads."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlencode


def build_api_url(
    host: str,
    port: int,
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Build a controller URL with query parameters."""
    base_url = f"http://{host}:{port}{endpoint}"
    if not params:
        return base_url

    query_params = []
    for key, value in params.items():
        if value is None or value == "":
            continue
        query_params.append((key, str(value)))

    if not query_params:
        return base_url

    return f"{base_url}?{urlencode(query_params)}"


def parse_climate_payload(
    payload: dict[str, Any],
    previous_units: dict[str, dict[str, Any]] | None = None,
    previous_order: list[str] | None = None,
    previous_common: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize grouped api_climate/apiaction v2 payloads."""
    previous_units = previous_units or {}
    previous_order = list(previous_order or previous_units.keys())
    previous_common = previous_common or {}

    units: dict[str, dict[str, Any]]
    unit_order: list[str]

    cfg_present = "cfg" in payload and isinstance(payload.get("cfg"), dict)
    st_present = "st" in payload and isinstance(payload.get("st"), dict)

    if cfg_present:
        units = {}
        unit_order = []
        cfg_groups = payload.get("cfg", {}).get("groups", [])
        for group in cfg_groups:
            group_id = _as_str(group.get("id"))
            group_name = _as_str(group.get("n"))
            group_protected = _as_int(group.get("p"), 0)
            for device in group.get("d", []):
                unit_id = _as_str(device.get("id"))
                if not unit_id:
                    continue

                unit = dict(previous_units.get(unit_id, {}))
                unit.update(
                    {
                        "unit_id": unit_id,
                        "name": _as_str(device.get("n")) or unit.get("name") or unit_id,
                        "group_id": group_id,
                        "group_name": group_name,
                        "group_protected": group_protected,
                        "selected_mode": _as_int(device.get("m")),
                        "device_type": _as_int(device.get("t")),
                    }
                )
                units[unit_id] = unit
                unit_order.append(unit_id)
    else:
        units = {unit_id: dict(data) for unit_id, data in previous_units.items()}
        unit_order = [unit_id for unit_id in previous_order if unit_id in units]

    active_units: set[str] = set()

    if st_present:
        st_groups = payload.get("st", {}).get("groups", [])
        for group in st_groups:
            group_id = _as_str(group.get("id"))
            for device in group.get("d", []):
                unit_id = _as_str(device.get("id"))
                if not unit_id:
                    continue

                unit = dict(units.get(unit_id, previous_units.get(unit_id, {})))
                unit.setdefault("unit_id", unit_id)
                if group_id and not unit.get("group_id"):
                    unit["group_id"] = group_id

                unit.update(
                    {
                        "power": _as_int(device.get("p")),
                        "target_power": _as_int(device.get("tp")),
                        "temperature": _normalize_temperature(device.get("t")),
                        "target_temp": _normalize_temperature(device.get("tt")),
                        "pwm": _normalize_pwm(device.get("pwm")),
                        "away_mode": _as_int(device.get("aw")),
                        "night_mode": _as_int(device.get("nt")),
                        "eco_mode": _as_int(device.get("ec")),
                        "heat_confirm": _as_int(device.get("hc")),
                        "burner": _as_int(device.get("br")),
                        "after_floor": _as_int(device.get("af")),
                        "after_floor_go": _as_int(device.get("afg")),
                        "slave": _as_int(device.get("sl")),
                        "valve_position": _as_int(device.get("vp")),
                        "valve_closing": _as_int(device.get("vcl")),
                        "valve_opening": _as_int(device.get("vop")),
                        "valve_closed": _as_int(device.get("vcd")),
                        "valve_opened": _as_int(device.get("vod")),
                    }
                )

                units[unit_id] = unit
                if unit_id not in unit_order:
                    unit_order.append(unit_id)
                active_units.add(unit_id)

    common = dict(previous_common)
    if st_present:
        common.update(_parse_common_state(payload.get("st", {}).get("sys", {})))

    if not st_present:
        active_units = set(units.keys())

    return {
        "version": _as_int(payload.get("v"), 2),
        "cfg_hash": _as_str(payload.get("cfg_hash")),
        "cfg_changed": _as_int(payload.get("cfg_changed"), 0),
        "units": units,
        "unit_order": unit_order,
        "active_units": active_units,
        "common": common,
        "timestamp": _as_int(payload.get("st", {}).get("ts")),
        "raw": payload,
    }


def _parse_common_state(sys_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize system state fields."""
    outputs = sys_data.get("o")
    normalized_outputs: list[int] = []
    if isinstance(outputs, list):
        normalized_outputs = [_as_int(value, 0) for value in outputs]

    return {
        "summer_mode": _as_int(sys_data.get("sm"), 0),
        "wifi_connected": _as_int(sys_data.get("wf"), 0),
        "wifi_rssi": _as_int(sys_data.get("wr")),
        "free_heap": _as_int(sys_data.get("fh")),
        "activation_status": _as_int(sys_data.get("act")),
        "cloud_status": _as_int(sys_data.get("cs")),
        "update_available": _as_int(sys_data.get("upd"), 0),
        "firmware_version": _as_str(sys_data.get("fw")),
        "available_firmware_version": _as_str(sys_data.get("uv")),
        "outputs": normalized_outputs,
    }


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_pwm(value: Any) -> int | None:
    pwm_value = _as_int(value)
    if pwm_value is None:
        return None
    if pwm_value > 100:
        return max(0, min(100, round(max(0, min(1023, pwm_value)) * 100 / 1023)))
    return max(0, min(100, pwm_value))


def _normalize_temperature(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None
