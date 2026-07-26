"""Tests for the raw MQTT payload capture."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "navimow"))

from raw_capture import MAX_PAYLOADS_PER_CHANNEL, RawPayloadCapture, attach_raw_capture


def test_record_parses_json_and_groups_by_device_and_channel() -> None:
    capture = RawPayloadCapture()
    capture.record("/downlink/vehicle/dev1/realtimeDate/state", b'{"state": "isDocked"}', "dev1")
    capture.record("/downlink/vehicle/dev1/realtimeDate/event", b'{"event": "stuck"}', "dev1")

    snapshot = capture.snapshot()
    assert len(snapshot) == 1
    channels = snapshot[0]["channels"]
    assert channels["state"][0]["payload"] == {"state": "isDocked"}
    assert channels["event"][0]["payload"] == {"event": "stuck"}


def test_record_keeps_undecodable_payload_as_hex() -> None:
    capture = RawPayloadCapture()
    capture.record("/downlink/vehicle/dev1/realtimeDate/state", b"\xff\xfe", "dev1")
    assert capture.snapshot()[0]["channels"]["state"][0]["payload"] == "fffe"


def test_record_caps_payloads_per_channel() -> None:
    capture = RawPayloadCapture()
    for index in range(MAX_PAYLOADS_PER_CHANNEL + 5):
        capture.record("/downlink/vehicle/dev1/realtimeDate/state", b'{"n": %d}' % index, "dev1")
    bucket = capture.snapshot()[0]["channels"]["state"]
    assert len(bucket) == MAX_PAYLOADS_PER_CHANNEL
    assert bucket[-1]["payload"] == {"n": MAX_PAYLOADS_PER_CHANNEL + 4}


def test_attach_wraps_and_forwards_to_original_handler() -> None:
    received: list[tuple[str, bytes, str]] = []

    async def original_handler(topic: str, payload: bytes, device_id: str) -> None:
        received.append((topic, payload, device_id))

    fake_sdk = SimpleNamespace(_mqtt=SimpleNamespace(on_message=original_handler))
    capture = attach_raw_capture(fake_sdk)

    asyncio.run(fake_sdk._mqtt.on_message("/downlink/vehicle/dev1/realtimeDate/state", b'{"state": "isRunning"}', "dev1"))

    assert received == [("/downlink/vehicle/dev1/realtimeDate/state", b'{"state": "isRunning"}', "dev1")]
    assert capture.snapshot()[0]["channels"]["state"][0]["payload"] == {"state": "isRunning"}


if __name__ == "__main__":
    test_record_parses_json_and_groups_by_device_and_channel()
    test_record_keeps_undecodable_payload_as_hex()
    test_record_caps_payloads_per_channel()
    test_attach_wraps_and_forwards_to_original_handler()
    print("all raw_capture tests passed")
