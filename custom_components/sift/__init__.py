"""Sift custom component for Home Assistant.

Ingests Home Assistant state changes into Sift (https://www.siftstack.com)
via schemaless REST, using a shared ClientSession, bounded queue, and batched
POSTs with retry/backoff.
"""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_API_KEY,
    CONF_API_URI,
    CONF_ASSET,
    CONF_BACKOFF_BASE,
    CONF_BACKOFF_MAX,
    CONF_FILTER,
    CONF_FLUSH_INTERVAL,
    CONF_MAX_BATCH_POINTS,
    CONF_MAX_RETRIES,
    CONF_QUEUE_MAXSIZE,
    DATA_SESSION,
    DATA_STATS,
    DATA_UNSUB,
    DATA_WORKER,
    DEFAULT_BACKOFF_BASE,
    DEFAULT_BACKOFF_MAX,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_MAX_BATCH_POINTS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_QUEUE_MAXSIZE,
    DOMAIN,
)
from .ingest import IngestPoint, IngestWorker, empty_stats
from .schemas import CONFIG_SCHEMA, STATE_VALUE_SCHEMA

_LOGGER = logging.getLogger(__name__)

# Re-export for Home Assistant config validation.
__all__ = ["CONFIG_SCHEMA", "async_setup"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Sift component."""
    conf = config[DOMAIN]
    entity_filter = conf.get(CONF_FILTER, {})

    api_uri = conf[CONF_API_URI]
    api_key = conf[CONF_API_KEY]
    asset = conf[CONF_ASSET]

    flush_interval = conf.get(CONF_FLUSH_INTERVAL, DEFAULT_FLUSH_INTERVAL)
    max_batch_points = conf.get(CONF_MAX_BATCH_POINTS, DEFAULT_MAX_BATCH_POINTS)
    queue_maxsize = conf.get(CONF_QUEUE_MAXSIZE, DEFAULT_QUEUE_MAXSIZE)
    max_retries = conf.get(CONF_MAX_RETRIES, DEFAULT_MAX_RETRIES)
    backoff_base = conf.get(CONF_BACKOFF_BASE, DEFAULT_BACKOFF_BASE)
    backoff_max = conf.get(CONF_BACKOFF_MAX, DEFAULT_BACKOFF_MAX)

    stats = empty_stats()
    timeout = aiohttp.ClientTimeout(total=30)
    session = aiohttp.ClientSession(timeout=timeout)

    worker = IngestWorker(
        session=session,
        api_uri=api_uri,
        api_key=api_key,
        asset=asset,
        stats=stats,
        flush_interval=flush_interval,
        max_batch_points=max_batch_points,
        queue_maxsize=queue_maxsize,
        max_retries=max_retries,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
    )

    hass.data[DOMAIN] = {
        CONF_API_URI: api_uri,
        CONF_API_KEY: api_key,
        CONF_ASSET: asset,
        CONF_FILTER: entity_filter,
        DATA_SESSION: session,
        DATA_WORKER: worker,
        DATA_STATS: stats,
    }

    await worker.start()

    @callback
    def handle_event(event: Event) -> None:
        """Enqueue qualifying state changes (no I/O on the event bus)."""
        new_state: State | None = event.data.get("new_state")

        if (
            new_state is None
            or new_state.state in (STATE_UNKNOWN, "", STATE_UNAVAILABLE, None)
            or not entity_filter(new_state.entity_id)
        ):
            return

        try:
            value = STATE_VALUE_SCHEMA(new_state.state)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Skipping un-coercible state for %s", new_state.entity_id)
            return

        timestamp = (
            dt_util.utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
        worker.enqueue(
            IngestPoint(
                timestamp=timestamp,
                channel=new_state.entity_id,
                value=value,
            )
        )

    unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, handle_event)
    hass.data[DOMAIN][DATA_UNSUB] = unsub

    async def _on_stop(_event: Event) -> None:
        unsub_fn = hass.data.get(DOMAIN, {}).get(DATA_UNSUB)
        if unsub_fn:
            unsub_fn()
        await worker.stop()
        if not session.closed:
            await session.close()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)

    _LOGGER.info(
        "Sift ingest ready for asset %s (flush=%.2fs, batch=%s, queue=%s)",
        asset,
        flush_interval,
        max_batch_points,
        queue_maxsize,
    )
    return True
