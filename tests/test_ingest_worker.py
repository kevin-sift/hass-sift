"""Unit tests for IngestWorker (no Home Assistant runtime required)."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
INGEST_PATH = ROOT / "custom_components" / "sift" / "ingest.py"


def _load_ingest():
    # Load schemas first as a sibling dependency with stubs already in conftest
    schemas_path = ROOT / "custom_components" / "sift" / "schemas.py"
    # Build a fake package
    pkg = type(sys)("custom_components.sift")
    pkg.__path__ = [str(ROOT / "custom_components" / "sift")]
    sys.modules.setdefault("custom_components", type(sys)("custom_components"))
    sys.modules["custom_components"].__path__ = [str(ROOT / "custom_components")]
    sys.modules["custom_components.sift"] = pkg

    spec_s = importlib.util.spec_from_file_location(
        "custom_components.sift.schemas", schemas_path
    )
    schemas = importlib.util.module_from_spec(spec_s)
    sys.modules["custom_components.sift.schemas"] = schemas
    assert spec_s.loader
    spec_s.loader.exec_module(schemas)

    spec = importlib.util.spec_from_file_location(
        "custom_components.sift.ingest", INGEST_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["custom_components.sift.ingest"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


ingest = _load_ingest()
IngestPoint = ingest.IngestPoint
IngestWorker = ingest.IngestWorker
empty_stats = ingest.empty_stats


def _worker(**overrides: Any):
    stats = empty_stats()
    session = MagicMock()
    kwargs = {
        "session": session,
        "api_uri": "https://example.test/api/v2/ingest",
        "api_key": "test-key",
        "asset": "test_asset",
        "stats": stats,
        "flush_interval": 0.05,
        "max_batch_points": 10,
        "queue_maxsize": 3,
        "max_retries": 2,
        "backoff_base": 0.01,
        "backoff_max": 0.05,
    }
    kwargs.update(overrides)
    return IngestWorker(**kwargs)


def test_build_payload_groups_same_timestamp() -> None:
    points = [
        IngestPoint("2026-01-01T00:00:00.000Z", "sensor.a", 1.0),
        IngestPoint("2026-01-01T00:00:00.000Z", "sensor.b", True),
        IngestPoint("2026-01-01T00:00:01.000Z", "sensor.a", 2.0),
    ]
    payload = IngestWorker.build_payload("asset", points)
    assert payload["asset_name"] == "asset"
    assert len(payload["data"]) == 2
    assert payload["data"][0]["values"] == [
        {"channel": "sensor.a", "value": 1.0},
        {"channel": "sensor.b", "value": True},
    ]


def test_build_payload_dedupes_channel_last_write_wins() -> None:
    """Same channel twice at one timestamp must not produce duplicate values."""
    points = [
        IngestPoint("2026-01-01T00:00:00.000Z", "binary_sensor.sift_heartbeat", "off"),
        IngestPoint("2026-01-01T00:00:00.000Z", "sensor.a", 1.0),
        IngestPoint("2026-01-01T00:00:00.000Z", "binary_sensor.sift_heartbeat", "on"),
    ]
    payload = IngestWorker.build_payload("asset", points)
    assert len(payload["data"]) == 1
    values = payload["data"][0]["values"]
    channels = [v["channel"] for v in values]
    assert channels.count("binary_sensor.sift_heartbeat") == 1
    assert {"channel": "binary_sensor.sift_heartbeat", "value": "on"} in values
    assert {"channel": "sensor.a", "value": 1.0} in values


def test_build_payload_same_channel_different_timestamps_ok() -> None:
    points = [
        IngestPoint("2026-01-01T00:00:00.000Z", "sensor.a", 1.0),
        IngestPoint("2026-01-01T00:00:00.001Z", "sensor.a", 2.0),
    ]
    payload = IngestWorker.build_payload("asset", points)
    assert len(payload["data"]) == 2
    assert payload["data"][0]["values"] == [{"channel": "sensor.a", "value": 1.0}]
    assert payload["data"][1]["values"] == [{"channel": "sensor.a", "value": 2.0}]


def test_enqueue_drop_oldest() -> None:
    worker = _worker(queue_maxsize=2)
    worker.enqueue(IngestPoint("t1", "sensor.a", 1))
    worker.enqueue(IngestPoint("t2", "sensor.b", 2))
    worker.enqueue(IngestPoint("t3", "sensor.c", 3))
    assert worker.stats["dropped_points"] == 1
    first = worker._queue.get_nowait()
    second = worker._queue.get_nowait()
    assert first.channel == "sensor.b"
    assert second.channel == "sensor.c"


@pytest.mark.asyncio
async def test_retry_429_then_200() -> None:
    worker = _worker(max_retries=3, backoff_base=0.001, backoff_max=0.01)
    resp_429 = MagicMock()
    resp_429.status = 429
    resp_429.text = AsyncMock(return_value="slow down")
    resp_429.__aenter__ = AsyncMock(return_value=resp_429)
    resp_429.__aexit__ = AsyncMock(return_value=None)

    resp_200 = MagicMock()
    resp_200.status = 200
    resp_200.text = AsyncMock(return_value="ok")
    resp_200.__aenter__ = AsyncMock(return_value=resp_200)
    resp_200.__aexit__ = AsyncMock(return_value=None)

    worker._session.post = MagicMock(side_effect=[resp_429, resp_200])
    ok = await worker._flush([IngestPoint("t", "sensor.a", 1.5)])
    assert ok is True
    assert worker.stats["consecutive_failures"] == 0
    assert worker.stats["last_success"] is not None
    assert worker._session.post.call_count == 2


@pytest.mark.asyncio
async def test_no_retry_401() -> None:
    worker = _worker(max_retries=5)
    resp = MagicMock()
    resp.status = 401
    resp.text = AsyncMock(return_value="unauthorized")
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    worker._session.post = MagicMock(return_value=resp)

    ok = await worker._flush([IngestPoint("t", "sensor.a", 1.5)])
    assert ok is False
    assert worker.stats["auth_failed"] is True
    assert worker._session.post.call_count == 1


@pytest.mark.asyncio
async def test_worker_serializes_flushes() -> None:
    worker = _worker(flush_interval=0.01, max_batch_points=2, queue_maxsize=50)
    in_flight = 0
    max_in_flight = 0
    calls = 0

    async def fake_flush(points):  # noqa: ANN001
        nonlocal in_flight, max_in_flight, calls
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        calls += 1
        await asyncio.sleep(0.02)
        in_flight -= 1
        worker._record_success()
        return True

    worker._flush = fake_flush  # type: ignore[method-assign]
    await worker.start()
    for i in range(6):
        worker.enqueue(IngestPoint(f"t{i}", f"sensor.{i}", i))
    await asyncio.sleep(0.25)
    await worker.stop()
    assert calls >= 1
    assert max_in_flight == 1


@pytest.mark.asyncio
async def test_stop_flushes_entire_queue() -> None:
    """stop() must flush all queued points, not only one max_batch_points chunk."""
    worker = _worker(flush_interval=60.0, max_batch_points=2, queue_maxsize=50)
    flushed: list[list] = []

    async def fake_flush(points):  # noqa: ANN001
        flushed.append(list(points))
        worker._record_success()
        return True

    worker._flush = fake_flush  # type: ignore[method-assign]
    # Do not start the background worker — points stay queued until stop().
    for i in range(5):
        worker.enqueue(IngestPoint(f"t{i}", f"sensor.{i}", i))
    await worker.stop()
    assert sum(len(batch) for batch in flushed) == 5
    assert [p.channel for batch in flushed for p in batch] == [
        "sensor.0",
        "sensor.1",
        "sensor.2",
        "sensor.3",
        "sensor.4",
    ]
    assert worker._queue.qsize() == 0


@pytest.mark.asyncio
async def test_stop_recovers_in_flight_on_cancel() -> None:
    """Points dequeued into an interrupted flush are still sent on stop()."""
    worker = _worker(flush_interval=0.01, max_batch_points=10, queue_maxsize=50)
    entered = asyncio.Event()
    flushed: list[list] = []
    calls = 0

    async def flush_then_block(points):  # noqa: ANN001
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            # First attempt is interrupted by stop()'s cancel.
            await asyncio.sleep(60)
            raise AssertionError("should have been cancelled")
        flushed.append(list(points))
        worker._record_success()
        return True

    worker._flush = flush_then_block  # type: ignore[method-assign]
    await worker.start()
    worker.enqueue(IngestPoint("t0", "sensor.held", 1))
    await asyncio.wait_for(entered.wait(), timeout=1.0)
    assert [p.channel for p in worker._in_flight] == ["sensor.held"]
    await worker.stop()
    assert calls == 2
    assert sum(len(batch) for batch in flushed) == 1
    assert flushed[0][0].channel == "sensor.held"

