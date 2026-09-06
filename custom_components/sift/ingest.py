"""Queued, batched schemaless ingest worker for Sift."""

from __future__ import annotations

import asyncio
import logging
import random
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .schemas import PAYLOAD_SCHEMA

def parse_period_seconds(period: str | int) -> int:
    """Parse period like 86400, '24h', '1d', '6h', '30m' into seconds."""
    if isinstance(period, int):
        return period
    raw = str(period).strip().lower()
    if raw.isdigit():
        return int(raw)
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if raw[-1] in units and raw[:-1].replace(".", "", 1).isdigit():
        return int(float(raw[:-1]) * units[raw[-1]])
    raise ValueError(f"unsupported runs.period: {period!r}")


def rolling_bucket_id(period_seconds: int, when: datetime | None = None) -> str:
    """Stable bucket label for client_key (UTC).

    24h (86400) buckets use YYYY-MM-DD. Other periods use floor(epoch/period).
    """
    when = when or datetime.now(timezone.utc)
    if period_seconds == 86400:
        return when.strftime("%Y-%m-%d")
    epoch = int(when.timestamp())
    bucket = epoch // period_seconds
    return f"p{period_seconds}-{bucket}"


def sanitize_key_part(value: str) -> str:
    """Keep client_key chars within Sift-ish safe set."""
    out = []
    for ch in value:
        if ch.isalnum() or ch in "_~.-":
            out.append(ch)
        else:
            out.append("-")
    cleaned = "".join(out).strip("-._")
    return cleaned or "run"


_LOGGER = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_AUTH_STATUS = frozenset({401, 403})


@dataclass(frozen=True, slots=True)
class IngestPoint:
    """One channel value at a timestamp."""

    timestamp: str
    channel: str
    value: float | str | bool


def empty_stats() -> dict[str, Any]:
    """Initial stats dict (also used by health entities later)."""
    return {
        "last_success": None,
        "consecutive_failures": 0,
        "dropped_points": 0,
        "queue_depth": 0,
        "auth_failed": False,
        "last_error": None,
        "current_run_client_key": None,
    }


