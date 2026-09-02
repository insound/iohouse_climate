[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)

# iOhouse Climate Integration for Home Assistant

**Интеграция Home Assistant для климат-контроллеров iOhouse Thermozone**

Интеграция использует grouped `api_climate`/`apiaction` v2 и автоматически подхватывает структуру устройств из самого контроллера. Вместо жёсткой модели из 4 legacy-зон `A1/A2/B1/B2` Home Assistant теперь строит сущности по фактически загруженным устройствам `unit_id` и группам, которые контроллер отдаёт в `cfg.groups[].d[]`.

Актуальная версия интеграции — **2.8.0**. Для полного набора функций рекомендуется прошивка контроллера **2.0110** или новее; совместимость с более ранними версиями прошивки сохранена. Подробности выпуска собраны в [CHANGELOG.md](CHANGELOG.md).

## Возможности

### Климат-контроль

- **Динамическая структура устройств**: интеграция больше не ограничена 4 фиксированными зонами и загружает все климатические устройства так, как они сконфигурированы в контроллере
- **Имена и группы из контроллера**: Home Assistant использует `group_name` и имя устройства, а не искусственные `A1/A2/B1/B2`
- **Управление температурой**: изменение уставки, включение/выключение, пресеты `Comfort`, `Away`, `Eco`, `Home`, `Sleep`
- **Индивидуальные лимиты**: для каждого обнаруженного устройства можно задать свои `min/max/step`
- **Быстрый отклик UI**: состояние обновляется сразу после успешной команды

### Управление группами

- **Комнатные climate**: если в группе контроллера включено `Управление группой`, Home Assistant создаёт отдельную `climate`-сущность комнаты для воздушного отопления и/или тёплого пола
- **Комнатный dehumidifier**: группа с вытяжкой/осушением создаёт отдельную `humidifier`-сущность с device class `dehumidifier`
- **Охлаждение и вентиляция комнаты**: управляемая группа с совместимым фанкойлом получает `Cool`, а с участниками вентиляции — `Fan only`
- **Блокировка дочерних устройств**: устройства внутри такой группы остаются видимыми для мониторинга, но у них скрывается ручное управление целевой температурой, питанием и пресетами
- **Единая команда**: изменение комнатной сущности отправляется на контроллер как групповая команда, а контроллер уже распределяет уставки по устройствам и iOnet

### Влагоудаление

- **Осушитель как humidifier**: зоны `Влагоудаление ON_OFF` (`selected_mode=12`) создаются как `humidifier` с device class `dehumidifier`, а не как `climate`
- **Управление влажностью**: текущая влажность, целевая влажность, включение/выключение и состояние `drying/idle/off`
- **Совместимость**: интеграция распознаёт влагоудаление по явному флагу `hu` или по режиму `selected_mode=12`

### Ручной режим

- **Ручные устройства как switch**: устройства `Ручной режим` (`selected_mode=2`) создаются как обычные `switch`, а не как `climate`
- **Прямое включение/выключение**: команды отправляются через `apiaction` по `unit_id`, как и для остальных устройств v2
- **Без температурных лимитов**: мастер настройки `min/max/step` пропускает ручные устройства

### Мониторинг

- **PWM сенсоры**: уровень модуляции по каждому устройству в диапазоне `0-100%`
- **DS18B20**: все настроенные 1-wire датчики контроллера передаются в Home Assistant
- **DHT**: температура и влажность по DHT-каналам контроллера передаются отдельными сенсорами только для реально доступных каналов
- **Телеметрия клапанов**: позиция и состояние клапана для 2-pin зон
- **Ручные outputs**: выходы контроллера создаются как switch-сущности, показывают живое состояние даже когда заняты логикой контроллера, но ручные команды для занятых каналов не отправляются
- **Летний режим**: глобальный переключатель системы
- **Независимые охлаждение и вентиляция**: глобальные переключатели используют разные capability прошивки (`ce` и `ve`); фанкойлы `selected_mode=11` получают `Cool`, а участвующие устройства режимов 8–12 — `Fan only`
- **Вентиляция по CO₂**: для каждой участвующей группы создаются сенсоры текущего CO₂ и рассчитанного запроса вентиляции, а fallback без валидного CO₂ отображается отдельным диагностическим binary sensor
- **Ведомая вытяжка**: SLAVE-вытяжка больше не отображается ложным термостатом; Home Assistant показывает её активность, текущую ступень/PWM и `unit_id` фанкойла-источника
- **ТЭН фанкойла**: температура воздуха после встроенного ТЭНа публикуется отдельным диагностическим сенсором, когда прошивка отдаёт `fht`
- **Оконная блокировка группы**: состояние защиты по датчику открытия доступно как binary sensor комнаты
- **Диагностические атрибуты**: `unit_id`, группа, выбранный режим, тип устройства, burner и служебные флаги

