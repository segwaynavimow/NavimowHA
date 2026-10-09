"""Tests for the coordinator's MQTT event handling."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mower_sdk.models import DeviceEventMessage
from navimow_loader import load_module

coordinator_module = load_module("coordinator")


def make_coordinator(fired: list, updated: list):
    coordinator = coordinator_module.NavimowCoordinator.__new__(
        coordinator_module.NavimowCoordinator
    )
    coordinator.device = SimpleNamespace(id="dev1", name="Zoliapjove")
    coordinator._last_state = None
    coordinator._last_attributes = None
    coordinator._last_event = None
    coordinator._last_http_status = None
    coordinator._last_mqtt_update = None
    coordinator._last_mqtt_state_update = None
    coordinator._last_http_fetch = None
    coordinator._last_data_source = None
    coordinator.hass = SimpleNamespace(
        loop=SimpleNamespace(call_soon_threadsafe=lambda callback, *args: callback(*args)),
        bus=SimpleNamespace(async_fire=lambda name, data: fired.append((name, data))),
    )
    coordinator.async_set_updated_data = lambda data: updated.append(data)
    return coordinator


def make_event(device_id: str = "dev1") -> DeviceEventMessage:
    return DeviceEventMessage.from_dict(
        {"device_id": device_id, "type": "alert", "event": "stuck", "level": "error", "message": "Wheel stuck"}
    )


def test_event_fires_on_ha_bus_and_updates_data() -> None:
    fired: list = []
    updated: list = []
    coordinator = make_coordinator(fired, updated)

    coordinator._handle_event(make_event())

    assert len(fired) == 1
    event_name, payload = fired[0]
    assert event_name == coordinator_module.EVENT_NAVIMOW_EVENT
    assert payload["device_id"] == "dev1"
    assert payload["device_name"] == "Zoliapjove"
    assert payload["event"] == "stuck"
    assert payload["level"] == "error"

    assert len(updated) == 1
    assert updated[0]["event"].event == "stuck"
    assert coordinator._last_mqtt_update is not None


def test_event_for_other_device_is_ignored() -> None:
    fired: list = []
    updated: list = []
    coordinator = make_coordinator(fired, updated)

    coordinator._handle_event(make_event(device_id="other-device"))

    assert fired == []
    assert updated == []
    assert coordinator._last_mqtt_update is None
