"""Tests for the Navimow diagnostics platform.

These tests validate the diagnostics logic (freshness derivation + redaction)
without a running Home Assistant instance and without the Navimow SDK. Home
Assistant must be importable (for ``async_redact_data``); the mower hardware and
the ``mower_sdk`` package are not required.
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import pathlib
import sys
import time
import types

# --- Import diagnostics.py in isolation -------------------------------------
# Register a lightweight stub for the ``custom_components.navimow`` package so
# importing the diagnostics submodule does NOT execute the integration's
# __init__.py (which pulls in the mower_sdk runtime dependency). Only the real
# const.py and diagnostics.py modules are loaded.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_NAV = _ROOT / "custom_components" / "navimow"

_cc = types.ModuleType("custom_components")
_cc.__path__ = [str(_ROOT / "custom_components")]
_nav = types.ModuleType("custom_components.navimow")
_nav.__path__ = [str(_NAV)]
sys.modules.setdefault("custom_components", _cc)
sys.modules.setdefault("custom_components.navimow", _nav)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"custom_components.navimow.{name}", _NAV / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_load("const")
diagnostics = _load("diagnostics")


# --- Fakes ------------------------------------------------------------------
@dataclasses.dataclass
class _FakeState:
    device_id: str
    battery: int
    state: str
    access_token: str


class _FakeSDK:
    is_connected = True


class _FakeDevice:
    id = "SN-SECRET-0001"
    model = "i110N"


class _FakeCoordinator:
    def __init__(self, last_mqtt, last_http, source):
        self.sdk = _FakeSDK()
        self.device = _FakeDevice()
        self.data = {
            "state": _FakeState(
                device_id="SN-SECRET-0001",
                battery=80,
                state="docked",
                access_token="tok_should_be_hidden",
            ),
            "attributes": {"rain_delay": 30, "password": "hunter2"},
            "meta": {
                "last_data_source": source,
                "last_mqtt_update_monotonic": last_mqtt,
                "last_http_fetch_monotonic": last_http,
            },
        }


class _FakeEntry:
    entry_id = "entry-1"


def _make_hass(coordinator):
    hass = types.SimpleNamespace()
    hass.data = {
        diagnostics.DOMAIN: {
            "entry-1": {"coordinators": {"SN-SECRET-0001": coordinator}}
        }
    }
    return hass


# --- Tests ------------------------------------------------------------------
def test_config_entry_diagnostics_freshness_and_redaction():
    now = time.monotonic()
    coordinator = _FakeCoordinator(
        last_mqtt=now - 600,  # stale (> MQTT_STALE_SECONDS=300)
        last_http=now - 30,  # fresh
        source="http_fallback",
    )
    result = asyncio.run(
        diagnostics.async_get_config_entry_diagnostics(
            _make_hass(coordinator), _FakeEntry()
        )
    )

    block = result["coordinators"][0]

    # Derived freshness fields.
    assert block["last_data_source"] == "http_fallback"
    assert block["is_mqtt_stale"] is True
    assert 595 <= block["mqtt_age_seconds"] <= 615
    assert 25 <= block["http_age_seconds"] <= 45
    assert block["sdk_connected"] is True
    assert block["device_model"] == "i110N"

    # Redaction: nothing sensitive leaks; non-sensitive values are preserved.
    assert block["device_id"] == "**REDACTED**"
    assert block["last_state"]["access_token"] == "**REDACTED**"
    assert block["last_state"]["device_id"] == "**REDACTED**"
    assert block["last_state"]["battery"] == 80
    assert block["last_attributes"]["password"] == "**REDACTED**"
    assert block["last_attributes"]["rain_delay"] == 30

    # Static config echoed for context.
    cfg = result["integration"]["config"]
    assert cfg["mqtt_stale_seconds"] == 300
    assert cfg["http_fallback_min_interval"] == 3600


def test_fresh_mqtt_is_not_stale():
    now = time.monotonic()
    coordinator = _FakeCoordinator(last_mqtt=now - 5, last_http=None, source="mqtt_push")
    result = asyncio.run(
        diagnostics.async_get_config_entry_diagnostics(
            _make_hass(coordinator), _FakeEntry()
        )
    )
    block = result["coordinators"][0]
    assert block["is_mqtt_stale"] is False
    assert block["http_age_seconds"] is None


def test_to_serializable_handles_bytes_and_cycles():
    # bytes -> hex, so no raw b'...' repr leaks into the dump.
    assert diagnostics._to_serializable(b"\x00\xff") == "00ff"
    # Self-referential structures must not crash a diagnostics dump.
    cyclic: dict = {}
    cyclic["self"] = cyclic
    out = diagnostics._to_serializable(cyclic)
    assert out["self"] == "**CIRCULAR**"


if __name__ == "__main__":
    test_config_entry_diagnostics_freshness_and_redaction()
    test_fresh_mqtt_is_not_stale()
    test_to_serializable_handles_bytes_and_cycles()
    print("OK: diagnostics tests passed")
