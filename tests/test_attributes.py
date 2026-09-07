"""Unit tests for opt-in attribute forwarding."""

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

    for name in ("const", "schemas", "ingest", "attributes"):
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
AttributeAllowlist = pkg.attributes.AttributeAllowlist
coerce_attr_value = pkg.attributes.coerce_attr_value
CONFIG_SCHEMA = pkg.schemas.CONFIG_SCHEMA
DOMAIN = pkg.const.DOMAIN


def test_coerce_skips_none_unknown_unavailable() -> None:
    assert coerce_attr_value(None) is None
    assert coerce_attr_value("unknown") is None
    assert coerce_attr_value("unavailable") is None
    assert coerce_attr_value("") is None


def test_coerce_number_bool_string() -> None:
    assert coerce_attr_value(72.456) == 72.46
    assert coerce_attr_value("idle") == "idle"
    # bool True coerces via float path (existing STATE_VALUE_SCHEMA behavior)
    assert coerce_attr_value(True) == 1.0


def test_allowlist_empty_default() -> None:
    al = AttributeAllowlist.from_config(None)
    assert not al
    assert al.attrs_for("climate.thermostat") == frozenset()


def test_entity_and_domain_union() -> None:
    al = AttributeAllowlist.from_config(
        [
            {
                "entity_id": "climate.thermostat",
                "attributes": ["hvac_action", "temperature"],
            },
            {"domain": "climate", "attributes": ["hvac_action", "target_temp_high"]},
        ]
    )
    assert al.attrs_for("climate.thermostat") == frozenset(
        {"hvac_action", "temperature", "target_temp_high"}
    )
    assert al.attrs_for("climate.other") == frozenset(
        {"hvac_action", "target_temp_high"}
    )
    assert al.attrs_for("sensor.temp") == frozenset()


def test_points_for_channel_naming_and_skips() -> None:
    al = AttributeAllowlist.from_config(
        [
            {
                "entity_id": "climate.thermostat",
                "attributes": [
                    "hvac_action",
                    "temperature",
                    "missing_attr",
                    "bad",
                ],
            }
        ]
    )
    points = al.points_for(
        entity_id="climate.thermostat",
        attributes={
            "hvac_action": "cooling",
            "temperature": 72.0,
            "bad": None,
        },
        timestamp="2026-01-01T00:00:00.000Z",
    )
    channels = {p.channel: p.value for p in points}
    assert channels == {
        "climate.thermostat.hvac_action": "cooling",
        "climate.thermostat.temperature": 72.0,
    }


def test_config_schema_accepts_entity_and_domain_rules() -> None:
    conf = CONFIG_SCHEMA(
        {
            DOMAIN: {
                "api_uri": "https://example.test/api/v2/ingest",
                "api_key": "k",
                "asset": "a",
                "forward_attributes": [
                    {
                        "entity_id": "climate.thermostat",
                        "attributes": ["hvac_action"],
                    },
                    {"domain": "climate", "attributes": ["temperature"]},
                ],
            }
        }
    )
    assert len(conf[DOMAIN]["forward_attributes"]) == 2


def test_config_schema_rejects_empty_attributes() -> None:
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA(
            {
                DOMAIN: {
                    "api_uri": "https://example.test/api/v2/ingest",
                    "api_key": "k",
                    "asset": "a",
                    "forward_attributes": [
                        {"entity_id": "climate.thermostat", "attributes": []},
                    ],
                }
            }
        )


def test_config_schema_requires_entity_or_domain() -> None:
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA(
            {
                DOMAIN: {
                    "api_uri": "https://example.test/api/v2/ingest",
                    "api_key": "k",
                    "asset": "a",
                    "forward_attributes": [{"attributes": ["hvac_action"]}],
                }
            }
        )


def test_config_schema_default_empty() -> None:
    conf = CONFIG_SCHEMA(
        {
            DOMAIN: {
                "api_uri": "https://example.test/api/v2/ingest",
                "api_key": "k",
                "asset": "a",
            }
        }
    )
    assert conf[DOMAIN]["forward_attributes"] == []
