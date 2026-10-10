"""Diagnostics support for the Navimow integration."""
from __future__ import annotations

import dataclasses
import time
from enum import Enum
from importlib import metadata
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.loader import async_get_integration

from .const import (
    DOMAIN,
    HTTP_FALLBACK_MIN_INTERVAL,
    MQTT_STALE_SECONDS,
    UPDATE_INTERVAL,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceEntry

# Keys stripped from the dump so the output is safe to paste into a GitHub issue.
TO_REDACT = {
    "access_token",
    "refresh_token",
    "token",
    "password",
    "pwdInfo",
    "email",
    "userName",
    "username",
    "serial_number",
    "serialNumber",
    "sn",
    "device_id",
    "deviceId",
    "id",
    "mac",
    "userId",
    "position",
}


def _to_serializable(obj: Any, _seen: set[int] | None = None) -> Any:
    """Best-effort convert SDK dataclasses/objects into redaction-friendly data.

    Guards against reference cycles (``_seen``) so a diagnostics dump can never
    recurse infinitely, and renders bytes as hex rather than a raw ``b'...'``
    repr so the output stays clean and redactable.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        return obj.hex()
    if isinstance(obj, Enum):
        return obj.value
    if _seen is None:
        _seen = set()
    obj_id = id(obj)
    if obj_id in _seen:
        return "**CIRCULAR**"
    seen = _seen | {obj_id}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            field.name: _to_serializable(getattr(obj, field.name), seen)
            for field in dataclasses.fields(obj)
        }
    if isinstance(obj, dict):
        return {str(key): _to_serializable(value, seen) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_serializable(value, seen) for value in obj]
    obj_dict = getattr(obj, "__dict__", None)
    if isinstance(obj_dict, dict):
        return {
            key: _to_serializable(value, seen)
            for key, value in obj_dict.items()
            if not key.startswith("_")
        }
    return str(obj)


def _sdk_version() -> str | None:
    """Return the installed navimow-sdk version, if available."""
    try:
        return metadata.version("navimow-sdk")
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return None


async def _integration_block(hass: HomeAssistant) -> dict[str, Any]:
    """Build the static integration/config section of the report."""
    version: str | None = None
    try:
        integration = await async_get_integration(hass, DOMAIN)
        version = str(integration.version) if integration.version else None
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        version = None
    return {
        "version": version,
        "navimow_sdk_version": _sdk_version(),
        "config": {
            "update_interval": UPDATE_INTERVAL,
            "mqtt_stale_seconds": MQTT_STALE_SECONDS,
            "http_fallback_min_interval": HTTP_FALLBACK_MIN_INTERVAL,
        },
    }


def _coordinator_block(coordinator: Any, now: float) -> dict[str, Any]:
    """Build the per-coordinator section, deriving MQTT/HTTP freshness.

    Reads only the coordinator's public ``data`` snapshot (the ``meta`` dict the
    coordinator already populates) plus the SDK connection flag, so it stays
    decoupled from the coordinator's update logic and from the SDK itself.
    """
    data = getattr(coordinator, "data", None)
    if not isinstance(data, dict):
        data = {}
    meta = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
    last_mqtt = meta.get("last_mqtt_update_monotonic")
    last_http = meta.get("last_http_fetch_monotonic")
    device = getattr(coordinator, "device", None)
    sdk = getattr(coordinator, "sdk", None)
    return {
        "device_id": getattr(device, "id", None),
        "device_model": getattr(device, "model", None),
        "last_data_source": meta.get("last_data_source"),
        "mqtt_age_seconds": round(now - last_mqtt, 1) if last_mqtt is not None else None,
        "http_age_seconds": round(now - last_http, 1) if last_http is not None else None,
        "is_mqtt_stale": last_mqtt is None or (now - last_mqtt) > MQTT_STALE_SECONDS,
        "sdk_connected": getattr(sdk, "is_connected", None),
        "last_state": _to_serializable(data.get("state")),
        "last_attributes": _to_serializable(data.get("attributes")),
    }


def _entry_data(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    return hass.data.get(DOMAIN, {}).get(entry.entry_id, {}) or {}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators = _entry_data(hass, entry).get("coordinators", {}) or {}
    now = time.monotonic()
    diagnostics = {
        "integration": await _integration_block(hass),
        "coordinators": [
            _coordinator_block(coordinator, now)
            for coordinator in coordinators.values()
        ],
    }
    return async_redact_data(diagnostics, TO_REDACT)


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a single device."""
    coordinators = _entry_data(hass, entry).get("coordinators", {}) or {}
    now = time.monotonic()
    device_ids = {
        identifier[1] for identifier in device.identifiers if identifier[0] == DOMAIN
    }
    # Only the coordinators whose device matches the requested device — never
    # fall back to dumping every device under the entry (least privilege).
    selected = [
        coordinator
        for device_id, coordinator in coordinators.items()
        if device_id in device_ids
    ]
    diagnostics = {
        "integration": await _integration_block(hass),
        "coordinators": [
            _coordinator_block(coordinator, now) for coordinator in selected
        ],
    }
    return async_redact_data(diagnostics, TO_REDACT)
