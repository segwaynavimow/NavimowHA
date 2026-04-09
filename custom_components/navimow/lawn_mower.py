"""Lawn mower platform for Navimow integration."""
import logging
from typing import Any

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from mower_sdk.api import MowerAPI
from mower_sdk.models import DeviceStateMessage, MowerCommand

from .const import DOMAIN, MOWER_STATUS_TO_ACTIVITY
from .coordinator import NavimowCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up lawn mower entities from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    api: MowerAPI = data["api"]
    devices = data["devices"]
    coordinators: dict[str, NavimowCoordinator] = data["coordinators"]

    entities = []
    for device in devices:
        entities.append(
            NavimowLawnMower(
                coordinator=coordinators[device.id],
                api=api,
                device_id=device.id,
                device_name=device.name,
                device_info=device,
            )
        )

    async_add_entities(entities)


class NavimowLawnMower(CoordinatorEntity[NavimowCoordinator], LawnMowerEntity):
    """Representation of a Navimow lawn mower."""

    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(
        self,
        coordinator: NavimowCoordinator,
        api: MowerAPI,
        device_id: str,
        device_name: str,
        device_info: Any,
    ) -> None:
        """Initialize the lawn mower entity."""
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._device_name = device_name
        self._device_info = device_info

        # 设置实体属性
        self._attr_name = device_name
        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="Navimow",
            model=device_info.model or "Unknown",
            sw_version=device_info.firmware_version or None,
            serial_number=device_info.serial_number or self._device_id,
        )

    @property
    def available(self) -> bool:
        """Keep entity available as long as cached state exists.

        Broker-initiated MQTT disconnects (with paho auto-reconnect) are
        transient; the entity should not flip to unavailable during the
        brief reconnection window.
        """
        if self.coordinator.get_device_state() is not None:
            return True
        return super().available

    @property
    def activity(self) -> LawnMowerActivity:
        """Return the current activity of the lawn mower."""
        state = self.coordinator.get_device_state()
        if not state:
            return None
        activity = MOWER_STATUS_TO_ACTIVITY.get(state.state)
        if activity is None:
            return None
        return LawnMowerActivity(activity)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        state: DeviceStateMessage | None = self.coordinator.get_device_state()
        attrs = self.coordinator.get_device_attributes()
        if not state:
            return {}
        attributes: dict[str, Any] = {
            "battery": state.battery,
            "status": state.state,
        }
        if state.signal_strength is not None:
            attributes["signal_strength"] = state.signal_strength
        if state.position:
            attributes["position"] = state.position
        if state.error:
            attributes["error"] = state.error
        if state.metrics:
            attributes["metrics"] = state.metrics
        if attrs:
            attributes["attributes"] = attrs.attributes
        return attributes

    async def _async_send_command(self, command: MowerCommand, label: str) -> None:
        """发送指令前先刷新 token，避免 token 过期导致 CODE_OAUTH_INFO_ILLEGAL。"""
        await self.coordinator._async_ensure_valid_token()
        await self._api.async_send_command(self._device_id, command)
        _LOGGER.info("%s for device %s", label, self._device_id)
        await self.coordinator.async_request_refresh()

    async def async_start_mowing(self) -> None:
        """Start mowing."""
        try:
            await self._async_send_command(MowerCommand.START, "Started mowing")
        except Exception as err:
            _LOGGER.error(
                "Failed to start mowing for device %s: %s", self._device_id, err
            )
            raise

    async def async_pause(self) -> None:
        """Pause mowing."""
        try:
            await self._async_send_command(MowerCommand.PAUSE, "Paused mowing")
        except Exception as err:
            _LOGGER.error(
                "Failed to pause mowing for device %s: %s", self._device_id, err
            )
            raise

    async def async_dock(self) -> None:
        """Dock the mower."""
        try:
            await self._async_send_command(MowerCommand.DOCK, "Docked")
        except Exception as err:
            _LOGGER.error("Failed to dock device %s: %s", self._device_id, err)
            raise

    async def async_resume(self) -> None:
        """Resume mowing."""
        try:
            await self._async_send_command(MowerCommand.RESUME, "Resumed mowing")
        except Exception as err:
            _LOGGER.error(
                "Failed to resume mowing for device %s: %s", self._device_id, err
            )
            raise
