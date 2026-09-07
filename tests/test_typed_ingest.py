"""Unit tests for Hybrid B typed ingest worker / URI helpers (mocked backend)."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

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
    load("typed_channels", "typed_channels.py")
    return load("typed_ingest", "typed_ingest.py")


ti = _load()
# typed_channels already loaded as sibling
tc = sys.modules["custom_components.sift.typed_channels"]


def test_derive_uris_from_api_uri() -> None:
    grpc, rest = ti.derive_uris("https://sift.example.com/api/v2/ingest")
    assert grpc == "sift.example.com:443"
    assert rest == "https://sift.example.com"


def test_derive_uris_overrides() -> None:
    grpc, rest = ti.derive_uris(
        "https://sift.example.com/api/v2/ingest",
        grpc_uri="grpc.example.com:443",
        rest_uri="https://rest.example.com",
    )
    assert grpc == "grpc.example.com:443"
    assert rest == "https://rest.example.com"


@pytest.mark.asyncio
async def test_typed_worker_sends_via_backend() -> None:
    backend = ti.MockTypedBackend()
    allowlist = tc.TypedChannelAllowlist.from_config(
        [{"entity_id": "sensor.office_temperature", "unit": "°F"}]
    )
    stats = {
        "last_success": None,
        "consecutive_failures": 0,
        "dropped_points": 0,
        "queue_depth": 0,
        "auth_failed": False,
        "last_error": None,
    }
    worker = ti.TypedIngestWorker(
        backend=backend, allowlist=allowlist, stats=stats, queue_maxsize=10
    )
    await worker.start()
    assert backend.started
    assert worker.contains("sensor.office_temperature")
    assert not worker.contains("sensor.other")

    worker.enqueue(
        ti.TypedPoint(
            timestamp="2026-09-07T12:00:00.000Z",
            spec=allowlist.get("sensor.office_temperature"),
            value=72.5,
            attributes={"unit_of_measurement": "°F", "friendly_name": "Office"},
        )
    )
    # Allow consumer to drain
    for _ in range(50):
        if backend.sent:
            break
        await asyncio.sleep(0.02)

    await worker.stop()
    assert backend.stopped
    assert len(backend.sent) == 1
    point, resolved = backend.sent[0]
    assert point.value == 72.5
    assert resolved.unit == "°F"
    assert resolved.data_type == "double"
    assert stats["consecutive_failures"] == 0
    assert stats["last_success"] is not None


@pytest.mark.asyncio
async def test_schema_guard_refuses_fingerprint_change() -> None:
    """SiftClientTypedBackend.send refuses unit/type change after register.

    Uses a stub stream so we do not need live sift_client networking.
    """

    class _StubStream:
        def __init__(self) -> None:
            self.flows = []
            self.sent = []

        async def add_new_flows(self, flows):
            self.flows.extend(flows)

        def try_send(self, flow_py):
            self.sent.append(flow_py)

        async def finish(self):
            return None

    backend = ti.SiftClientTypedBackend(
        api_key="k",
        asset="test_asset",
        client_key="limburghome-ha-v1",
        grpc_uri="example.com:443",
        rest_uri="https://example.com",
    )
    # Bypass start(); inject stub
    backend._stream = _StubStream()
    backend._finished = False

    spec = tc.TypedChannelSpec(entity_id="sensor.office_temperature", unit="°F")
    point = ti.TypedPoint(
        timestamp="2026-09-07T12:00:00.000Z",
        spec=spec,
        value=70.0,
        attributes={"unit_of_measurement": "°F"},
    )
    resolved = tc.resolve_channel(spec, value=70.0, attributes={"unit_of_measurement": "°F"})

    # Patch _register_flow / _to_flow_py to avoid sift imports for first send
    async def _fake_register(resolved_ch):
        backend._registered[resolved_ch.entity_id] = (
            resolved_ch.entity_id,
            resolved_ch.unit,
            resolved_ch.data_type,
        )

    def _fake_flow(point_, resolved_ch):
        return ("flow", resolved_ch.entity_id, point_.value)

    backend._register_flow = _fake_register  # type: ignore[method-assign]
    backend._to_flow_py = _fake_flow  # type: ignore[method-assign]

    await backend.send(point, resolved)
    assert len(backend._stream.sent) == 1

    # Same entity, different unit → refused
    bad = tc.resolve_channel(
        tc.TypedChannelSpec(entity_id="sensor.office_temperature", unit="°C"),
        value=21.0,
        attributes={"unit_of_measurement": "°C"},
    )
    await backend.send(point, bad)
    assert len(backend._stream.sent) == 1  # no additional send
