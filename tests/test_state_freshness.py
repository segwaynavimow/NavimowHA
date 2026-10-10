"""State ordering regressions using real HA entities and SDK message parsing."""

import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.components.lawn_mower import LawnMowerActivity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import frame
from mower_sdk.models import Device, DeviceStateMessage, DeviceStatus, MowerCommand, MowerStatus
from mower_sdk.sdk import NavimowSDK

from custom_components.navimow import coordinator as coordinator_module
from custom_components.navimow.coordinator import NavimowCoordinator
from custom_components.navimow.lawn_mower import NavimowLawnMower
from custom_components.navimow.sensor import SENSOR_DESCRIPTIONS, NavimowSensor


class StateFreshnessTest(unittest.IsolatedAsyncioTestCase):
    """Exercise local updates without connecting to cloud or a mower."""

    async def asyncSetUp(self):
        self.config_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.config_dir.cleanup)
        self.hass = HomeAssistant(self.config_dir.name)
        frame.async_setup(self.hass)
        self.now = 1000.0
        self.clock = patch.object(
            coordinator_module, "time", SimpleNamespace(monotonic=lambda: self.now)
        )
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.device = Device("test-device", "Test mower", "test-model", "test-fw", "test-sn")
        # Keep the SDK's actual cache, parser and callback dispatch, without its
        # network constructor. No broker or cloud requests are made by tests.
        self.sdk = NavimowSDK.__new__(NavimowSDK)
        self.sdk._state_cache = {}
        self.sdk._attributes_cache = {}
        self.sdk._state_callbacks = []
        self.sdk._attributes_callbacks = []
        self.sdk._event_callbacks = []
        self.api = Mock()
        self.api.async_get_device_status = AsyncMock(return_value=self.status(80))
        self.api.async_send_command = AsyncMock()
        self.coordinator = NavimowCoordinator(self.hass, self.sdk, self.api, self.device)
        await self.coordinator.async_setup()
        self.mower = NavimowLawnMower(
            self.coordinator, self.api, self.device.id, self.device.name, self.device
        )
        self.battery = NavimowSensor(self.coordinator, SENSOR_DESCRIPTIONS[0])

    def status(self, battery, state=MowerStatus.MOWING):
        return DeviceStatus(self.device.id, state, battery)

    def seed_old_cache(self):
        self.sdk._state_cache[self.device.id] = DeviceStateMessage(
            self.device.id, None, "docked", 15
        )

    async def push(self, channel, payload, device_id="test-device"):
        await self.sdk._on_mqtt_message(
            f"/downlink/vehicle/{device_id}/realtimeDate/{channel}",
            json.dumps(payload).encode(),
            device_id,
        )
        await asyncio.sleep(0)  # Apply the SDK callback on HA's event loop.

    async def refresh(self):
        return await self.coordinator._async_update_data()

    def assert_display(self, battery, activity=LawnMowerActivity.MOWING):
        self.assertEqual(self.battery.native_value, battery)
        self.assertEqual(self.mower.activity, activity)
        self.assertEqual(self.mower.extra_state_attributes["battery"], battery)

    async def test_http_battery_and_activity_survive_repeated_ticks(self):
        """Bug-51087: 80% must not roll back to the unchanged 15% cache."""
        self.seed_old_cache()
        await self.refresh()
        self.assert_display(80)
        for tick in (1030, 1060, 1090, 1120):
            self.now = tick
            await self.refresh()
            self.assert_display(80)
            self.assertEqual(self.coordinator.data["meta"]["last_data_source"], "http_fallback")
        self.assertEqual(self.api.async_get_device_status.await_count, 2)

    async def test_http_failure_retains_last_good_state(self):
        self.seed_old_cache()
        await self.refresh()
        self.api.async_get_device_status.side_effect = TimeoutError("synthetic timeout")
        self.now += 91
        await self.refresh()
        self.assert_display(80)

    async def test_initial_cache_remains_available_when_http_fails(self):
        self.seed_old_cache()
        self.api.async_get_device_status.side_effect = TimeoutError("synthetic timeout")
        await self.refresh()
        self.assert_display(15, LawnMowerActivity.DOCKED)
        self.assertTrue(self.mower.available)

    async def test_startup_without_cache_uses_http(self):
        await self.refresh()
        self.assert_display(80)
        self.api.async_get_device_status.assert_awaited_once_with(self.device.id)

    async def test_fresh_mqtt_state_updates_entities_and_suppresses_http(self):
        await self.refresh()
        self.now += 30
        await self.push("state", {"state": "isRunning", "battery": 79})
        self.assert_display(79)
        self.api.async_get_device_status.reset_mock()
        self.now += 30
        await self.refresh()
        self.assert_display(79)
        self.api.async_get_device_status.assert_not_awaited()

    async def test_attribute_messages_do_not_hide_stale_state(self):
        await self.push("state", {"state": "idle", "battery": 15})
        self.now += 91
        await self.push("attributes", {"attributes": {"rain_delay": 30}})
        await self.refresh()
        self.assert_display(80)
        self.assertEqual(self.coordinator.get_device_attributes().attributes["rain_delay"], 30)

    async def test_mqtt_during_http_request_takes_priority(self):
        self.seed_old_cache()

        async def slow_http(_):
            self.now += 1
            await self.push("state", {"state": "isRunning", "battery": 79})
            return self.status(80, MowerStatus.DOCKED)

        self.api.async_get_device_status.side_effect = slow_http
        await self.refresh()
        self.assert_display(79)
        self.assertEqual(self.coordinator.data["meta"]["last_data_source"], "mqtt_push")

    async def test_attributes_during_http_do_not_discard_response(self):
        async def slow_http(_):
            self.now += 1
            await self.push("attributes", {"attributes": {"rain_delay": 30}})
            return self.status(80)

        self.api.async_get_device_status.side_effect = slow_http
        await self.refresh()
        self.assert_display(80)

    async def test_other_device_push_does_not_change_state(self):
        await self.refresh()
        await self.push("state", {"state": "idle", "battery": 15}, "other-device")
        self.assert_display(80)

    async def test_auth_failure_is_propagated(self):
        self.coordinator.oauth_session = SimpleNamespace(
            async_ensure_token_valid=AsyncMock(side_effect=ConfigEntryAuthFailed("synthetic"))
        )
        with self.assertRaises(ConfigEntryAuthFailed):
            await self.refresh()
        self.api.async_get_device_status.assert_not_awaited()

    async def test_token_is_refreshed_even_when_mqtt_is_fresh(self):
        await self.push("state", {"state": "isRunning", "battery": 79})
        session = SimpleNamespace(
            async_ensure_token_valid=AsyncMock(), token={"access_token": "synthetic-token"}
        )
        self.coordinator.oauth_session = session
        await self.refresh()
        session.async_ensure_token_valid.assert_awaited_once()
        self.api.set_token.assert_called_once_with("synthetic-token")
        self.api.async_get_device_status.assert_not_awaited()

    async def test_all_control_commands_keep_token_send_refresh_order(self):
        calls = []

        async def valid_token():
            calls.append("token")

        async def send(device_id, command):
            calls.append((device_id, command))

        async def refresh():
            calls.append("refresh")

        self.coordinator._async_ensure_valid_token = valid_token
        self.coordinator.async_request_refresh = refresh
        self.api.async_send_command.side_effect = send
        for method, command in (
            (self.mower.async_start_mowing, MowerCommand.START),
            (self.mower.async_pause, MowerCommand.PAUSE),
            (self.mower.async_dock, MowerCommand.DOCK),
            (self.mower.async_resume, MowerCommand.RESUME),
        ):
            with self.subTest(command=command):
                calls.clear()
                await method()
                self.assertEqual(calls, ["token", (self.device.id, command), "refresh"])


if __name__ == "__main__":
    unittest.main()
