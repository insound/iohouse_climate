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
        if isinstance(value, (list, tuple, set)):
            items = sorted(value) if isinstance(value, set) else value
            for item in items:
                if item is None or item == "":
                    continue
                query_params.append((key, str(item)))
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
    previous_active_units: set[str] | None = None,
) -> dict[str, Any]:
    """Normalize grouped api_climate/apiaction v2 payloads."""
    previous_units = previous_units or {}
    previous_order = list(previous_order or previous_units.keys())
    previous_common = previous_common or {}
    if previous_active_units is None:
        previous_active_units = set(previous_units.keys())
    else:
        previous_active_units = set(previous_active_units)

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
                        "slave": _as_int(device.get("sl"), unit.get("slave")),
                        "capability": _as_int(device.get("cap")),
                        "legacy_zone": _as_str(device.get("zone")),
                    }
                )
                units[unit_id] = unit
                unit_order.append(unit_id)
    else:
        units = {unit_id: dict(data) for unit_id, data in previous_units.items()}
        unit_order = [unit_id for unit_id in previous_order if unit_id in units]

    partial_state = "ok" in payload
    seen_state_units: set[str] = set()

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
                        "temperature": _normalize_temperature(device.get("t"), precision="0.1"),
                        "floor_temperature": (
                            _normalize_temperature(device.get("ft"), precision="0.01")
                            if "ft" in device
                            else unit.get("floor_temperature")
                        ),
                        "target_temp": _normalize_temperature(device.get("tt"), precision="0.1"),
                        "pwm": _normalize_pwm(device.get("pwm")),
                        "output_logical": _normalize_pwm(device.get("ol")),
                        "cascade_active": (
                            _normalize_int_list(device.get("ca"))
                            if "ca" in device
                            else unit.get("cascade_active", [])
                        ),
                        "away_mode": _as_int(device.get("aw")),
                        "night_mode": _as_int(device.get("nt")),
                        "eco_mode": _as_int(device.get("ec")),
                        "heat_confirm": _as_int(device.get("hc")),
                        "burner": _as_int(device.get("br")),
                        "after_floor": _as_int(device.get("af")),
                        "after_floor_go": _as_int(device.get("afg")),
                        "slave": _as_int(device.get("sl"), unit.get("slave")),
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
                seen_state_units.add(unit_id)

    common = _clone_common(previous_common)
    if cfg_present:
        _merge_controller_config(payload.get("cfg", {}), common)
    if st_present:
        common.update(_parse_common_state(payload.get("st", {}).get("sys", {}), previous_common))
        _merge_controller_state(payload.get("st", {}), common)

    if partial_state:
        active_units = set(previous_active_units)
        active_units.update(seen_state_units)
    elif st_present:
        active_units = seen_state_units
    else:
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


