"""Unit tests for health binary_sensor freshness + heartbeat canary."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel: str):
    pkg_name = "custom_components.sift"
    if pkg_name not in sys.modules:
        pkg = type(sys)(pkg_name)
        pkg.__path__ = [str(ROOT / "custom_components" / "sift")]
        sys.modules.setdefault("custom_components", type(sys)("custom_components"))
        sys.modules["custom_components"].__path__ = [str(ROOT / "custom_components")]
        sys.modules[pkg_name] = pkg

    # Ensure const/schemas available as siblings when needed
    for sibling in ("const", "schemas"):
        full = f"{pkg_name}.{sibling}"
        if full not in sys.modules:
            path = ROOT / "custom_components" / "sift" / f"{sibling}.py"
            spec = importlib.util.spec_from_file_location(full, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[full] = mod
            assert spec.loader
            spec.loader.exec_module(mod)

    full = f"{pkg_name}.{name}"
    path = ROOT / "custom_components" / "sift" / rel
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


binary_sensor = _load_module("binary_sensor", "binary_sensor.py")
schemas = _load_module("schemas", "schemas.py")
const = _load_module("const", "const.py")

SiftIngestOkBinarySensor = binary_sensor.SiftIngestOkBinarySensor
SiftHeartbeatBinarySensor = binary_sensor.SiftHeartbeatBinarySensor
CONFIG_SCHEMA = schemas.CONFIG_SCHEMA


def test_ingest_ok_false_without_success() -> None:
    stats = {
        "last_success": None,
        "auth_failed": False,
        "consecutive_failures": 0,
    }
    sens = SiftIngestOkBinarySensor(stats, stale_after=300)
    assert sens.is_on is False


def test_ingest_ok_true_when_fresh() -> None:
    stats = {
        "last_success": datetime.now(timezone.utc) - timedelta(seconds=10),
        "auth_failed": False,
        "consecutive_failures": 0,
    }
    sens = SiftIngestOkBinarySensor(stats, stale_after=300)
    assert sens.is_on is True


def test_ingest_ok_false_when_stale() -> None:
    stats = {
        "last_success": datetime.now(timezone.utc) - timedelta(seconds=400),
        "auth_failed": False,
        "consecutive_failures": 3,
    }
    sens = SiftIngestOkBinarySensor(stats, stale_after=300)
    assert sens.is_on is False


def test_ingest_ok_false_on_auth_failed() -> None:
    stats = {
        "last_success": datetime.now(timezone.utc),
        "auth_failed": True,
        "consecutive_failures": 1,
    }
    sens = SiftIngestOkBinarySensor(stats, stale_after=300)
    assert sens.is_on is False


def test_ingest_ok_attributes() -> None:
    last = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    stats = {
        "last_success": last,
        "auth_failed": False,
        "consecutive_failures": 2,
    }
    sens = SiftIngestOkBinarySensor(stats, stale_after=120)
    attrs = sens.extra_state_attributes
    assert attrs["last_success"] == last.isoformat()
    assert attrs["consecutive_failures"] == 2
    assert attrs["auth_failed"] is False
    assert attrs["stale_after_seconds"] == 120
    assert "current_run_client_key" not in attrs


def test_heartbeat_toggles() -> None:
    hb = SiftHeartbeatBinarySensor()
    assert hb.is_on is False
    hb.toggle()
    assert hb.is_on is True
    hb.toggle()
    assert hb.is_on is False


def test_config_schema_accepts_health_and_heartbeat() -> None:
    conf = CONFIG_SCHEMA(
        {
            "sift": {
                "api_uri": "https://example.test/api/v2/ingest",
                "api_key": "k",
                "asset": "limburghome_ha",
                "health_stale_after": 180,
                "heartbeat": {"enabled": True, "interval": 45},
            }
        }
    )
    sift = conf["sift"]
    assert sift["health_stale_after"] == 180
    assert sift["heartbeat"]["enabled"] is True
    assert sift["heartbeat"]["interval"] == 45


def test_config_schema_defaults_heartbeat_off() -> None:
    conf = CONFIG_SCHEMA(
        {
            "sift": {
                "api_uri": "https://example.test/api/v2/ingest",
                "api_key": "k",
                "asset": "limburghome_ha",
            }
        }
    )
    sift = conf["sift"]
    assert sift["health_stale_after"] == const.DEFAULT_HEALTH_STALE_AFTER
    assert "heartbeat" not in sift or sift.get("heartbeat") is None


def test_heartbeat_entity_id_constant() -> None:
    assert const.HEARTBEAT_ENTITY_ID == "binary_sensor.sift_heartbeat"
