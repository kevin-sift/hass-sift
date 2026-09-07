"""Hybrid B typed ingest: IngestionConfig streaming via sift_client.

Prefer ``sift_client.IngestionConfigStreamingClient`` (async) when
``sift-stack-py[sift-stream]`` is installed. Schemaless REST path is unchanged
when the typed allowlist is empty — this module is only constructed when
``ingestion_config.typed_channels`` is non-empty.

Architecture (expansion-ready):
- One flow per allowlisted entity: ``ha_typed.{entity_id}``
- Channel name stays full ``entity_id``
- Additive growth via ``add_new_flows`` (same stable ``client_key``)
- Schema guard refuses unit/type changes on an already-registered channel
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlparse

from .typed_channels import (
    ResolvedChannel,
    TypedChannelAllowlist,
    TypedChannelSpec,
    flow_name_for,
    resolve_channel,
)

_LOGGER = logging.getLogger(__name__)

_DTYPE_TO_SIFT = {
    "double": "DOUBLE",
    "float": "FLOAT",
    "bool": "BOOL",
    "string": "STRING",
    "int32": "INT_32",
    "int64": "INT_64",
    "enum": "ENUM",
}


@dataclass(frozen=True, slots=True)
class TypedPoint:
    """One allowlisted value ready for typed send."""

    timestamp: str  # ISO-8601 Z
    spec: TypedChannelSpec
    value: float | str | bool
    attributes: dict[str, Any]


class TypedStreamBackend(Protocol):
    """Minimal surface for the typed path (mockable in tests)."""

    async def start(self) -> None: ...

    async def send(self, point: TypedPoint, resolved: ResolvedChannel) -> None: ...

    async def stop(self) -> None: ...


def derive_uris(
    api_uri: str,
    *,
    grpc_uri: str | None = None,
    rest_uri: str | None = None,
) -> tuple[str, str]:
    """Derive (grpc_host, rest_url) from schemaless api_uri + optional overrides.

    ``api_uri`` looks like ``https://host/api/v2/ingest``.
    ``grpc_uri`` should be ``host:port`` (no scheme) when set.
    """
    parsed = urlparse(api_uri)
    host = parsed.hostname or ""
    scheme = parsed.scheme or "https"
    default_port = 443 if scheme == "https" else 80

    if rest_uri:
        rest = rest_uri.rstrip("/")
    else:
        netloc = parsed.netloc or host
        rest = f"{scheme}://{netloc}"

    if grpc_uri:
        grpc = grpc_uri.replace("https://", "").replace("http://", "").rstrip("/")
    else:
        port = parsed.port or default_port
        grpc = f"{host}:{port}" if host else ""

    return grpc, rest


class MockTypedBackend:
    """In-memory backend for unit tests (records resolved sends)."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.sent: list[tuple[TypedPoint, ResolvedChannel]] = []

    async def start(self) -> None:
        self.started = True

    async def send(self, point: TypedPoint, resolved: ResolvedChannel) -> None:
        self.sent.append((point, resolved))

    async def stop(self) -> None:
        self.stopped = True


