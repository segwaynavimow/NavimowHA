"""Sensor platform for Navimow integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from mower_sdk.models import DeviceStateMessage, MowerStatus

from .const import DOMAIN
from .coordinator import NavimowCoordinator


@dataclass(frozen=True, kw_only=True)
class NavimowSensorEntityDescription(SensorEntityDescription):
    """Describes Navimow sensor entity."""

    value_fn: Callable[[NavimowCoordinator], Any]
    attributes_fn: Callable[[NavimowCoordinator], dict[str, Any] | None] | None = None


def state_battery(coordinator: NavimowCoordinator) -> int | None:
    """Return battery percentage from the latest state message."""
    state = coordinator.get_device_state()
    return state.battery if state else None


AT_BASE_STATES = (MowerStatus.DOCKED.value, MowerStatus.IDLE.value)


def docked_status(state: DeviceStateMessage) -> str:
    """Split at-base states into charging/idle using battery level.

    While parked, H230 firmware flaps between isDocked and isIdle every few
    ticks, so the cloud state cannot distinguish "still charging" from
    "program finished". Battery level can: below 100% the mower is charging,
    at 100% with nothing left to resume it idles.
    """
    if state.battery is None:
        return MowerStatus.DOCKED.value
    if state.battery < 100:
        return MowerStatus.CHARGING.value
    return MowerStatus.IDLE.value


def state_status(coordinator: NavimowCoordinator) -> str | None:
    """Return the mower status, with at-base states refined into charging or idle."""
    state = coordinator.get_device_state()
    if not state:
        return None
    if state.state in AT_BASE_STATES:
        return docked_status(state)
    return state.state


def state_status_attributes(coordinator: NavimowCoordinator) -> dict[str, Any] | None:
    """Return raw state and metrics as attributes of the status sensor."""
    state = coordinator.get_device_state()
    return dict(state.metrics) if state and state.metrics else None


def state_signal_strength(coordinator: NavimowCoordinator) -> int | None:
    """Return signal strength from the latest state message."""
    state = coordinator.get_device_state()
    return state.signal_strength if state else None


def state_error(coordinator: NavimowCoordinator) -> str | None:
    """Return the current error code, or 'none' when the mower reports no error."""
    state = coordinator.get_device_state()
    if not state:
        return None
    return state.error.get("code", "unknown") if state.error else "none"


def state_error_attributes(coordinator: NavimowCoordinator) -> dict[str, Any] | None:
    """Return the full error payload as attributes of the error sensor."""
    state = coordinator.get_device_state()
    return dict(state.error) if state and state.error else None


def last_event(coordinator: NavimowCoordinator) -> str | None:
    """Return the name of the most recent MQTT event."""
    event = coordinator.get_last_event()
    return event.event if event else None


def last_event_attributes(coordinator: NavimowCoordinator) -> dict[str, Any] | None:
    """Return the full event payload as attributes of the event sensor."""
    event = coordinator.get_last_event()
    return event.to_dict() if event else None


def http_mowing_time(coordinator: NavimowCoordinator) -> int | None:
    """Return the current mowing session duration reported over HTTP."""
    status = coordinator.get_http_status()
    return status.mowing_time if status else None


def http_total_mowing_time(coordinator: NavimowCoordinator) -> int | None:
    """Return the lifetime mowing duration reported over HTTP."""
    status = coordinator.get_http_status()
    return status.total_mowing_time if status else None


def http_status_extra(coordinator: NavimowCoordinator) -> dict[str, Any] | None:
    """Return unparsed HTTP payload fields kept in DeviceStatus.extra."""
    status = coordinator.get_http_status()
    return dict(status.extra) if status and status.extra else None


SENSOR_DESCRIPTIONS: tuple[NavimowSensorEntityDescription, ...] = (
    NavimowSensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=state_battery,
    ),
    NavimowSensorEntityDescription(
        key="status",
        translation_key="status",
        value_fn=state_status,
        attributes_fn=state_status_attributes,
    ),
    NavimowSensorEntityDescription(
        key="signal_strength",
        translation_key="signal_strength",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=state_signal_strength,
    ),
    NavimowSensorEntityDescription(
        key="error",
        translation_key="error",
        value_fn=state_error,
        attributes_fn=state_error_attributes,
    ),
    NavimowSensorEntityDescription(
        key="last_event",
        translation_key="last_event",
        entity_registry_enabled_default=False,
        value_fn=last_event,
        attributes_fn=last_event_attributes,
    ),
    NavimowSensorEntityDescription(
        key="mowing_time",
        translation_key="mowing_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=http_mowing_time,
        attributes_fn=http_status_extra,
    ),
    NavimowSensorEntityDescription(
        key="total_mowing_time",
        translation_key="total_mowing_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=http_total_mowing_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navimow sensors from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    devices = data["devices"]
    coordinators: dict[str, NavimowCoordinator] = data["coordinators"]

    entities: list[NavimowSensor] = []
    for device in devices:
        coordinator = coordinators[device.id]
        for description in SENSOR_DESCRIPTIONS:
            entities.append(
                NavimowSensor(
                    coordinator=coordinator,
                    entity_description=description,
                )
            )
    async_add_entities(entities)


class NavimowSensor(CoordinatorEntity[NavimowCoordinator], SensorEntity):
    """Representation of a Navimow sensor."""

    entity_description: NavimowSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NavimowCoordinator,
        entity_description: NavimowSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = entity_description

        device = coordinator.device
        self._attr_unique_id = f"{DOMAIN}_{device.id}_{entity_description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer="Navimow",
            model=device.model or "Unknown",
            sw_version=device.firmware_version or None,
            serial_number=device.serial_number or device.id,
        )

    @property
    def available(self) -> bool:
        if self.coordinator.get_device_state() is not None:
            return True
        return super().available

    @property
    def native_value(self) -> Any:
        """Return sensor value from coordinator."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes from coordinator, if the description defines any."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator)
