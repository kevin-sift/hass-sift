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

    @staticmethod
    def build_payload(asset: str, points: list[IngestPoint]) -> dict[str, Any]:
        """Group points by timestamp into a schemaless ingest body."""
        grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for point in points:
            grouped.setdefault(point.timestamp, []).append(
                {"channel": point.channel, "value": point.value}
            )
        return {
            "asset_name": asset,
            "data": [
                {"timestamp": ts, "values": values} for ts, values in grouped.items()
            ],
        }

    async def _flush(self, points: list[IngestPoint]) -> bool:
        payload = self.build_payload(self._asset, points)
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
