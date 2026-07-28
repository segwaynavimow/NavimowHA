"""Event platform for Navimow integration."""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from mower_sdk.models import MowerError

from .const import DOMAIN, EVENT_NAVIMOW_EVENT
from .coordinator import NavimowCoordinator

KNOWN_EVENT_TYPES: list[str] = [
    error.value for error in MowerError if error is not MowerError.NONE
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Navimow event entities from a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    devices = data["devices"]
    coordinators: dict[str, NavimowCoordinator] = data["coordinators"]
    async_add_entities(
        NavimowEventEntity(coordinators[device.id]) for device in devices
    )


class NavimowEventEntity(CoordinatorEntity[NavimowCoordinator], EventEntity):
    """Exposes mower MQTT events (stuck, lifted, rain, ...) as an event entity."""

    _attr_has_entity_name = True
    _attr_translation_key = "mower_event"
    _attr_event_types = KNOWN_EVENT_TYPES
    # H-series never publishes to the event topic; models that do can enable it.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: NavimowCoordinator) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{DOMAIN}_{device.id}_event"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer="Navimow",
            model=device.model or "Unknown",
            sw_version=device.firmware_version or None,
            serial_number=device.serial_number or device.id,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to the integration's bus events for this device."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_NAVIMOW_EVENT, self.handle_navimow_event)
        )

    @callback
    def handle_navimow_event(self, event: Event) -> None:
        """Record a navimow_event from the bus on this entity."""
        if event.data.get("device_id") != self.coordinator.device.id:
            return
        event_type = event.data.get("event") or "unknown"
        if event_type not in self._attr_event_types:
            event_type = MowerError.UNKNOWN.value
        self._trigger_event(event_type, dict(event.data))
        self.async_write_ha_state()
