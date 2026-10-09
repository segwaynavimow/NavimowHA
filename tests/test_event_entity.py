"""Tests for the Navimow event entity."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from homeassistant.core import Event
from navimow_loader import load_module

event_module = load_module("event")


def make_entity():
    device = SimpleNamespace(
        id="dev1",
        name="Zoliapjove",
        model="H230E",
        firmware_version="1.0",
        serial_number="SN1",
    )
    coordinator = SimpleNamespace(device=device)
    entity = event_module.NavimowEventEntity(coordinator)
    entity.async_write_ha_state = lambda: None
    return entity


def test_known_event_types_cover_sdk_errors() -> None:
    assert "stuck" in event_module.KNOWN_EVENT_TYPES
    assert "rain" in event_module.KNOWN_EVENT_TYPES
    assert "unknown" in event_module.KNOWN_EVENT_TYPES
    assert "none" not in event_module.KNOWN_EVENT_TYPES


def test_known_event_passes_through() -> None:
    entity = make_entity()
    triggered: list = []
    entity._trigger_event = lambda event_type, data: triggered.append((event_type, data))

    entity.handle_navimow_event(
        Event("navimow_event", {"device_id": "dev1", "event": "stuck", "level": "error"})
    )

    assert triggered == [("stuck", {"device_id": "dev1", "event": "stuck", "level": "error"})]


def test_unrecognized_event_maps_to_unknown() -> None:
    entity = make_entity()
    triggered: list = []
    entity._trigger_event = lambda event_type, data: triggered.append((event_type, data))

    entity.handle_navimow_event(
        Event("navimow_event", {"device_id": "dev1", "event": "firmware_hiccup"})
    )

    assert triggered[0][0] == "unknown"
    assert triggered[0][1]["event"] == "firmware_hiccup"


def test_event_for_other_device_is_ignored() -> None:
    entity = make_entity()
    triggered: list = []
    entity._trigger_event = lambda event_type, data: triggered.append((event_type, data))

    entity.handle_navimow_event(
        Event("navimow_event", {"device_id": "someone-else", "event": "stuck"})
    )

    assert triggered == []


def test_real_trigger_accepts_every_declared_type() -> None:
    entity = make_entity()
    for event_type in event_module.KNOWN_EVENT_TYPES:
        entity.handle_navimow_event(
            Event("navimow_event", {"device_id": "dev1", "event": event_type})
        )
    assert entity.state is not None
