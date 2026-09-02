# iOhouse Climate for Thermozone AB4

This package is built around the grouped `api_climate`/`apiaction` v2 contract.

Current package version exposes controller group control as room-level `climate` and `humidifier` entities, independent cooling/ventilation modes, CO2-driven group ventilation diagnostics, humidity-control zones as Home Assistant `humidifier` entities with dehumidifier device class, manual-mode units and controller-level manual outputs as `switch` entities, controller diagnostics, plus `DS18B20` and `DHT` sensors through the same v2 payload.

Version 2.8.0 follows the firmware 2.0110 contract: ventilation capability `ve` is independent from cooling `ce`, participating modes 8-12 expose `fan_only`, managed fan-coil groups expose cooling, and group CO2/demand/fallback plus follower-exhaust and fan-coil-heater telemetry are available as HA entities. Firmware before 2.0110 remains compatible through its legacy cooling-backed ventilation capability.

Notes:

- climate entities are discovered dynamically from controller `unit_id` and groups, not from fixed `A1/A2/B1/B2` slots
- managed controller groups are exposed as room-level `climate` entities for air heating and floor heating
- managed dehumidification groups are exposed as room-level `humidifier`/dehumidifier entities
- child units inside managed groups keep diagnostic state but no longer accept independent target/power/preset commands
- humidity-control zones (`selected_mode=12`) are exposed as `humidifier`/dehumidifier entities instead of `climate`
- manual-mode units (`selected_mode=2`) are exposed as regular `switch` entities instead of `climate`
- heat/cool fan coils (`selected_mode=11`) expose `cool` mode when the controller reports cooling support
- ventilation participants (`selected_mode=8..12`, `vp=1`) expose `fan_only` when the controller reports independent ventilation support
- managed groups expose `cool`/`fan_only` when their device inventory supports those modes
- linked fan coil valves show the fan coil temperature/setpoint and do not expose independent target/preset controls
- controller cooling and ventilation modes are exposed as independent switch entities through `api_climate`/`apiaction`
- group ventilation demand, CO2, invalid-sensor fallback and opening guard state are exposed as sensors/binary sensors
- follower exhaust zones are monitoring-only ventilation devices instead of misleading climate entities
- optional fan-coil heater downstream air temperature is exposed as a diagnostic sensor
- manual outputs are exposed as switch entities, and occupied outputs still show live state while ignoring manual toggle commands
- controller diagnostics include Wi-Fi RSSI, free heap and uptime
- controller `legionella_work` is exposed as a read-only binary sensor
- `DS18B20` entities are created for configured sensors
- `DHT` entities are created only for channels that are currently available and report valid data
- controller sensor values keep hundredths, while climate values intentionally stay at tenths
