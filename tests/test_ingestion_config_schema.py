"""Validate ingestion_config YAML schema (Hybrid B)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import voluptuous as vol

ROOT = Path(__file__).resolve().parents[1]


def _load_schemas():
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
    return load("schemas", "schemas.py")


schemas = _load_schemas()


def test_config_without_ingestion_config_ok() -> None:
    conf = schemas.CONFIG_SCHEMA(
        {
            "sift": {
                "api_uri": "https://example.com/api/v2/ingest",
                "api_key": "k",
                "asset": "a",
            }
        }
    )
    assert "ingestion_config" not in conf["sift"]


def test_ingestion_config_typed_channel() -> None:
    conf = schemas.CONFIG_SCHEMA(
        {
            "sift": {
                "api_uri": "https://example.com/api/v2/ingest",
                "api_key": "k",
                "asset": "limburghome_ha",
                "ingestion_config": {
                    "client_key": "limburghome-ha-v1",
                    "typed_channels": [
                        {
                            "entity_id": "sensor.office_temperature",
                            "unit": "°F",
                            "description": "Office",
                            "data_type": "double",
                        }
                    ],
                },
            }
        }
    )
    ic = conf["sift"]["ingestion_config"]
    assert ic["client_key"] == "limburghome-ha-v1"
    assert ic["typed_channels"][0]["entity_id"] == "sensor.office_temperature"
    assert ic["typed_channels"][0]["unit"] == "°F"


def test_ingestion_config_rejects_bad_data_type() -> None:
    try:
        schemas.CONFIG_SCHEMA(
            {
                "sift": {
                    "api_uri": "https://example.com/api/v2/ingest",
                    "api_key": "k",
                    "asset": "a",
                    "ingestion_config": {
                        "typed_channels": [
                            {"entity_id": "sensor.x", "data_type": "nope"}
                        ]
                    },
                }
            }
        )
        raised = False
    except vol.Invalid:
        raised = True
    assert raised