### Обновления

- **OTA обновление прошивки** через Home Assistant
- **Проверка доступной версии** и сущность `update`

### Автообнаружение

- **SSDP / UPnP**
- **DHCP**
- **Zeroconf / mDNS**
- **Пошаговый мастер настройки** с конфигурацией лимитов температуры по каждому устройству

## Установка

### Через HACS

#### Стандартный способ

1. Откройте **HACS** в Home Assistant.
2. Перейдите в раздел **Integrations**.
3. Если репозиторий ещё не добавлен, откройте меню с тремя точками и выберите **Custom repositories**.
4. Добавьте URL `https://github.com/insound/iohouse_climate`.
5. Выберите категорию **Integration**.
6. Установите **iOhouse Climate**.
7. Перезапустите Home Assistant.

### Ручная установка

1. Скачайте последнюю версию из [releases](https://github.com/insound/iohouse_climate/releases).
2. Извлеките каталог `custom_components/iohouse_climate` в конфигурацию Home Assistant.
3. Перезапустите Home Assistant.

## Настройка

### Автоматическая настройка

Интеграция поддерживает автообнаружение контроллеров iOhouse в локальной сети:

1. Перейдите в **Settings** → **Devices & Services**.
2. Если контроллер найден автоматически, Home Assistant покажет предложение настроить интеграцию.
3. Нажмите **Configure** и пройдите мастер.

### Ручная настройка

1. Перейдите в **Settings** → **Devices & Services**.
2. Нажмите **Add Integration**.
3. Найдите **iOhouse Climate**.
4. Введите параметры контроллера:
   - **IP address / Host**
   - **Port**: обычно `80`
   - **Name**
   - **API key**: опционально, если на контроллере включена авторизация
5. Интеграция считает `api_climate` v2 и покажет список реально доступных устройств из контроллера.
6. Для каждого климатического устройства задайте температурные ограничения. Зоны влагоудаления, ручные устройства и дочерние устройства под `Управлением группой` на этом шаге пропускаются, потому что их ручная целевая температура не управляется отдельной climate-сущностью.

### Параметры настройки устройства

Для каждого обнаруженного климатического устройства можно настроить:

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| **Min temperature** | Минимальная уставка | `1.0` |
| **Max temperature** | Максимальная уставка | `100.0` |
| **Temperature step** | Шаг изменения температуры | `0.1` |

## Создаваемые сущности

### Climate

- `climate.<group>_<device>`: климатическое устройство, созданное по `unit_id` и имени из контроллера
- `climate.<group>_climate`: комнатное управление воздушным отоплением для группы с включённым `Управлением группой`
- `climate.<group>_floor`: комнатное управление тёплым полом для группы с включённым `Управлением группой`
- режимы: `Heat`, `Off`, а для совместимого оборудования также `Cool` и `Fan only`
- пресеты: `Comfort`, `Away`, `Eco`, `Home`, `Sleep`

### Humidifier

- `humidifier.<group>_<device>`: зона влагоудаления/осушитель с device class `dehumidifier`
- `humidifier.<group>_dehumidifier`: комнатное управление влагоудалением для группы с включённым `Управлением группой`
- влажность: текущая и целевая в процентах
- режимы состояния: `drying`, `idle`, `off`

### Sensor

- `sensor.<device>_pwm`: диагностический PWM-сенсор
- `sensor.<controller>_wifi_rssi`: уровень сигнала Wi-Fi контроллера
- `sensor.<controller>_free_heap`: свободная heap-память контроллера
- `sensor.<controller>_uptime`: аптайм контроллера
- `sensor.<ds18b20>`: температура DS18B20
- `sensor.<dht>_temperature`: температура DHT
- `sensor.<dht>_humidity`: влажность DHT
- `sensor.<group>_ventilation_demand`: рассчитанная производительность вентиляции группы, %
- `sensor.<group>_co2`: валидное значение CO₂, которое использует контроллер, ppm
- `sensor.<device>_fancoil_heater_air_temperature`: температура воздуха после встроенного ТЭНа фанкойла

### Valve

- `valve.<device>_valve`: сущность клапана для устройств с 2-pin телеметрией

### Switch

- `switch.<device>_manual_mode`: устройство `Ручной режим`, созданное по `unit_id`
- `switch.<controller>_summer_mode`: летний режим контроллера
- `switch.<controller>_cooling_mode`: глобальный режим охлаждения, доступен когда контроллер отдаёт `cooling_modes_enabled`
- `switch.<controller>_ventilation_mode`: независимый глобальный режим вентиляции, доступен когда контроллер отдаёт `ventilation_modes_enabled`
- `switch.<controller>_output_N`: ручные выходы контроллера; занятые контроллером каналы остаются видимыми и показывают live-state, но ручное переключение для них игнорируется

### Update

- `update.<controller>_firmware`: обновление прошивки

### Binary Sensor

- `binary_sensor.<controller>_legionella_work`: активен ли сейчас цикл антилегионеллы
- `binary_sensor.<group>_opening_guard`: блокирует ли открытое окно/дверь климат группы
- `binary_sensor.<group>_ventilation_co2_fallback`: используется ли минимальная вентиляция из-за отсутствующего/невалидного CO₂
- `binary_sensor.<device>_exhaust_ventilation`: активна ли ведомая вытяжка, следующая за фанкойлом

## Важные замечания

- `api_climate` рассчитан на использование в доверенной локальной сети
- если на контроллере включён API key, write-команды требуют `apikey_rest`
- для наиболее согласованного поведения рекомендуется обновлять **прошивку контроллера** и **HA integration** вместе
- при переходе со старой интеграции, где адресация строилась на `A1/A2/B1/B2`, стоит проверить пользовательские `min/max/step`, потому что теперь они привязаны к `unit_id`
- если устройство находится в группе с включённым `Управлением группой`, его дочерняя сущность в Home Assistant используется для мониторинга; ручные команды надо отправлять в комнатную сущность группы
- DHT-сущности создаются только когда контроллер сообщает валидный и доступный DHT-канал; неподключённые каналы больше не появляются как `unknown`
- `Cool` и `Fan only` переключают глобальные режимы контроллера `cm`/`vm`, как и соответствующие переключатели; это влияет на все совместимые устройства, а не только на одну карточку

## Пример автоматизации

```yaml
automation:
  - alias: "Night Eco Mode"
    trigger:
      platform: time
      at: "22:00:00"
    action:
      service: climate.set_preset_mode
      target:
        entity_id: climate.kitchen_floor
      data:
        preset_mode: "eco"
```

## Что изменилось в 2.8.0

- вентиляция полностью отделена от охлаждения: интеграция читает `ve`/`vent.en`, а на старой прошивке сохраняет совместимость через прежний `ce`
- для участвующих устройств режимов 8–12 и управляемых комнат добавлен HVAC mode `Fan only`; групповое охлаждение теперь получает `Cool`, если в комнате есть совместимый фанкойл
- добавлены групповые CO₂ и ventilation-demand сенсоры, fallback и opening-guard binary sensors
- добавлена телеметрия встроенного ТЭНа фанкойла и ведомой SLAVE-вытяжки; вытяжка исключена из climate-сущностей
- разобраны новые поля API v2: `ve`, `vent`, `v`, `vp`, `fsrc`, `fht`, `co2`, `ob`

## Что изменилось в 2.7.1

- восстановлено создание дочерних `climate`, `humidifier`, `switch`, `sensor` и `valve` сущностей на Home Assistant до `2026.8`
- связь дочернего устройства с контроллером теперь использует поддерживаемый текущей версией Home Assistant ключ: `via_device_id` на новых установках и `via_device` на старых

## Что изменилось в 2.7.0

- добавлены групповые climate-сущности для комнатного управления отоплением и тёплым полом
- добавлены групповые humidifier/dehumidifier-сущности для комнатного управления влагоудалением
- дочерние устройства в группе с `Управлением группой` остаются в Home Assistant как мониторинг, но больше не принимают ручные команды уставки, питания и пресетов
- команды групп отправляются через `/apiaction?gid=<group_id>&gk=<kind>` и совместимы с новым `api_climate` v2 payload
- мастер настройки температурных лимитов пропускает дочерние устройства, у которых целевая температура управляется группой

## Что изменилось в 2.6.3

- минимальная версия Home Assistant в `hacs.json` поднята до `2024.1.0`, потому что интеграция использует платформу `valve`
- для HACS release asset включён явный режим `zip_release`
- `manifest.json` обновлён под актуальные рекомендации Home Assistant: добавлен `integration_type: hub`, убрана лишняя зависимость `aiohttp`
- процентные сенсоры используют `UnitOfRatio.PERCENTAGE` на новых версиях Home Assistant с fallback для старых установок
- на Home Assistant с поддержкой `via_device_id` дочерние устройства зон связываются с контроллером по registry ID

## Что изменилось в 2.6.2

- устройства `Ручной режим` (`selected_mode=2`) больше не создаются как `climate`
- для ручных устройств добавлены обычные `switch`-сущности с управлением через `/apiaction?uid=<unit_id>&p=0|1`
- мастер настройки температурных лимитов пропускает ручные устройства
- проверка прошивки считает `upd=1` достаточным признаком обновления, даже если контроллер временно не отдал `uv`
- сущность обновления прошивки получила русские название, краткое описание и release notes

## What changed in 2.6.1

- linked fan coil valves use the fan coil temperature/setpoint from `api_climate`
- linked fan coil valves no longer expose independent target temperature or preset controls

## What changed in 2.6.0

- controller-level cooling and ventilation switches are exposed from `api_climate` system fields `ce/cm/vm`
- heat/cool fan coils (`selected_mode=11`) now expose `cool` HVAC mode when controller cooling modes are enabled
- `climate.set_hvac_mode(cool)` and `climate.set_temperature(..., hvac_mode=cool)` switch the controller into cooling mode through `/apiaction?cm=1`

## What changed in 2.5.0

- humidity-control zones (`selected_mode=12` / `hu=1`) are now exposed as Home Assistant `humidifier` entities with `dehumidifier` device class instead of `climate`
- dehumidifier entities support current humidity, target humidity, turn on/off and `drying/idle/off` action state
- climate setup/options now skip dehumidifier zones when showing per-unit temperature limits
- parser keeps humidity-control metadata from both explicit `hu` and legacy mode-12 payloads

## What changed in 2.4.0

- auto-discovery now better matches both `iohouse` and `thermozone` controller naming
- discovery setup no longer tries to read units before the user had a chance to enter an API key
- controller diagnostics now expose Wi-Fi RSSI, free heap and uptime sensors
- controller `legionella_work` is now available as a read-only binary sensor
- `api_climate` parsing now keeps more v2 metadata, including `up`, `lw`, `ft`, `ca`, config `cap`, `zone` and config-side `sl`
- valve entities can now appear later when valve telemetry becomes available after startup, instead of only on the first refresh
- options flow refreshes the current controller unit list before editing per-unit temperature limits

## What changed in 2.3.2

- firmware update entity now preserves the last known `upd/fw/uv` values when partial `st.sys` payloads omit them, so the Home Assistant update sensor no longer drops into an unavailable/unknown state after otherwise successful controller requests

## What changed in 2.3.1

- controller device is registered before child zone devices reference it through `via_device`
- partial `/apiaction` responses no longer make unrelated climate entities temporarily unavailable
- `climate.set_temperature` now sends `temperature` and `hvac_mode` together when Home Assistant provides both
- multi-entity climate actions with identical parameters are coalesced into one `/apiaction` request
- batched zone commands are sent as repeated query arguments, for example `uid=a&uid=b&p=1`
- the controller also accepts the fallback `uids=a,b` form for batch zone actions

## What changed in 2.3.0

- DS18B20 and DHT controller sensors now preserve hundredths in Home Assistant, while climate entities intentionally stay at `0.1`
- busy controller outputs now remain visible as live switches in Home Assistant, but manual commands for occupied outputs are blocked locally and are not sent to the controller

## What changed in 2.2.1

- DHT discovery was tightened: disconnected DHT channels no longer create `unknown` entities in Home Assistant
- already created DHT entities now correctly become unavailable if the sensor disappears or loses valid data

## What changed in 2.2.0

- manual controller outputs were restored as Home Assistant switches
- all configured `DS18B20` and available `DHT` sensors are now exposed as Home Assistant sensors
- integration now reads controller IO metadata from the same v2 payload instead of depending on legacy-only paths

## What changed in 2.1.2

- `current temperature` и `target temperature` приведены к той же видимой точности `0.1 °C`, что используется в локальном интерфейсе контроллера
- `target temperature` теперь следует за эффективной уставкой контроллера, поэтому Home Assistant не расходится с локальным UI после изменения температуры
- шаг температуры по умолчанию выровнен до `0.1`, а старые более мелкие значения мягко нормализуются при обновлении настроек

## What changed in 2.1.1

- добавлен `strings.json`, чтобы config/options flow показывал нормальные подписи полей и имя устройства на каждом шаге настройки

## What changed in 2.1.0

- интеграция переведена на `api_climate` v2 grouped payload
- discovery теперь использует стабильные `unit_id` из `cfg.groups[].d[]`
- polling использует `cfg_hash` и автоматическое обновление конфигурации при изменениях
- write-команды отправляются через `apiaction?uid=<unit_id>&...`
- метаданные устройств включают `group_name`, `selected_mode` и `device_type`
- неподдерживаемые legacy output write switches удалены из публичного API интеграции
