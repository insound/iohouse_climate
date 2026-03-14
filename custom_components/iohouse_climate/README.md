# iOhouse Climate for Thermozone AB4

This package is built around the grouped `api_climate`/`apiaction` v2 contract.

Current package version exposes controller-level manual outputs plus `DS18B20` and `DHT` sensors through the same v2 payload.

Notes:

- climate entities are discovered dynamically from controller `unit_id` and groups, not from fixed `A1/A2/B1/B2` slots
- manual outputs are exposed as switch entities, and occupied outputs still show live state while ignoring manual toggle commands
- `DS18B20` entities are created for configured sensors
- `DHT` entities are created only for channels that are currently available and report valid data
- controller sensor values keep hundredths, while climate values intentionally stay at tenths
