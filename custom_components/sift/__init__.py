"""Sift custom component for Home Assistant.

Ingests Home Assistant state changes into Sift (https://www.siftstack.com)
via schemaless REST, using a shared ClientSession, bounded queue, and batched
POSTs with retry/backoff. Optionally forwards selected log lines as a string
channel, exposes health diagnostics, and can emit a heartbeat canary.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    EVENT_STATE_CHANGED,
    Platform,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import discovery
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .binary_sensor import SiftHeartbeatBinarySensor
from .const import (
    CONF_API_KEY,
    CONF_API_URI,
    CONF_ASSET,
    CONF_BACKOFF_BASE,
    CONF_BACKOFF_MAX,
    CONF_FILTER,
    CONF_FLUSH_INTERVAL,
    CONF_FORWARD_LOGS,
    CONF_HEALTH_STALE_AFTER,
    CONF_HEARTBEAT,
    CONF_HEARTBEAT_ENABLED,
    CONF_HEARTBEAT_INTERVAL,
    CONF_LOGS_CHANNEL,
    CONF_LOGS_ENABLED,
    CONF_LOGS_LEVEL,
    CONF_LOGS_LOGGERS,
    CONF_LOGS_MAX_LENGTH,
    CONF_MAX_BATCH_POINTS,
    CONF_MAX_RETRIES,
    CONF_QUEUE_MAXSIZE,
    DATA_HEARTBEAT_ENTITY,
    DATA_LOG_HANDLER,
    DATA_SESSION,
    DATA_STATS,
    DATA_UNSUB,
    DATA_UNSUB_HEARTBEAT,
    DATA_WORKER,
    DEFAULT_BACKOFF_BASE,
    DEFAULT_BACKOFF_MAX,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_HEALTH_STALE_AFTER,
    DEFAULT_HEARTBEAT_ENABLED,
    DEFAULT_HEARTBEAT_INTERVAL,
    DEFAULT_LOGS_CHANNEL,
    DEFAULT_LOGS_ENABLED,
    DEFAULT_LOGS_LEVEL,
    DEFAULT_LOGS_MAX_LENGTH,
    DEFAULT_MAX_BATCH_POINTS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_QUEUE_MAXSIZE,
    DOMAIN,
    HEARTBEAT_ENTITY_ID,
)
from .ingest import IngestPoint, IngestWorker, empty_stats
from .logging_forward import attach_log_handler, detach_log_handler
from .schemas import CONFIG_SCHEMA, STATE_VALUE_SCHEMA

_LOGGER = logging.getLogger(__name__)

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
    health_stale_after = conf.get(CONF_HEALTH_STALE_AFTER, DEFAULT_HEALTH_STALE_AFTER)

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

    heartbeat: SiftHeartbeatBinarySensor | None = None
    hb_conf = conf.get(CONF_HEARTBEAT) or {}
    if hb_conf.get(CONF_HEARTBEAT_ENABLED, DEFAULT_HEARTBEAT_ENABLED):
        heartbeat = SiftHeartbeatBinarySensor()

    hass.data[DOMAIN] = {
        CONF_API_URI: api_uri,
        CONF_API_KEY: api_key,
        CONF_ASSET: asset,
        CONF_FILTER: entity_filter,
        CONF_HEALTH_STALE_AFTER: health_stale_after,
        DATA_SESSION: session,
        DATA_WORKER: worker,
        DATA_STATS: stats,
        DATA_LOG_HANDLER: None,
        DATA_HEARTBEAT_ENTITY: heartbeat,
        DATA_UNSUB_HEARTBEAT: None,
    }

    await worker.start()

    logs_conf = conf.get(CONF_FORWARD_LOGS) or {}
    if logs_conf.get(CONF_LOGS_ENABLED, DEFAULT_LOGS_ENABLED):
        handler = attach_log_handler(
            loop=hass.loop,
            worker=worker,
            level_name=logs_conf.get(CONF_LOGS_LEVEL, DEFAULT_LOGS_LEVEL),
            loggers=logs_conf.get(CONF_LOGS_LOGGERS, []),
            channel=logs_conf.get(CONF_LOGS_CHANNEL, DEFAULT_LOGS_CHANNEL),
            max_message_length=logs_conf.get(
                CONF_LOGS_MAX_LENGTH, DEFAULT_LOGS_MAX_LENGTH
            ),
        )
        hass.data[DOMAIN][DATA_LOG_HANDLER] = handler
        _LOGGER.info(
            "Sift log forwarding enabled → channel %s (level=%s)",
            logs_conf.get(CONF_LOGS_CHANNEL, DEFAULT_LOGS_CHANNEL),
            logs_conf.get(CONF_LOGS_LEVEL, DEFAULT_LOGS_LEVEL),
        )

    @callback
    def handle_event(event: Event) -> None:
        """Enqueue qualifying state changes (no I/O on the event bus)."""
        new_state: State | None = event.data.get("new_state")

        if new_state is None or new_state.state in (
            STATE_UNKNOWN,
            "",
            STATE_UNAVAILABLE,
            None,
        ):
            return

        # Heartbeat always passes the filter (canary must reach Sift).
        if new_state.entity_id != HEARTBEAT_ENTITY_ID and not entity_filter(
            new_state.entity_id
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

    # Diagnostic platforms (YAML discovery).
    hass.async_create_task(
        discovery.async_load_platform(
            hass, Platform.BINARY_SENSOR, DOMAIN, {}, config
        )
    )
    hass.async_create_task(
        discovery.async_load_platform(hass, Platform.SENSOR, DOMAIN, {}, config)
    )

    unsub_heartbeat = None
    if heartbeat is not None:
        interval = int(
            hb_conf.get(CONF_HEARTBEAT_INTERVAL, DEFAULT_HEARTBEAT_INTERVAL)
        )

        @callback
        def _heartbeat_tick(_now) -> None:
            heartbeat.toggle()
            if heartbeat.hass is not None:
                heartbeat.async_write_ha_state()
            # Force ingest even if state_changed is slow/missed.
            timestamp = (
                dt_util.utcnow()
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
            worker.enqueue(
                IngestPoint(
                    timestamp=timestamp,
                    channel=HEARTBEAT_ENTITY_ID,
                    value="on" if heartbeat.is_on else "off",
                )
            )

        unsub_heartbeat = async_track_time_interval(
            hass, _heartbeat_tick, timedelta(seconds=interval)
        )
        hass.data[DOMAIN][DATA_UNSUB_HEARTBEAT] = unsub_heartbeat
        _LOGGER.info(
            "Sift heartbeat enabled every %ss → %s", interval, HEARTBEAT_ENTITY_ID
        )

    async def _on_stop(_event: Event) -> None:
        detach_log_handler(hass.data.get(DOMAIN, {}).get(DATA_LOG_HANDLER))
        hb_unsub = hass.data.get(DOMAIN, {}).get(DATA_UNSUB_HEARTBEAT)
        if hb_unsub:
            hb_unsub()
        unsub_fn = hass.data.get(DOMAIN, {}).get(DATA_UNSUB)
        if unsub_fn:
            unsub_fn()
        await worker.stop()
        if not session.closed:
            await session.close()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)

    _LOGGER.info(
        "Sift ingest ready for asset %s (flush=%.2fs, batch=%s, queue=%s, stale=%ss)",
        asset,
        flush_interval,
        max_batch_points,
        queue_maxsize,
        health_stale_after,
    )
    return True
