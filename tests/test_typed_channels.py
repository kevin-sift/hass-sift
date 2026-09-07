"""Unit tests for Hybrid B typed channel allowlist / unit resolution."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    pkg_name = "custom_components.sift"
    if pkg_name not in sys.modules:
        pkg = type(sys)(pkg_name)
        pkg.__path__ = [str(ROOT / "custom_components" / "sift")]
        sys.modules.setdefault("custom_components", type(sys)("custom_components"))
        sys.modules["custom_components"].__path__ = [str(ROOT / "custom_components")]
        sys.modules[pkg_name] = pkg

    def load(mod_name: str, filename: str):
        full = f"{pkg_name}.{mod_name}"
        if full in sys.modules:
            return sys.modules[full]
        path = ROOT / "custom_components" / "sift" / filename
        spec = importlib.util.spec_from_file_location(full, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        assert spec.loader
        spec.loader.exec_module(mod)
        return mod

    load("const", "const.py")
    return load("typed_channels", "typed_channels.py")


tc = _load()


def test_empty_allowlist_is_falsy() -> None:
    al = tc.TypedChannelAllowlist.from_config([])
    assert not al
    assert len(al) == 0
    assert "sensor.x" not in al


def test_allowlist_from_config() -> None:
    al = tc.TypedChannelAllowlist.from_config(
        [
            {
                "entity_id": "sensor.office_temperature",
                "unit": "°F",
                "description": "Office",
                "data_type": "double",
            }
        ]
    )
    assert al
    assert "sensor.office_temperature" in al
    spec = al.get("sensor.office_temperature")
    assert spec is not None
    assert spec.unit == "°F"
    assert spec.description == "Office"
    assert spec.data_type == "double"


def test_resolve_unit_prefers_override() -> None:
    assert (
        tc.resolve_unit(
            attributes={"unit_of_measurement": "°C"},
            override="°F",
        )
        == "°F"
    )


def test_resolve_unit_from_uom() -> None:
    assert (
        tc.resolve_unit(attributes={"unit_of_measurement": "°F"}, override=None)
        == "°F"
    )


def test_resolve_unit_from_device_class() -> None:
    assert (
        tc.resolve_unit(attributes={"device_class": "temperature"}, override=None)
        == "°C"
    )


def test_resolve_channel_temp_f() -> None:
    spec = tc.TypedChannelSpec(entity_id="sensor.office_temperature")
    resolved = tc.resolve_channel(
        spec,
        value=72.5,
        attributes={
            "unit_of_measurement": "°F",
            "friendly_name": "Office Temperature",
            "device_class": "temperature",
        },
    )
    assert resolved.entity_id == "sensor.office_temperature"
    assert resolved.unit == "°F"
    assert resolved.description == "Office Temperature"
    assert resolved.data_type == "double"


def test_infer_data_type() -> None:
    assert tc.infer_data_type(1.2) == "double"
    assert tc.infer_data_type(True) == "bool"
    assert tc.infer_data_type("on") == "string"
    assert tc.infer_data_type("on", explicit="enum") == "enum"


def test_flow_name_stable() -> None:
    assert tc.flow_name_for("sensor.office_temperature") == (
        "ha_typed.sensor.office_temperature"
    )


def test_fingerprint() -> None:
    al = tc.TypedChannelAllowlist.from_config(
        [{"entity_id": "sensor.office_temperature"}]
    )
    resolved = tc.resolve_channel(
        al.get("sensor.office_temperature"),
        value=70.0,
        attributes={"unit_of_measurement": "°F"},
    )
    assert al.fingerprint(resolved) == (
        "sensor.office_temperature",
        "°F",
        "double",
    )