def _parse_common_state(
    sys_data: dict[str, Any],
    previous_common: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize system state fields while preserving values omitted in partial payloads."""
    previous_common = previous_common or {}

    state = {
        "summer_mode": previous_common.get("summer_mode", 0),
        "wifi_connected": previous_common.get("wifi_connected", 0),
        "wifi_rssi": previous_common.get("wifi_rssi"),
        "free_heap": previous_common.get("free_heap"),
        "activation_status": previous_common.get("activation_status"),
        "cloud_status": previous_common.get("cloud_status"),
        "uptime_ms": previous_common.get("uptime_ms"),
        "legionella_work": previous_common.get("legionella_work", 0),
        "update_available": previous_common.get("update_available", 0),
        "firmware_version": previous_common.get("firmware_version", ""),
        "available_firmware_version": previous_common.get("available_firmware_version", ""),
        "outputs": list(previous_common.get("outputs", [])),
    }

    if "sm" in sys_data:
        state["summer_mode"] = _as_int(sys_data.get("sm"), 0)
    if "wf" in sys_data:
        state["wifi_connected"] = _as_int(sys_data.get("wf"), 0)
    if "wr" in sys_data:
        state["wifi_rssi"] = _as_int(sys_data.get("wr"))
    if "fh" in sys_data:
        state["free_heap"] = _as_int(sys_data.get("fh"))
    if "act" in sys_data:
        state["activation_status"] = _as_int(sys_data.get("act"))
    if "cs" in sys_data:
        state["cloud_status"] = _as_int(sys_data.get("cs"))
    if "up" in sys_data:
        state["uptime_ms"] = _as_int(sys_data.get("up"))
    if "lw" in sys_data:
        state["legionella_work"] = _as_int(sys_data.get("lw"), 0)
    if "upd" in sys_data:
        state["update_available"] = _as_int(sys_data.get("upd"), 0)
    if "fw" in sys_data:
        state["firmware_version"] = _as_str(sys_data.get("fw"))
    if "uv" in sys_data:
        state["available_firmware_version"] = _as_str(sys_data.get("uv"))
    elif "upd" in sys_data and _as_int(sys_data.get("upd"), 0) != 1:
        state["available_firmware_version"] = ""
    if "o" in sys_data:
        outputs = sys_data.get("o")
        state["outputs"] = [_as_int(value, 0) for value in outputs] if isinstance(outputs, list) else []

    return state


def _clone_common(previous_common: dict[str, Any]) -> dict[str, Any]:
    common = dict(previous_common)
    common["output_order"] = list(previous_common.get("output_order", []))
    common["outputs_map"] = {
        output_id: dict(data)
        for output_id, data in previous_common.get("outputs_map", {}).items()
    }
    common["ds_order"] = list(previous_common.get("ds_order", []))
    common["ds_map"] = {
        sensor_id: dict(data)
        for sensor_id, data in previous_common.get("ds_map", {}).items()
    }
    common["dht_order"] = list(previous_common.get("dht_order", []))
    common["dht_map"] = {
        sensor_id: dict(data)
        for sensor_id, data in previous_common.get("dht_map", {}).items()
    }
    return common


def _merge_controller_config(cfg_data: dict[str, Any], common: dict[str, Any]) -> None:
    outputs_cfg = cfg_data.get("out")
    if isinstance(outputs_cfg, list):
        outputs_map: dict[str, dict[str, Any]] = {}
        output_order: list[str] = []
        for index, output in enumerate(outputs_cfg, start=1):
            output_id = _as_str(output.get("id")) or f"out{index}"
            output_data = dict(common.get("outputs_map", {}).get(output_id, {}))
            output_data.update(
                {
                    "id": output_id,
                    "name": _as_str(output.get("n")) or output_data.get("name") or f"Output {index}",
                }
            )
            outputs_map[output_id] = output_data
            output_order.append(output_id)
        common["outputs_map"] = outputs_map
        common["output_order"] = output_order

    sensors_cfg = cfg_data.get("sens")
    if isinstance(sensors_cfg, dict):
        ds_cfg = sensors_cfg.get("ds")
        if isinstance(ds_cfg, list):
            ds_map: dict[str, dict[str, Any]] = {}
            ds_order: list[str] = []
            for index, sensor in enumerate(ds_cfg, start=1):
                sensor_id = _as_str(sensor.get("id")) or f"ds{index}"
                sensor_data = dict(common.get("ds_map", {}).get(sensor_id, {}))
                sensor_data.update(
                    {
                        "id": sensor_id,
                        "name": _as_str(sensor.get("n")) or sensor_data.get("name") or f"DS18B20 {index}",
                    }
                )
                ds_map[sensor_id] = sensor_data
                ds_order.append(sensor_id)
            common["ds_map"] = ds_map
            common["ds_order"] = ds_order

        dht_cfg = sensors_cfg.get("dht")
        if isinstance(dht_cfg, list):
            dht_map: dict[str, dict[str, Any]] = {}
            for index, sensor in enumerate(dht_cfg, start=1):
                sensor_id = _as_str(sensor.get("id")) or f"dht{index}"
                sensor_data = dict(common.get("dht_map", {}).get(sensor_id, {}))
                sensor_data.update(
                    {
                        "id": sensor_id,
                        "name": _as_str(sensor.get("n")) or sensor_data.get("name") or f"DHT {index}",
                        "available": sensor_data.get("available", 0),
                    }
                )
                dht_map[sensor_id] = sensor_data
            common["dht_map"] = dht_map
            common["dht_order"] = [
                sensor_id
                for sensor_id in common.get("dht_order", [])
                if sensor_id in dht_map and _as_int(dht_map[sensor_id].get("available"), 0)
            ]


def _merge_controller_state(st_data: dict[str, Any], common: dict[str, Any]) -> None:
    outputs_map = {
        output_id: dict(data)
        for output_id, data in common.get("outputs_map", {}).items()
    }
    output_order = list(common.get("output_order", []))

    output_state = st_data.get("out")
    if isinstance(output_state, dict) and isinstance(output_state.get("d"), list):
        for index, output in enumerate(output_state.get("d", []), start=1):
            output_id = _as_str(output.get("id")) or f"out{index}"
            output_data = dict(outputs_map.get(output_id, {}))
            output_data.update(
                {
                    "id": output_id,
                    "name": output_data.get("name") or f"Output {index}",
                    "state": _as_int(output.get("s"), 0),
                    "pwm": _normalize_pwm(output.get("p")),
                    "busy": _as_int(output.get("b"), 0),
                    "owner_unit_id": _as_str(output.get("uid")),
                }
            )
            outputs_map[output_id] = output_data
            if output_id not in output_order:
                output_order.append(output_id)
    else:
        for index, value in enumerate(common.get("outputs", []), start=1):
            output_id = f"out{index}"
            output_data = dict(outputs_map.get(output_id, {}))
            output_data.update(
                {
                    "id": output_id,
                    "name": output_data.get("name") or f"Output {index}",
                    "state": _as_int(value, 0),
                    "busy": output_data.get("busy", 0),
                    "owner_unit_id": output_data.get("owner_unit_id", ""),
                }
            )
            outputs_map[output_id] = output_data
            if output_id not in output_order:
                output_order.append(output_id)

    common["outputs_map"] = outputs_map
    common["output_order"] = output_order

    sensors_state = st_data.get("sens")
    if not isinstance(sensors_state, dict):
        return

    ds_map = {
        sensor_id: dict(data)
        for sensor_id, data in common.get("ds_map", {}).items()
    }
    ds_order = list(common.get("ds_order", []))
    ds_state = sensors_state.get("ds")
    if isinstance(ds_state, list):
        for index, sensor in enumerate(ds_state, start=1):
            sensor_id = _as_str(sensor.get("id")) or f"ds{index}"
            sensor_data = dict(ds_map.get(sensor_id, {}))
            sensor_data.update(
                {
                    "id": sensor_id,
                    "name": sensor_data.get("name") or f"DS18B20 {index}",
                    "added": _as_int(sensor.get("a"), 1),
                    "error": _as_int(sensor.get("e"), 0),
                    "temperature": _normalize_temperature(sensor.get("t"), precision="0.01"),
                }
            )
            ds_map[sensor_id] = sensor_data
            if sensor_id not in ds_order:
                ds_order.append(sensor_id)
    common["ds_map"] = ds_map
    common["ds_order"] = ds_order

    dht_map = {
        sensor_id: dict(data)
        for sensor_id, data in common.get("dht_map", {}).items()
    }
    dht_order = list(common.get("dht_order", []))
    dht_state = sensors_state.get("dht")
    if isinstance(dht_state, list):
        visible_dht_ids: list[str] = []
        for index, sensor in enumerate(dht_state, start=1):
            sensor_id = _as_str(sensor.get("id")) or f"dht{index}"
            sensor_data = dict(dht_map.get(sensor_id, {}))
            sensor_available = _as_int(sensor.get("a"), 0)
            sensor_data.update(
                {
                    "id": sensor_id,
                    "name": sensor_data.get("name") or f"DHT {index}",
                    "available": sensor_available,
                    "temperature": _normalize_temperature(sensor.get("t"), precision="0.01"),
                    "humidity": _normalize_humidity(sensor.get("h"), precision="0.01"),
                }
            )
            dht_map[sensor_id] = sensor_data
            if sensor_available:
                visible_dht_ids.append(sensor_id)

        dht_order = [
            sensor_id for sensor_id in dht_order
            if sensor_id in visible_dht_ids
        ]
        for sensor_id in visible_dht_ids:
            if sensor_id not in dht_order:
                dht_order.append(sensor_id)
    common["dht_map"] = dht_map
    common["dht_order"] = dht_order


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


def _normalize_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [_as_int(item, 0) or 0 for item in value]


def _normalize_humidity(value: Any, precision: str = "0.01") -> float | None:
    humidity_value = _as_float(value)
    if humidity_value is None:
        return None
    try:
        normalized = float(
            Decimal(str(humidity_value)).quantize(Decimal(precision), rounding=ROUND_HALF_UP)
        )
    except (InvalidOperation, ValueError):
        return None
    return max(0.0, min(100.0, normalized))


def _normalize_temperature(value: Any, precision: str = "0.1") -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)).quantize(Decimal(precision), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None
