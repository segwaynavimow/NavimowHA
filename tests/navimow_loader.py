"""Shared test loader for navimow modules.

Registers a lightweight stub for the ``custom_components.navimow`` package so
submodules can be imported without executing the integration's __init__.py
(which needs a full Home Assistant setup). Requires ``homeassistant`` and
``mower_sdk`` to be importable.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from types import ModuleType

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "navimow"

package_stub = types.ModuleType("custom_components")
package_stub.__path__ = [str(ROOT / "custom_components")]
navimow_stub = types.ModuleType("custom_components.navimow")
navimow_stub.__path__ = [str(PACKAGE_DIR)]
sys.modules.setdefault("custom_components", package_stub)
sys.modules.setdefault("custom_components.navimow", navimow_stub)


def load_module(name: str) -> ModuleType:
    """Import custom_components/navimow/<name>.py in package context."""
    full_name = f"custom_components.navimow.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, PACKAGE_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
