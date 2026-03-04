[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)

# iOhouse Climate

Home Assistant custom integration for iOhouse Thermozone controllers.

## What changed in 2.1.1

- added Home Assistant `strings.json` so config/options flow shows translated field labels and step descriptions with device names

## What changed in 2.1.0

- switched to `api_climate` v2 grouped payloads
- discovery now uses stable `unit_id` from `cfg.groups[].d[]`
- polling now uses `cfg_hash` and automatic config refresh on changes
- write commands now use `apiaction?uid=<unit_id>&...`
- device metadata includes `group_name`, `selected_mode`, and `device_type`
- unsupported legacy output write switches were removed from the public API path

## Features

- climate entities for each runtime unit
- PWM diagnostic sensors
- valve telemetry for 2-pin zones
- summer mode switch
- firmware update entity

## Installation

### HACS

1. Open HACS.
2. Add `https://github.com/insound/iohouse_climate` as a custom integration repository.
3. Install `iOhouse Climate`.
4. Restart Home Assistant.

### Manual

1. Download the latest `iohouse_climate.zip` release asset.
2. Extract `custom_components/iohouse_climate` into your Home Assistant config directory.
3. Restart Home Assistant.

## Notes

- `api_climate` read requests are intended for a trusted local network.
- `apiaction` write requests require `apikey_rest` if the controller has API auth enabled.
- Existing installations moving from legacy `A1/A2/B1/B2` addressing to `unit_id` may need to review per-zone min/max/step settings after upgrade.
