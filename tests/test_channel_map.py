"""Unit tests for optional sift.channel_map rename."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import voluptuous as vol

ROOT = Path(__file__).resolve().parents[1]


def _load_pkg():
    pkg = type(sys)("custom_components.sift")
    pkg.__path__ = [str(ROOT / "custom_components" / "sift")]
    sys.modules.setdefault("custom_components", type(sys)("custom_components"))
    sys.modules["custom_components"].__path__ = [str(ROOT / "custom_components")]
    sys.modules["custom_components.sift"] = pkg

    for name in ("const", "channels", "schemas", "ingest", "attributes"):
        path = ROOT / "custom_components" / "sift" / f"{name}.py"
        mod_name = f"custom_components.sift.{name}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        assert spec.loader
        spec.loader.exec_module(mod)
        setattr(pkg, name, mod)
    return pkg


pkg = _load_pkg()
resolve_sift_channel = pkg.channels.resolve_sift_channel
AttributeAllowlist = pkg.attributes.AttributeAllowlist
CONFIG_SCHEMA = pkg.schemas.CONFIG_SCHEMA
DOMAIN = pkg.const.DOMAIN

_ENTITY = "sensor.garagefridge_temperature"
_MAPPED = "home.garage.fridge.temperature"


def test_resolve_map_hit() -> None:
    assert (
        resolve_sift_channel(_ENTITY, channel_map={_ENTITY: _MAPPED}) == _MAPPED
    )


def test_resolve_map_miss() -> None:
    assert (
        resolve_sift_channel(
            "sensor.other", channel_map={_ENTITY: _MAPPED}
        )
        == "sensor.other"
    )


def test_resolve_empty_map_noop() -> None:
    assert resolve_sift_channel(_ENTITY, channel_map={}) == _ENTITY
    assert resolve_sift_channel(_ENTITY, channel_map=None) == _ENTITY
    assert resolve_sift_channel(_ENTITY) == _ENTITY


def test_resolve_attr_uses_mapped_base() -> None:
    assert (
        resolve_sift_channel(
            _ENTITY, attr="unit_of_measurement", channel_map={_ENTITY: _MAPPED}
        )
        == f"{_MAPPED}.unit_of_measurement"
    )


def test_resolve_attr_unmapped_keeps_entity_id_base() -> None:
    # weather.ksna stays ideal without mapping
    assert (
        resolve_sift_channel(
            "weather.ksna", attr="temperature", channel_map={_ENTITY: _MAPPED}
        )
        == "weather.ksna.temperature"
    )


def test_attr_forward_points_use_mapped_base() -> None:
    al = AttributeAllowlist.from_config(
        [
            {
                "entity_id": "climate.thermostat",
                "attributes": ["hvac_action"],
            }
        ]
    )
    points = al.points_for(
        entity_id="climate.thermostat",
        attributes={"hvac_action": "cooling"},
        timestamp="2026-01-01T00:00:00.000Z",
        channel_map={"climate.thermostat": "home.living.thermostat"},
    )
    assert len(points) == 1
    assert points[0].channel == "home.living.thermostat.hvac_action"
    assert points[0].value == "cooling"


def test_attr_forward_empty_map_noop() -> None:
    al = AttributeAllowlist.from_config(
        [
            {
                "entity_id": "climate.thermostat",
                "attributes": ["hvac_action"],
            }
        ]
    )
    points = al.points_for(
        entity_id="climate.thermostat",
        attributes={"hvac_action": "cooling"},
        timestamp="2026-01-01T00:00:00.000Z",
        channel_map={},
    )
    assert points[0].channel == "climate.thermostat.hvac_action"


def test_config_schema_accepts_channel_map() -> None:
    conf = CONFIG_SCHEMA(
        {
            DOMAIN: {
                "api_uri": "https://example.test/api/v2/ingest",
                "api_key": "k",
                "asset": "a",
                "channel_map": {_ENTITY: _MAPPED},
            }
        }
    )
    assert conf[DOMAIN]["channel_map"] == {_ENTITY: _MAPPED}


def test_config_schema_default_empty_map() -> None:
    conf = CONFIG_SCHEMA(
        {
            DOMAIN: {
                "api_uri": "https://example.test/api/v2/ingest",
                "api_key": "k",
                "asset": "a",
            }
        }
    )
    assert conf[DOMAIN]["channel_map"] == {}


def test_config_schema_rejects_empty_mapped_name() -> None:
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA(
            {
                DOMAIN: {
                    "api_uri": "https://example.test/api/v2/ingest",
                    "api_key": "k",
                    "asset": "a",
                    "channel_map": {_ENTITY: ""},
                }
            }
        )


def test_config_schema_rejects_empty_key() -> None:
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA(
            {
                DOMAIN: {
                    "api_uri": "https://example.test/api/v2/ingest",
                    "api_key": "k",
                    "asset": "a",
                    "channel_map": {"": _MAPPED},
                }
            }
        )
