"""Optional Home Assistant log → Sift string-channel forwarder."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .const import SIFT_LOGGER_PREFIX
from .ingest import IngestPoint

if TYPE_CHECKING:
    import asyncio

    from .ingest import IngestWorker

_LEVEL_BY_NAME = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|authorization|bearer|password|secret)\s*[:=]\s*\S+"
)


def parse_level(name: str) -> int:
    """Map config level name to logging level."""
    return _LEVEL_BY_NAME.get(name.upper(), logging.WARNING)


class SiftLogHandler(logging.Handler):
    """Forward selected log records into the ingest queue as strings."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        worker: IngestWorker,
        min_level: int,
        logger_prefixes: list[str],
        channel: str,
        max_message_length: int,
    ) -> None:
        super().__init__(level=min_level)
        self._loop = loop
        self._worker = worker
        self._logger_prefixes = logger_prefixes
        self._channel = channel
        self._max_message_length = max_message_length
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == SIFT_LOGGER_PREFIX or record.name.startswith(
            SIFT_LOGGER_PREFIX + "."
        ):
            return False
        if self._logger_prefixes:
            return any(
                record.name == prefix or record.name.startswith(prefix + ".")
                for prefix in self._logger_prefixes
            )
        return True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            message = _SECRET_RE.sub(r"\1=***", message)
            if len(message) > self._max_message_length:
                message = message[: self._max_message_length - 3] + "..."

            created = datetime.fromtimestamp(record.created, tz=timezone.utc)
            timestamp = created.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            point = IngestPoint(
                timestamp=timestamp,
                channel=self._channel,
                value=message,
            )

            if self._loop.is_closed():
                return

            self._loop.call_soon_threadsafe(self._worker.enqueue, point)
        except Exception:  # noqa: BLE001 — never raise from logging
            self.handleError(record)


def attach_log_handler(
    *,
    loop: asyncio.AbstractEventLoop,
    worker: IngestWorker,
    level_name: str,
    loggers: list[str],
    channel: str,
    max_message_length: int,
) -> SiftLogHandler:
    """Install handler on the root logger; returns handler for later detach."""
    handler = SiftLogHandler(
        loop=loop,
        worker=worker,
        min_level=parse_level(level_name),
        logger_prefixes=list(loggers),
        channel=channel,
        max_message_length=max_message_length,
    )
    logging.getLogger().addHandler(handler)
    return handler


def detach_log_handler(handler: SiftLogHandler | None) -> None:
    """Remove handler from the root logger if present."""
    if handler is None:
        return
    logging.getLogger().removeHandler(handler)
    handler.close()
