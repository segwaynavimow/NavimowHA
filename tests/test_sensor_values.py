"""Tests for the sensor platform value and attribute functions."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mower_sdk.models import (
    DeviceEventMessage,
    DeviceStateMessage,
    DeviceStatus,
    MowerStatus,
)
from navimow_loader import load_module

sensor = load_module("sensor")


def make_coordinator(state=None, event=None, http_status=None) -> SimpleNamespace:
    return SimpleNamespace(
        get_device_state=lambda: state,
        get_last_event=lambda: event,
        get_http_status=lambda: http_status,
    )


def make_state(**overrides) -> DeviceStateMessage:
    payload = {
        "device_id": "dev1",
        "state": "isRunning",
        "battery": 77,
        "signal_strength": 3,
        "metrics": {"area_done": 12},
    }
    payload.update(overrides)
    return DeviceStateMessage.from_dict(payload)


def test_state_values_from_mqtt_payload() -> None:
    coordinator = make_coordinator(state=make_state())
    assert sensor.state_battery(coordinator) == 77
    assert sensor.state_status(coordinator) == "mowing"
    assert sensor.state_signal_strength(coordinator) == 3
    attributes = sensor.state_status_attributes(coordinator)
    assert attributes["raw_state"] == "isRunning"
    assert attributes["area_done"] == 12


def test_values_are_none_without_state() -> None:
    coordinator = make_coordinator()
    assert sensor.state_battery(coordinator) is None
    assert sensor.state_status(coordinator) is None
    assert sensor.state_signal_strength(coordinator) is None
    assert sensor.state_status_attributes(coordinator) is None
    assert sensor.state_error(coordinator) is None
    assert sensor.last_event(coordinator) is None
    assert sensor.http_mowing_time(coordinator) is None


def test_status_docked_splits_into_charging_and_idle() -> None:
    charging = make_state(state="isDocked", battery=93)
    assert sensor.state_status(make_coordinator(state=charging)) == "charging"
    full = make_state(state="isDocked", battery=100)
    assert sensor.state_status(make_coordinator(state=full)) == "idle"


def test_status_cloud_idle_flicker_is_folded_into_derivation() -> None:
    flicker = make_state(state="isIdle", battery=93)
    assert sensor.state_status(make_coordinator(state=flicker)) == "charging"
    full = make_state(state="isIdle", battery=100)
    assert sensor.state_status(make_coordinator(state=full)) == "idle"


def test_error_reports_none_when_mower_is_healthy() -> None:
    coordinator = make_coordinator(state=make_state())
    assert sensor.state_error(coordinator) == "none"
    assert sensor.state_error_attributes(coordinator) is None


def test_error_reports_code_and_payload() -> None:
    state = make_state(error={"code": "stuck", "message": "Wheel stuck"})
    coordinator = make_coordinator(state=state)
    assert sensor.state_error(coordinator) == "stuck"
    assert sensor.state_error_attributes(coordinator) == {"code": "stuck", "message": "Wheel stuck"}


def test_last_event_name_and_payload() -> None:
    event = DeviceEventMessage.from_dict(
        {"device_id": "dev1", "type": "alert", "event": "rain", "level": "warning", "message": "Rain delay"}
    )
    coordinator = make_coordinator(event=event)
    assert sensor.last_event(coordinator) == "rain"
    attributes = sensor.last_event_attributes(coordinator)
    assert attributes["event"] == "rain"
    assert attributes["level"] == "warning"


def test_http_status_durations_and_extra() -> None:
    status = DeviceStatus(
        device_id="dev1",
        status=MowerStatus.MOWING,
        battery=77,
        mowing_time=1200,
        total_mowing_time=340000,
        extra={"vehicleState": "isRunning"},
    )
    coordinator = make_coordinator(http_status=status)
    assert sensor.http_mowing_time(coordinator) == 1200
    assert sensor.http_total_mowing_time(coordinator) == 340000
    assert sensor.http_status_extra(coordinator) == {"vehicleState": "isRunning"}


def test_every_description_has_unique_key() -> None:
    keys = [description.key for description in sensor.SENSOR_DESCRIPTIONS]
    assert len(keys) == len(set(keys))