class IngestWorker:
    """Single-consumer worker: drain queue, batch POST, retry with backoff."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        api_uri: str,
        api_key: str,
        asset: str,
        stats: dict[str, Any],
        flush_interval: float,
        max_batch_points: int,
        queue_maxsize: int,
        max_retries: int,
        backoff_base: float,
        backoff_max: float,
        runs_mode: str = "none",
        runs_period: str | int = "24h",
        runs_key_prefix: str | None = None,
    ) -> None:
        self._session = session
        self._api_uri = api_uri
        self._api_key = api_key
        self._asset = asset
        self.stats = stats
        self._flush_interval = flush_interval
        self._max_batch_points = max_batch_points
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._runs_mode = runs_mode
        self._runs_period_seconds = parse_period_seconds(runs_period)
        self._runs_key_prefix = sanitize_key_part(runs_key_prefix or asset)
        self._queue: asyncio.Queue[IngestPoint] = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    def enqueue(self, point: IngestPoint) -> None:
        """Non-blocking enqueue; drop-oldest when full."""
        try:
            self._queue.put_nowait(point)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self.stats["dropped_points"] = int(self.stats["dropped_points"]) + 1
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(point)
            except asyncio.QueueFull:
                self.stats["dropped_points"] = int(self.stats["dropped_points"]) + 1
                _LOGGER.warning("Sift ingest queue full; dropping point for %s", point.channel)
        self.stats["queue_depth"] = self._queue.qsize()

    async def start(self) -> None:
        """Start the background worker task."""
        if self._task is not None:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="sift_ingest_worker")

    async def stop(self) -> None:
        """Stop worker and best-effort flush remaining points."""
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Best-effort final flush
        points = self._drain(self._max_batch_points)
        if points:
            await self._flush(points)

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                points = await self._collect_batch()
                if not points:
                    continue
                await self._flush(points)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep worker alive
                _LOGGER.exception("Sift ingest worker error; continuing")
                await asyncio.sleep(1)

    async def _collect_batch(self) -> list[IngestPoint]:
        """Wait for first point, then drain until flush interval or batch full."""
        try:
            first = await asyncio.wait_for(
                self._queue.get(), timeout=self._flush_interval
            )
        except asyncio.TimeoutError:
            self.stats["queue_depth"] = self._queue.qsize()
            return []

        points = [first]
        deadline = asyncio.get_running_loop().time() + self._flush_interval
        while len(points) < self._max_batch_points:
            timeout = deadline - asyncio.get_running_loop().time()
            if timeout <= 0:
                break
            try:
                points.append(await asyncio.wait_for(self._queue.get(), timeout=timeout))
            except asyncio.TimeoutError:
                break
        self.stats["queue_depth"] = self._queue.qsize()
        return points

    def _drain(self, limit: int) -> list[IngestPoint]:
        points: list[IngestPoint] = []
        while len(points) < limit:
            try:
                points.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        self.stats["queue_depth"] = self._queue.qsize()
        return points

    def current_run_config(self) -> dict[str, str] | None:
        """Return schemaless run_config for rolling mode, else None."""
        if self._runs_mode != "rolling":
            return None
        bucket = rolling_bucket_id(self._runs_period_seconds)
        client_key = f"{self._runs_key_prefix}-{bucket}"
        # Sift client_key: 3-128 chars, start/end alnum
        if len(client_key) < 3:
            client_key = f"run-{client_key}"
        client_key = client_key[:128]
        self.stats["current_run_client_key"] = client_key
        return {"client_key": client_key, "name": client_key}

    @staticmethod
    def build_payload(
        asset: str,
        points: list[IngestPoint],
        run_config: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Group points by timestamp into a schemaless ingest body."""
        grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for point in points:
            grouped.setdefault(point.timestamp, []).append(
                {"channel": point.channel, "value": point.value}
            )
        payload: dict[str, Any] = {
            "asset_name": asset,
            "data": [
                {"timestamp": ts, "values": values} for ts, values in grouped.items()
            ],
        }
        if run_config:
            payload["run_config"] = run_config
        return payload

    async def _flush(self, points: list[IngestPoint]) -> bool:
        payload = self.build_payload(self._asset, points, self.current_run_config())
        try:
            validated = PAYLOAD_SCHEMA(payload)
        except Exception as exc:  # noqa: BLE001
            self._record_failure(f"payload validation: {exc}")
            _LOGGER.error("Dropping invalid Sift batch (%s points): %s", len(points), exc)
            return False

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(self._max_retries + 1):
            try:
                async with self._session.post(
                    self._api_uri, json=validated, headers=headers
                ) as resp:
                    body = await resp.text()
                    if resp.status == 200:
                        self._record_success()
                        _LOGGER.debug(
                            "Sent %s point(s) to Sift successfully", len(points)
                        )
                        return True

                    if resp.status in _AUTH_STATUS:
                        self.stats["auth_failed"] = True
                        self._record_failure(f"HTTP {resp.status}: {body[:200]}")
                        _LOGGER.error(
                            "Sift auth error %s; not retrying. Body: %s",
                            resp.status,
                            body[:500],
                        )
                        return False

                    if resp.status == 400:
                        self._record_failure(f"HTTP 400: {body[:200]}")
                        _LOGGER.error(
                            "Sift rejected batch (400); dropping %s point(s): %s",
                            len(points),
                            body[:500],
                        )
                        return False

                    if resp.status in _RETRYABLE_STATUS and attempt < self._max_retries:
                        delay = self._backoff_delay(attempt)
                        _LOGGER.warning(
                            "Sift API %s (attempt %s/%s); retry in %.2fs: %s",
                            resp.status,
                            attempt + 1,
                            self._max_retries + 1,
                            delay,
                            body[:200],
                        )
                        await asyncio.sleep(delay)
                        continue

                    self._record_failure(f"HTTP {resp.status}: {body[:200]}")
                    _LOGGER.error(
                        "Sift API error %s after retries; dropping %s point(s): %s",
                        resp.status,
                        len(points),
                        body[:500],
                    )
                    return False

            except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as exc:
                if attempt < self._max_retries:
                    delay = self._backoff_delay(attempt)
                    _LOGGER.warning(
                        "Sift transport error (attempt %s/%s); retry in %.2fs: %s",
                        attempt + 1,
                        self._max_retries + 1,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                self._record_failure(str(exc))
                _LOGGER.exception(
                    "Sift transport error after retries; dropping %s point(s)",
                    len(points),
                )
                return False

        return False

    def _backoff_delay(self, attempt: int) -> float:
        delay = self._backoff_base * (2**attempt)
        delay = min(delay, self._backoff_max)
        jitter = delay * 0.1 * random.random()
        return delay + jitter

    def _record_success(self) -> None:
        self.stats["last_success"] = datetime.now(timezone.utc)
        self.stats["consecutive_failures"] = 0
        self.stats["auth_failed"] = False
        self.stats["last_error"] = None
        self.stats["queue_depth"] = self._queue.qsize()

    def _record_failure(self, error: str) -> None:
        self.stats["consecutive_failures"] = int(self.stats["consecutive_failures"]) + 1
        self.stats["last_error"] = error
        self.stats["queue_depth"] = self._queue.qsize()
