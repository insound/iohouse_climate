"""Update platform для iOhouse с умной заморозкой и современной архитектурой."""
from __future__ import annotations
import asyncio
import logging
import time 
from typing import Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityFeature,
    UpdateDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_NAME
from .coordinator import IOhouseDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Инициализация платформы обновления."""
    coordinator: IOhouseDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Создаем сущность обновления прошивки
    entities = [IOhouseFirmwareUpdateEntity(coordinator, entry)]
    
    async_add_entities(entities, update_before_add=True)

class IOhouseFirmwareUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Сущность обновления прошивки iOhouse с умной заморозкой."""
    
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | 
        UpdateEntityFeature.PROGRESS |
        UpdateEntityFeature.RELEASE_NOTES
    )
    _attr_icon = "mdi:cloud-download"
    _attr_has_entity_name = True
    _attr_name = "Firmware"

    def __init__(
        self,
        coordinator: IOhouseDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Инициализация сущности обновления прошивки."""
        super().__init__(coordinator)
        
        self.coordinator = coordinator
        self.entry = entry
        self._device_name = entry.data[CONF_NAME]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_firmware_update"
        
        # Состояние процесса обновления
        self._installing = False
        self._install_start_time = None
        self._progress_task = None
        
        _LOGGER.debug("Создана сущность обновления прошивки %s", self._attr_unique_id)

    @property
    def device_info(self) -> dict[str, Any]:
        """Информация об устройстве."""
        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": self._device_name,
            "manufacturer": "iOhouse",
            "model": "Thermozone Controller",
        }

    @property
    def available(self) -> bool:
        """Доступность сущности обновления."""
        return self.coordinator.last_update_success

    @property
    def installed_version(self) -> str | None:
        """Текущая установленная версия прошивки."""
        common_data = self.coordinator.get_common_data()
        version = common_data.get("fWversion")
        
        if version is not None:
            return str(version)
        
        return None

    @property
    def latest_version(self) -> str | None:
        """Последняя доступная версия прошивки."""
        common_data = self.coordinator.get_common_data()
        
        # Проверяем есть ли доступное обновление
        if common_data.get("avalible_update") == 1:
            update_version = common_data.get("u_version")
            if update_version is not None:
                return str(update_version)
        
        # Если обновления нет, возвращаем текущую версию
        return self.installed_version

    @property
    def update_available(self) -> bool:
        """Проверка доступности обновления."""
        if self._installing:
            return False
            
        common_data = self.coordinator.get_common_data()
        
        # Основная проверка - флаг avalible_update
        if common_data.get("avalible_update") != 1:
            return False
        
        # Дополнительная проверка - сравнение версий
        current_version = common_data.get("fWversion")
        update_version = common_data.get("u_version")
        
        if current_version is None or update_version is None:
            return False
        
        try:
            # Сравниваем версии как числа
            return float(update_version) > float(current_version)
        except (ValueError, TypeError):
            # Если не можем преобразовать в числа, сравниваем как строки
            return str(update_version) != str(current_version)

    @property
    def in_progress(self) -> bool:
        """Статус процесса обновления."""
        return self._installing

    @property
    def release_url(self) -> str | None:
        """URL страницы с информацией о релизе."""
        # Можно добавить ссылку на страницу обновлений iOhouse если есть
        return None

    @property
    def title(self) -> str:
        """Заголовок обновления."""
        if self._installing:
            return f"Installing firmware {self.latest_version}..."
        elif self.update_available and self.latest_version:
            return f"Firmware {self.latest_version} available"
        return "Firmware up to date"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Дополнительные атрибуты состояния."""
        common_data = self.coordinator.get_common_data()
        
        attributes = {
            "device_name": self._device_name,
            "current_version": self.installed_version,
            "available_version": self.latest_version,
            "update_flag": common_data.get("avalible_update", 0),
            "installing": self._installing,
        }
        
        if self._installing and self._install_start_time:
            import time
            attributes["install_duration"] = int(time.time() - self._install_start_time)
        
        return attributes

    async def async_install(
        self,
        version: str | None = None,
        backup: bool = False,
        **kwargs,
    ) -> None:
        """Установка обновления прошивки с умной заморозкой."""
        if not self.update_available:
            _LOGGER.warning("Попытка установки обновления когда оно недоступно для %s", self._device_name)
            return
        
        if self._installing:
            _LOGGER.warning("Обновление %s уже выполняется", self._device_name)
            return
        
        # Начинаем процесс установки
        self._installing = True
        self._install_start_time = time.time()
        
        # Немедленно обновляем состояние UI
        self.async_write_ha_state()
        
        try:
            _LOGGER.info("Запуск обновления прошивки %s с версии %s на %s", 
                        self._device_name, self.installed_version, self.latest_version)
            
            # Создаем умную заморозку для флага обновления
            # Сбрасываем флаг сразу, чтобы UI показал что обновление началось
            # self.coordinator.create_common_freeze("avalible_update", 0)
            

            # Обновляем состояние перед отправкой команды
            await self.coordinator.async_request_refresh()
            
            # Отправляем команду обновления
            success = await self.coordinator.send_update_command()
            
            if success:
                _LOGGER.info("Команда обновления прошивки %s отправлена успешно", self._device_name)
                
            
                # Показываем уведомление о начале обновления
                await self._show_update_notification(
                    message=(
                        f"Обновление прошивки {self._device_name} запущено. "
                        f"Устройство может быть недоступно в течение нескольких минут. "
                        f"Обновление с версии {self.installed_version} на {self.latest_version}."
                    ),
                    title="Обновление прошивки iOhouse",
                    notification_id=f"{DOMAIN}_firmware_update_{self.entry.entry_id}",
                )
                
                # Запускаем мониторинг прогресса
                self._progress_task = self.hass.async_create_task(
                    self._monitor_update_progress()
                )
                
            else:
                _LOGGER.error("Ошибка отправки команды обновления прошивки %s", self._device_name)
                await self._handle_update_error("Не удалось отправить команду обновления")
                
        except Exception as err:
            _LOGGER.error("Исключение при обновлении прошивки %s: %s", self._device_name, err)
            await self._handle_update_error(f"Ошибка: {err}")

    async def _monitor_update_progress(self) -> None:
        """Мониторинг прогресса обновления."""
        try:
            # Ждем некоторое время перед первой проверкой
            await asyncio.sleep(30)
            
            max_checks = 10  # Максимум 10 проверок (примерно 5 минут)
            check_interval = 30  # Интервал между проверками 30 секунд
            
            for check_num in range(max_checks):
                _LOGGER.debug("Проверка прогресса обновления %s (%d/%d)", 
                             self._device_name, check_num + 1, max_checks)
                
                # Запрашиваем свежие данные
                await self.coordinator.async_request_refresh()
                
                # Проверяем завершение обновления
                if await self._check_update_completion():
                    return
                
                # Ждем перед следующей проверкой
                if check_num < max_checks - 1:
                    await asyncio.sleep(check_interval)
            
            # Если за отведенное время обновление не завершилось
            _LOGGER.warning("Обновление прошивки %s не завершилось за отведенное время", self._device_name)
            await self._handle_update_timeout()
            
        except asyncio.CancelledError:
            _LOGGER.debug("Мониторинг обновления %s отменен", self._device_name)
        except Exception as err:
            _LOGGER.error("Ошибка мониторинга обновления %s: %s", self._device_name, err)

    async def _check_update_completion(self) -> bool:
        """Проверка завершения обновления."""
        common_data = self.coordinator.get_common_data()
        
        # Проверяем что флаг обновления сброшен
        update_available = common_data.get("avalible_update", 0)
        
        # Проверяем изменение версии прошивки
        current_version = common_data.get("fWversion")
        expected_version = self.latest_version
        
        if update_available == 0:
            # Флаг сброшен - обновление могло завершиться
            if current_version and expected_version:
                try:
                    if str(current_version) == str(expected_version):
                        await self._handle_update_success()
                        return True
                except (ValueError, TypeError):
                    pass
            
            # Даже если версии не совпадают, но флаг сброшен - считаем завершенным
            await self._handle_update_success()
            return True
        
        return False

    async def _handle_update_success(self) -> None:
        """Обработка успешного завершения обновления."""
        self._installing = False
        self._install_start_time = None
        
        # Отменяем задачу мониторинга
        if self._progress_task and not self._progress_task.done():
            self._progress_task.cancel()
        
        # Убираем уведомление о процессе
        await self._dismiss_notification(f"{DOMAIN}_firmware_update_{self.entry.entry_id}")
        
        # Показываем уведомление об успехе
        await self._show_update_notification(
            message=(
                f"Обновление прошивки {self._device_name} завершено успешно! "
                f"Новая версия: {self.installed_version}"
            ),
            title="Обновление iOhouse завершено",
            notification_id=f"{DOMAIN}_firmware_success_{self.entry.entry_id}",
        )
        
        _LOGGER.info("Обновление прошивки %s завершено успешно, новая версия: %s", 
                    self._device_name, self.installed_version)
        
        # Обновляем состояние
        self.async_write_ha_state()

    async def _handle_update_error(self, error_msg: str) -> None:
        """Обработка ошибки обновления."""
        self._installing = False
        self._install_start_time = None
        
        # Отменяем задачу мониторинга
        if self._progress_task and not self._progress_task.done():
            self._progress_task.cancel()
        
        # Убираем уведомление о процессе
        await self._dismiss_notification(f"{DOMAIN}_firmware_update_{self.entry.entry_id}")
        
        # Показываем уведомление об ошибке
        await self._show_update_notification(
            message=(
                f"Ошибка обновления прошивки {self._device_name}: {error_msg}. "
                "Проверьте подключение к устройству и повторите попытку."
            ),
            title="Ошибка обновления iOhouse",
            notification_id=f"{DOMAIN}_firmware_error_{self.entry.entry_id}",
        )
        
        # Обновляем состояние
        self.async_write_ha_state()

    async def _handle_update_timeout(self) -> None:
        """Обработка таймаута обновления."""
        await self._show_update_notification(
            message=(
                f"Обновление прошивки {self._device_name} занимает больше времени чем ожидалось. "
                "Устройство может все еще обновляться. Проверьте статус через несколько минут."
            ),
            title="Обновление iOhouse - долгий процесс",
            notification_id=f"{DOMAIN}_firmware_timeout_{self.entry.entry_id}",
        )
        
        # Не сбрасываем флаг _installing - возможно обновление все еще идет
        _LOGGER.warning("Обновление прошивки %s превысило ожидаемое время", self._device_name)

    async def _show_update_notification(
        self, 
        message: str, 
        title: str, 
        notification_id: str
    ) -> None:
        """Показать уведомление пользователю."""
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": message,
                    "title": title,
                    "notification_id": notification_id,
                }
            )
        except Exception as err:
            _LOGGER.warning("Не удалось показать уведомление: %s", err)

    async def _dismiss_notification(self, notification_id: str) -> None:
        """Убрать уведомление."""
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {
                    "notification_id": notification_id,
                }
            )
        except Exception as err:
            _LOGGER.warning("Не удалось убрать уведомление: %s", err)

    async def async_release_notes(self) -> str | None:
        """Получение заметок о релизе."""
        if not self.update_available and not self._installing:
            return None
        
        current_ver = self.installed_version or "Unknown"
        latest_ver = self.latest_version or "Unknown"
        
        notes = [
            f"iOhouse Firmware Update",
            f"",
            f"Current Version: {current_ver}",
            f"New Version: {latest_ver}",
            f"",
            f"This update will install the latest firmware for your iOhouse Thermozone Controller.",
            f"",
            f"Important notes:",
            f"• The device will be temporarily unavailable during the update process",
            f"• Update process typically takes 2-5 minutes",
            f"• Do not power off the device during the update",
            f"• All settings and configurations will be preserved",
        ]
        
        return "\n".join(notes)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Обработка обновления от координатора."""
        # Если мы в процессе установки, проверяем завершение
        if self._installing:
            # Создаем задачу проверки завершения без ожидания
            self.hass.async_create_task(self._check_update_completion())
        
        super()._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        """Вызывается при удалении сущности."""
        # Отменяем задачу мониторинга если она запущена
        if self._progress_task and not self._progress_task.done():
            self._progress_task.cancel()
        
        # Убираем все уведомления
        for suffix in ["update", "success", "error", "timeout"]:
            await self._dismiss_notification(f"{DOMAIN}_firmware_{suffix}_{self.entry.entry_id}")
        
        await super().async_will_remove_from_hass()