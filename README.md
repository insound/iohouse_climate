[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)

# iOhouse Climate Integration for Home Assistant

**Интеграция Home Assistant для климат-контроллеров iOhouse Thermozone**

Интеграция использует grouped `api_climate`/`apiaction` v2 и автоматически подхватывает структуру устройств из самого контроллера. Вместо жёсткой модели из 4 legacy-зон `A1/A2/B1/B2` Home Assistant теперь строит сущности по фактически загруженным устройствам `unit_id` и группам, которые контроллер отдаёт в `cfg.groups[].d[]`.

## Возможности

### Климат-контроль

- **Динамическая структура устройств**: интеграция больше не ограничена 4 фиксированными зонами и загружает все климатические устройства так, как они сконфигурированы в контроллере
- **Имена и группы из контроллера**: Home Assistant использует `group_name` и имя устройства, а не искусственные `A1/A2/B1/B2`
- **Управление температурой**: изменение уставки, включение/выключение, пресеты `Comfort`, `Away`, `Eco`, `Home`, `Sleep`
- **Индивидуальные лимиты**: для каждого обнаруженного устройства можно задать свои `min/max/step`
- **Быстрый отклик UI**: состояние обновляется сразу после успешной команды

### Мониторинг

- **PWM сенсоры**: уровень модуляции по каждому устройству в диапазоне `0-100%`
- **DS18B20**: все настроенные 1-wire датчики контроллера передаются в Home Assistant
- **DHT**: температура и влажность по DHT-каналам контроллера передаются отдельными сенсорами только для реально доступных каналов
- **Телеметрия клапанов**: позиция и состояние клапана для 2-pin зон
- **Ручные outputs**: выходы контроллера создаются как switch-сущности, показывают живое состояние даже когда заняты логикой контроллера, но ручные команды для занятых каналов не отправляются
- **Летний режим**: глобальный переключатель системы
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
6. Для каждого устройства задайте температурные ограничения.

### Параметры настройки устройства

Для каждого обнаруженного устройства можно настроить:

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| **Min temperature** | Минимальная уставка | `1.0` |
| **Max temperature** | Максимальная уставка | `100.0` |
| **Temperature step** | Шаг изменения температуры | `0.1` |

## Создаваемые сущности

### Climate

- `climate.<group>_<device>`: климатическое устройство, созданное по `unit_id` и имени из контроллера
- режимы: `Heat`, `Off`
- пресеты: `Comfort`, `Away`, `Eco`, `Home`, `Sleep`

### Sensor

- `sensor.<device>_pwm`: диагностический PWM-сенсор
- `sensor.<ds18b20>`: температура DS18B20
- `sensor.<dht>_temperature`: температура DHT
- `sensor.<dht>_humidity`: влажность DHT

### Valve

- `valve.<device>_valve`: сущность клапана для устройств с 2-pin телеметрией

### Switch

- `switch.<controller>_summer_mode`: летний режим контроллера
- `switch.<controller>_output_N`: ручные выходы контроллера; занятые контроллером каналы остаются видимыми и показывают live-state, но ручное переключение для них игнорируется

### Update

- `update.<controller>_firmware`: обновление прошивки

## Важные замечания

- `api_climate` рассчитан на использование в доверенной локальной сети
- если на контроллере включён API key, write-команды требуют `apikey_rest`
- для наиболее согласованного поведения рекомендуется обновлять **прошивку контроллера** и **HA integration** вместе
- при переходе со старой интеграции, где адресация строилась на `A1/A2/B1/B2`, стоит проверить пользовательские `min/max/step`, потому что теперь они привязаны к `unit_id`
- DHT-сущности создаются только когда контроллер сообщает валидный и доступный DHT-канал; неподключённые каналы больше не появляются как `unknown`

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
