"""Rolling capture of raw MQTT payloads.

The SDK parsers drop any JSON key they do not recognize, so this hook records
the last few undecoded payloads per device and channel. The capture is exposed
through the diagnostics download, making it possible to see everything the
Segway cloud actually publishes for a device.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mower_sdk.sdk import NavimowSDK

_LOGGER = logging.getLogger(__name__)

MAX_PAYLOADS_PER_CHANNEL = 10


class RawPayloadCapture:
    """Keeps the last few raw MQTT payloads per device and channel."""

    def __init__(self) -> None:
        self.devices: dict[str, dict[str, deque[dict[str, Any]]]] = {}

    def record(self, topic: str, payload: bytes, device_id: str) -> None:
        """Store one raw payload under its device and topic channel."""
        try:
            decoded: Any = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = payload.hex()
        channel = topic.rsplit("/", 1)[-1]
        channels = self.devices.setdefault(device_id, {})
        bucket = channels.setdefault(channel, deque(maxlen=MAX_PAYLOADS_PER_CHANNEL))
        bucket.append({"received_at": time.time(), "payload": decoded})
        _LOGGER.debug("Raw MQTT payload on %s: %s", topic, decoded)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a diagnostics-friendly copy of all captured payloads."""
        return [
            {"device_id": device_id, "channels": {channel: list(bucket) for channel, bucket in channels.items()}}
            for device_id, channels in self.devices.items()
        ]


def attach_raw_capture(sdk: NavimowSDK) -> RawPayloadCapture:
    """Wrap the SDK's MQTT message hook so every raw payload is captured first."""
    capture = RawPayloadCapture()
    # ponytail: reaches into sdk._mqtt because the SDK offers no raw-payload hook;
    # revisit if navimow-sdk ever exposes one.
    original_handler = sdk._mqtt.on_message

    async def capture_and_forward(topic: str, payload: bytes, device_id: str) -> None:
        capture.record(topic, payload, device_id)
        if original_handler is not None:
            await original_handler(topic, payload, device_id)

    sdk._mqtt.on_message = capture_and_forward
    return capture
