"""Switch platform для ioHouse."""
from __future__ import annotations
import logging
import async_timeout

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_NAME, CONF_API_KEY
from .climate import IOhouseClimateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация платформы переключателей."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Исправлено: добавлена закрывающая скобка для списка OutSwitch
    entities = [
        SummerModeSwitch(coordinator, entry),
        *[OutSwitch(coordinator, entry, i) for i in range(1, 9)]
    ]
    
    async_add_entities(entities, update_before_add=True)

class BaseIOSwitch(SwitchEntity):
    """Базовый класс для переключателей ioHouse."""
    def __init__(self, coordinator: IOhouseClimateCoordinator, entry: ConfigEntry):
        super().__init__()
        self.coordinator = coordinator
        self.entry = entry
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        coordinator.async_add_common_listener(self._handle_common_update)  # Регистрация в common_listeners

    async def async_added_to_hass(self) -> None:
        """Подписка на обновления координатора."""
        # Исправлено: добавлена закрывающая скобка для async_add_listener
        self.coordinator.async_add_common_listener(self._handle_common_update)

    async def _handle_common_update(self) -> None:  # Добавлен async!
        """Обработчик ТОЛЬКО для обновлений common_data."""
        if self.hass and self.entity_id:
            self.hass.add_job(self.async_write_ha_state)  # Обернуть вызов в async_create_background_task


    # Исправлено: метод вынесен из async_added_to_hass
    def _handle_coordinator_update(self) -> None:
        """Обновление состояния при изменении данных."""
        if self.hass and self.entity_id:
            self.hass.add_job(self.async_write_ha_state)  # Обернуть вызов в async_create_background_task

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            manufacturer="ioHouse",
            model="Thermo Controller",
            name=self.entry.data[CONF_NAME],
        )

    async def _send_command(self, command: str) -> bool:
        host = self.entry.data[CONF_HOST]
        port = self.entry.data.get(CONF_PORT, 80)
        api_key = self.entry.data.get(CONF_API_KEY, "")
        
        url = f"http://{host}:{port}/apiaction?{command}"
        if api_key:
            url += f"&apikey_rest={api_key}"

        try:
            async with async_timeout.timeout(10):
                response = await self.coordinator.session.get(url)
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "ок":
                        await self.coordinator.async_discover_zones()
                        return True
        except Exception as e:
            _LOGGER.error("Ошибка отправки команды %s: %s", command, str(e))
        return False

class SummerModeSwitch(BaseIOSwitch):
    """Переключатель летнего режима."""
    
    _attr_icon = "mdi:sun-thermometer"
    _attr_name = "Summer Mode"

    def __init__(self, coordinator: IOhouseClimateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}-summer-mode-{entry.entry_id}"

    @property
    def is_on(self) -> bool:
        return self.coordinator.common_data.get("summermode", 0) == 1

    async def async_turn_on(self, **kwargs):
        if await self._send_command("summermode=1"):
            self.coordinator.common_data["summermode"] = 1
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        if await self._send_command("summermode=0"):
            self.coordinator.common_data["summermode"] = 0
            self.async_write_ha_state()

class OutSwitch(BaseIOSwitch):
    """Переключатель выхода."""
    
    _attr_icon = "mdi:electric-switch"

    def __init__(self, coordinator: IOhouseClimateCoordinator, entry: ConfigEntry, out_num: int):
        super().__init__(coordinator, entry)
        self.out_num = out_num
        self._attr_name = f"Output {out_num}"
        self._attr_unique_id = f"{DOMAIN}-out{out_num}-{entry.entry_id}"

    @property
    def available(self) -> bool:
        return (
            self.coordinator.available and
            f"out{self.out_num}" in self.coordinator.common_data
        )
        if not self.coordinator.available:
            return self._last_available and (time.time() - self._last_unavailable < 30)
        return True


    @property
    def is_on(self) -> bool:
        return self.coordinator.common_data.get(f"out{self.out_num}", 0) == 1

    async def async_turn_on(self, **kwargs):
        if await self._send_command(f"out{self.out_num}=1"):
            self.coordinator.common_data[f"out{self.out_num}"] = 1
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        if await self._send_command(f"out{self.out_num}=0"):
            self.coordinator.common_data[f"out{self.out_num}"] = 0
            self.async_write_ha_state()