class SiftClientTypedBackend:
    """Real sift_client IngestionConfigStreamingClient adapter.

    Lazy-imports ``sift_client`` / ``sift_stream_bindings`` so schemaless-only
    installs never need the native wheel.
    """

    def __init__(
        self,
        *,
        api_key: str,
        asset: str,
        client_key: str,
        grpc_uri: str,
        rest_uri: str,
        use_ssl: bool = True,
    ) -> None:
        self._api_key = api_key
        self._asset = asset
        self._client_key = client_key
        self._grpc_uri = grpc_uri
        self._rest_uri = rest_uri
        self._use_ssl = use_ssl
        self._client: Any = None
        self._stream: Any = None
        self._registered: dict[str, tuple[str, str, str]] = {}  # entity → fingerprint
        self._finished = False

    async def start(self) -> None:
        try:
            from sift_client import SiftClient, SiftConnectionConfig
            from sift_client.resources import StreamingMode
            from sift_client.sift_types import RunCreate
            from sift_client.sift_types.ingestion import IngestionConfigCreate
        except ImportError as exc:
            raise RuntimeError(
                "typed_channels requires sift-stack-py[sift-stream]; "
                "pip install 'sift-stack-py[sift-stream]' in the HA environment"
            ) from exc

        grpc_host = (
            self._grpc_uri.replace("https://", "")
            .replace("http://", "")
            .rstrip("/")
        )
        conn = SiftConnectionConfig(
            api_key=self._api_key,
            grpc_url=grpc_host,
            rest_url=self._rest_uri,
            use_ssl=self._use_ssl,
        )
        self._client = SiftClient(connection_config=conn)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        uid = uuid.uuid4().hex[:8]
        run = RunCreate(
            name=f"{self._asset}.ha_typed.{stamp}-{uid}",
            client_key=f"{self._client_key}.run.{stamp}-{uid}",
        )
        # Start with empty flows; register per-entity on first send (additive).
        ingestion_config = IngestionConfigCreate(
            asset_name=self._asset,
            flows=[],
            client_key=self._client_key,
        )
        self._stream = await self._client.async_.ingestion.create_ingestion_config_streaming_client(
            ingestion_config=ingestion_config,
            run=run,
            streaming_mode=StreamingMode.LIVE_WITH_BACKUPS,
            enable_tls=self._use_ssl,
        )
        _LOGGER.info(
            "Typed IngestionConfig stream ready asset=%s client_key=%s",
            self._asset,
            self._client_key,
        )

    async def send(self, point: TypedPoint, resolved: ResolvedChannel) -> None:
        if self._stream is None or self._finished:
            raise RuntimeError("Typed backend not started or already stopped")

        fp = (resolved.entity_id, resolved.unit, resolved.data_type)
        existing = self._registered.get(resolved.entity_id)
        if existing is None:
            await self._register_flow(resolved)
            self._registered[resolved.entity_id] = fp
        elif existing != fp:
            _LOGGER.error(
                "Refusing typed send for %s: schema fingerprint changed "
                "%s → %s (bump client_key only after a deliberate migration; "
                "string→number/enum upgrades on existing channels are risky)",
                resolved.entity_id,
                existing,
                fp,
            )
            return

        flow_py = self._to_flow_py(point, resolved)
        # try_send is sync (non-blocking); do not await.
        self._stream.try_send(flow_py)

    async def stop(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._stream is not None:
            try:
                await self._stream.finish()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("typed stream finish() failed")
            self._stream = None
        self._client = None

    async def _register_flow(self, resolved: ResolvedChannel) -> None:
        from sift_client.sift_types.ingestion import (
            ChannelConfig,
            ChannelDataType,
            FlowConfig,
        )

        dtype_name = _DTYPE_TO_SIFT.get(resolved.data_type, "DOUBLE")
        dtype = getattr(ChannelDataType, dtype_name)
        channel = ChannelConfig(
            name=resolved.entity_id,
            data_type=dtype,
            unit=resolved.unit or None,
            description=resolved.description or None,
        )
        flow = FlowConfig(name=flow_name_for(resolved.entity_id), channels=[channel])
        await self._stream.add_new_flows([flow])
        _LOGGER.info(
            "Registered typed flow %s channel=%s unit=%r type=%s",
            flow.name,
            resolved.entity_id,
            resolved.unit,
            resolved.data_type,
        )

    def _to_flow_py(self, point: TypedPoint, resolved: ResolvedChannel):
        from sift_stream_bindings import (  # type: ignore
            ChannelValuePy,
            FlowPy,
            TimeValuePy,
            ValuePy,
        )

        value_py = _to_value_py(ValuePy, point.value, resolved.data_type)
        # Parse ISO timestamp → millis
        ts = point.timestamp
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        millis = int(dt.timestamp() * 1000)
        return FlowPy(
            flow_name=flow_name_for(resolved.entity_id),
            timestamp=TimeValuePy.from_timestamp_millis(millis),
            values=[
                ChannelValuePy(name=resolved.entity_id, value=value_py),
            ],
        )


def _to_value_py(ValuePy, raw: float | str | bool, data_type: str):
    if data_type == "bool" or isinstance(raw, bool):
        return ValuePy.Bool(bool(raw))
    if data_type == "string" or isinstance(raw, str):
        return ValuePy.String(str(raw))
    if data_type == "float":
        return ValuePy.Float(float(raw))
    if data_type == "int32":
        return ValuePy.Int32(int(raw))
    if data_type == "int64":
        return ValuePy.Int64(int(raw))
    return ValuePy.Double(float(raw))


class TypedIngestWorker:
    """Queue + single consumer for typed points (mirrors schemaless worker)."""

    def __init__(
        self,
        *,
        backend: TypedStreamBackend,
        allowlist: TypedChannelAllowlist,
        stats: dict[str, Any],
        queue_maxsize: int = 500,
    ) -> None:
        self._backend = backend
        self.allowlist = allowlist
        self.stats = stats
        self._queue: asyncio.Queue[TypedPoint] = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    def contains(self, entity_id: str) -> bool:
        return entity_id in self.allowlist

    def enqueue(self, point: TypedPoint) -> None:
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
                _LOGGER.warning(
                    "Typed ingest queue full; dropping point for %s",
                    point.spec.entity_id,
                )

    async def start(self) -> None:
        await self._backend.start()
        if self._task is None:
            self._stopped.clear()
            self._task = asyncio.create_task(
                self._run(), name="sift_typed_ingest_worker"
            )

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Drain remaining best-effort
        while True:
            try:
                point = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self._send_one(point)
        await self._backend.stop()

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                point = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            try:
                await self._send_one(point)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Typed ingest send failed for %s", point.spec.entity_id
                )
                self.stats["consecutive_failures"] = (
                    int(self.stats["consecutive_failures"]) + 1
                )
                self.stats["last_error"] = f"typed: {point.spec.entity_id}"

    async def _send_one(self, point: TypedPoint) -> None:
        resolved = resolve_channel(
            point.spec, value=point.value, attributes=point.attributes
        )
        await self._backend.send(point, resolved)
        self.stats["last_success"] = datetime.now(timezone.utc)
        self.stats["consecutive_failures"] = 0
        self.stats["auth_failed"] = False
        self.stats["last_error"] = None
