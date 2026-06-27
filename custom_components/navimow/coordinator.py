"""DataUpdateCoordinator for Navimow integration."""
import json
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from mower_sdk.api import MowerAPI
from mower_sdk.models import (
    Device,
    DeviceAttributesMessage,
    DeviceEventMessage,
    DeviceStateMessage,
    DeviceStatus,
)
from mower_sdk.sdk import NavimowSDK

from .const import (
    CONF_ZONE_NAMES,
    DEFAULT_ZONE_NAMES,
    DATA_UNAVAILABLE_SECONDS,
    DOMAIN,
    HTTP_FALLBACK_MIN_INTERVAL,
    MQTT_STALE_SECONDS,
    UPDATE_INTERVAL,
)
from .location import location_topic, position_topic
from .position import position_dict

_LOGGER = logging.getLogger(__name__)


class NavimowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Navimow data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        sdk: NavimowSDK,
        api: MowerAPI,
        device: Device,
        config_entry: ConfigEntry,
        oauth_session: config_entry_oauth2_flow.OAuth2Session | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.sdk = sdk
        self.api = api
        self.device = device
        self.config_entry = config_entry
        self.oauth_session = oauth_session
        self.data: dict[str, Any] = {}
        self._last_state: DeviceStateMessage | None = None
        self._last_attributes: DeviceAttributesMessage | None = None
        self._last_event: DeviceEventMessage | None = None
        self._last_location: dict[str, Any] | None = None
        self._last_position: dict[str, float] | None = None
        self._last_mqtt_update: float | None = None
        self._last_mqtt_state_update: float | None = None
        self._last_http_fetch: float | None = None
        self._last_data_source: str | None = None
        self._last_location_topic: str | None = None
        self._last_position_topic: str | None = None
        self._last_raw_state_message: dict[str, Any] | None = None
        self._last_raw_attributes_message: dict[str, Any] | None = None
        self._last_raw_event_message: dict[str, Any] | None = None
        self._last_raw_position_payload: Any = None

    async def async_setup(self) -> None:
        """Register callbacks from SDK."""
        self.sdk.on_state(self._handle_state)
        self.sdk.on_event(self._handle_event)
        self.sdk.on_attributes(self._handle_attributes)

    def _build_data(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "state": self._last_state,
            "attributes": self._last_attributes,
            "event": self._last_event,
            "location": self._last_location,
            "meta": {
                "last_data_source": self._last_data_source,
                "last_mqtt_update_monotonic": self._last_mqtt_update,
                "last_mqtt_state_update_monotonic": self._last_mqtt_state_update,
                "last_http_fetch_monotonic": self._last_http_fetch,
                "last_location_topic": self._last_location_topic,
                "last_position_topic": self._last_position_topic,
            },
            "debug": {
                "expected_location_topic": location_topic(self.device.id),
                "expected_position_topic": position_topic(self.device.id),
                "raw_state_message": self._last_raw_state_message,
                "raw_attributes_message": self._last_raw_attributes_message,
                "raw_event_message": self._last_raw_event_message,
                "raw_location_payload": (
                    self._last_location.get("raw_payload") if self._last_location else None
                ),
                "raw_position_payload": self._last_raw_position_payload,
                "last_location_payload_types": (
                    self._last_location.get("payload_types") if self._last_location else None
                ),
                "last_unknown_location_items": (
                    self._last_location.get("unknown_items") if self._last_location else None
                ),
            },
        }

    def _device_status_to_state(self, status: DeviceStatus) -> DeviceStateMessage:
        error: dict[str, Any] | None = None
        if status.error_code and status.error_code.value != "none":
            error = {
                "code": status.error_code.value,
                "message": status.error_message,
            }
        return DeviceStateMessage(
            device_id=status.device_id,
            timestamp=status.timestamp,
            state=status.status.value,
            battery=status.battery,
            signal_strength=status.signal_strength,
            position=status.position,
            error=error,
            metrics=None,
        )

    async def _async_ensure_valid_token(self) -> str | None:
        if not self.oauth_session:
            return None
        try:
            token: dict[str, Any] | None
            if hasattr(self.oauth_session, "async_ensure_token_valid"):
                await self.oauth_session.async_ensure_token_valid()
                token = self.oauth_session.token
            elif hasattr(self.oauth_session, "async_get_valid_token"):
                token = await self.oauth_session.async_get_valid_token()
            else:
                token = self.oauth_session.token
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.warning(
                "Token refresh failed (likely transient), falling back to cached token: %s", err
            )
            cached = getattr(self.oauth_session, "token", None)
            if cached and cached.get("access_token"):
                token = cached
            else:
                raise ConfigEntryAuthFailed(
                    f"Token refresh failed and no cached token available: {err}"
                ) from err
        if not token or not token.get("access_token"):
            raise ConfigEntryAuthFailed("No access token after refresh")
        access_token = token["access_token"]
        self.api.set_token(access_token)
        return access_token

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self._async_ensure_valid_token()
        except ConfigEntryAuthFailed:
            raise

        cached_state = self.sdk.get_cached_state(self.device.id)
        if cached_state is not None:
            self._last_state = self._state_with_known_position(cached_state)
            self._last_raw_state_message = _serialize_debug_value(cached_state)
            self._last_data_source = "mqtt_cache"

        cached_attrs = self.sdk.get_cached_attributes(self.device.id)
        if cached_attrs is not None:
            self._last_attributes = cached_attrs
            self._last_raw_attributes_message = _serialize_debug_value(cached_attrs)

        now = time.monotonic()
        is_state_stale = (
            self._last_mqtt_state_update is None
            or now - self._last_mqtt_state_update > MQTT_STALE_SECONDS
        )
        can_http_fetch = (
            self._last_http_fetch is None
            or now - self._last_http_fetch > HTTP_FALLBACK_MIN_INTERVAL
        )
        if is_state_stale and can_http_fetch:
            try:
                status = await self.api.async_get_device_status(self.device.id)
                _LOGGER.debug(
                    "HTTP fallback success: device=%s battery=%s status=%s",
                    self.device.id,
                    status.battery,
                    status.status.value if status.status else "unknown",
                )
                fallback_state = self._device_status_to_state(status)
                self._last_state = self._state_with_known_position(fallback_state)
                self._last_raw_state_message = _serialize_debug_value(fallback_state)
                self._last_http_fetch = now
                self._last_data_source = "http_fallback"
                self.data = self._build_data()
                self.async_set_updated_data(self.data)
            except ConfigEntryAuthFailed:
                raise
            except Exception as err:
                _LOGGER.warning(
                    "HTTP fallback failed for device %s: %s", self.device.id, err
                )

        _LOGGER.debug(
            "Coordinator update: device=%s source=%s mqtt_ts=%s mqtt_state_ts=%s http_ts=%s",
            self.device.id,
            self._last_data_source,
            self._last_mqtt_update,
            self._last_mqtt_state_update,
            self._last_http_fetch,
        )

        last_success = max(
            (ts for ts in (self._last_mqtt_update, self._last_http_fetch) if ts is not None),
            default=None,
        )
        if last_success is None or now - last_success > DATA_UNAVAILABLE_SECONDS:
            raise UpdateFailed(
                f"No data received for device {self.device.id} via MQTT or HTTP "
                f"in over {DATA_UNAVAILABLE_SECONDS} seconds"
            )

        self.data = self._build_data()
        return self.data

    def _handle_state(self, state: DeviceStateMessage) -> None:
        if state.device_id != self.device.id:
            return
        _LOGGER.debug(
            "MQTT state received: device=%s state=%s battery=%s",
            state.device_id,
            state.state,
            state.battery,
        )
        now = time.monotonic()
        self._last_mqtt_update = now
        self._last_mqtt_state_update = now
        self._last_data_source = "mqtt_push"
        self.hass.loop.call_soon_threadsafe(
            self._update_from_state, self._state_with_known_position(state)
        )

    def _handle_event(self, event: DeviceEventMessage) -> None:
        if event.device_id != self.device.id:
            return
        _LOGGER.debug(
            "MQTT event received: device=%s type=%s event=%s",
            event.device_id,
            event.type,
            event.event,
        )
        self._last_mqtt_update = time.monotonic()
        self._last_data_source = "mqtt_push"
        self.hass.loop.call_soon_threadsafe(self._update_from_event, event)

    def _handle_attributes(self, attrs: DeviceAttributesMessage) -> None:
        if attrs.device_id != self.device.id:
            return
        _LOGGER.debug(
            "MQTT attributes received: device=%s",
            attrs.device_id,
        )
        self._last_mqtt_update = time.monotonic()
        self.hass.loop.call_soon_threadsafe(self._update_from_attributes, attrs)

    def _update_from_state(self, state: DeviceStateMessage) -> None:
        self._last_state = self._state_with_known_position(state)
        self._last_raw_state_message = _serialize_debug_value(state)
        self._last_data_source = "mqtt_push"
        self.async_set_updated_data(self._build_data())

    def _update_from_event(self, event: DeviceEventMessage) -> None:
        self._last_event = event
        self._last_raw_event_message = _serialize_debug_value(event)
        self.async_set_updated_data(self._build_data())

    def _update_from_attributes(self, attrs: DeviceAttributesMessage) -> None:
        self._last_attributes = attrs
        self._last_raw_attributes_message = _serialize_debug_value(attrs)
        self.async_set_updated_data(self._build_data())

    def ingest_location(
        self, location: dict[str, Any], topic: str | None = None
    ) -> None:
        """Store decoded realtime location updates."""
        if location.get("device_id") not in (None, self.device.id):
            return
        self._last_location = location
        self._last_location_topic = topic
        self._last_mqtt_update = time.monotonic()
        self._last_data_source = "mqtt_location"
        self.async_set_updated_data(self._build_data())

    def ingest_position(self, payload: Any, topic: str | None = None) -> bool:
        """Merge realtime position updates into the cached state."""
        normalized_position = position_dict(payload)
        if normalized_position is None:
            return False

        self._last_raw_position_payload = _serialize_debug_value(payload)
        self._last_position = normalized_position
        self._last_position_topic = topic
        self._last_mqtt_update = time.monotonic()
        self._last_data_source = "mqtt_position"

        state = self._last_state
        if state is None:
            state = DeviceStateMessage(
                device_id=self.device.id,
                timestamp=None,
                state="unknown",
                battery=None,
                signal_strength=None,
                position=normalized_position,
                error=None,
                metrics=None,
            )
        else:
            state = DeviceStateMessage(
                device_id=state.device_id,
                timestamp=state.timestamp,
                state=state.state,
                battery=state.battery,
                signal_strength=state.signal_strength,
                position=normalized_position,
                error=state.error,
                metrics=state.metrics,
            )

        self._last_state = state
        self.async_set_updated_data(self._build_data())
        return True

    def _state_with_known_position(
        self, state: DeviceStateMessage
    ) -> DeviceStateMessage:
        normalized_position = position_dict(state.position)
        if normalized_position is not None:
            self._last_position = normalized_position
            if state.position == normalized_position:
                return state
            return DeviceStateMessage(
                device_id=state.device_id,
                timestamp=state.timestamp,
                state=state.state,
                battery=state.battery,
                signal_strength=state.signal_strength,
                position=normalized_position,
                error=state.error,
                metrics=state.metrics,
            )

        if self._last_position is None:
            return state

        return DeviceStateMessage(
            device_id=state.device_id,
            timestamp=state.timestamp,
            state=state.state,
            battery=state.battery,
            signal_strength=state.signal_strength,
            position=self._last_position,
            error=state.error,
            metrics=state.metrics,
        )

    def _zone_names(self) -> dict[str, str]:
        raw = self.config_entry.options.get(CONF_ZONE_NAMES, DEFAULT_ZONE_NAMES)
        if not isinstance(raw, str) or not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(key): str(value) for key, value in parsed.items()}

    def get_zone_label(self) -> str | None:
        location = self.get_device_location()
        if not location:
            return None
        partition = location.get("partition")
        if partition is None:
            return None
        return self._zone_names().get(str(partition), f"Zone {partition}")

    def get_vehicle_state_label(self) -> str | None:
        location = self.get_device_location()
        if not location or location.get("vehicle_state") is None:
            return None
        raw_value = location.get("vehicle_state")
        state = self.get_device_state()
        if state and state.state:
            return f"{state.state} ({raw_value})"
        return f"state_{raw_value}"

    def get_raw_state(self) -> str | None:
        state = self.get_device_state()
        if not state or not state.metrics or not isinstance(state.metrics, dict):
            return None
        raw_state = state.metrics.get("raw_state")
        if raw_state is None:
            return None
        return str(raw_state)

    def get_operating_mode(self) -> str | None:
        raw_state = self.get_raw_state()
        if raw_state:
            return raw_state
        state = self.get_device_state()
        return state.state if state else None

    def is_mapping_mode(self) -> bool:
        return self.get_raw_state() == "isMapping"

    def get_device_state(self) -> DeviceStateMessage | None:
        return self.data.get("state")

    def get_device_event(self) -> DeviceEventMessage | None:
        return self.data.get("event")

    def get_device_attributes(self) -> DeviceAttributesMessage | None:
        return self.data.get("attributes")

    def get_device_info(self) -> Any | None:
        return self.data.get("device")

    def get_device_location(self) -> dict[str, Any] | None:
        return self.data.get("location")

    def get_device_meta(self) -> dict[str, Any]:
        return self.data.get("meta", {})

    def get_device_debug(self) -> dict[str, Any]:
        return self.data.get("debug", {})


def _serialize_debug_value(value: Any) -> Any:
    """Convert SDK messages and payloads into telemetry-friendly data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _serialize_debug_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_debug_value(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            key: _serialize_debug_value(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)
