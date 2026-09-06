"""Config and payload schemas for the Sift component."""

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entityfilter import FILTER_SCHEMA

from .const import (
    CONF_HEALTH_STALE_AFTER,
    CONF_HEARTBEAT,
    CONF_HEARTBEAT_ENABLED,
    CONF_HEARTBEAT_INTERVAL,
    DEFAULT_HEALTH_STALE_AFTER,
    DEFAULT_HEARTBEAT_ENABLED,
    DEFAULT_HEARTBEAT_INTERVAL,

    CONF_RUNS,
    CONF_RUNS_KEY_PREFIX,
    CONF_RUNS_MODE,
    CONF_RUNS_PERIOD,
    DEFAULT_RUNS_MODE,
    DEFAULT_RUNS_PERIOD,
    RUNS_MODE_NONE,
    RUNS_MODE_ROLLING,

    CONF_FORWARD_LOGS,
    CONF_LOGS_CHANNEL,
    CONF_LOGS_ENABLED,
    CONF_LOGS_LEVEL,
    CONF_LOGS_LOGGERS,
    CONF_LOGS_MAX_LENGTH,
    DEFAULT_LOGS_CHANNEL,
    DEFAULT_LOGS_ENABLED,
    DEFAULT_LOGS_LEVEL,
    DEFAULT_LOGS_MAX_LENGTH,
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
    DEFAULT_BACKOFF_BASE,
    DEFAULT_BACKOFF_MAX,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_MAX_BATCH_POINTS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_QUEUE_MAXSIZE,
    DOMAIN,
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_API_URI): cv.string,
                vol.Required(CONF_API_KEY): cv.string,
                vol.Required(CONF_ASSET): cv.string,
                vol.Optional(CONF_FILTER, default={}): FILTER_SCHEMA,
                vol.Optional(
                    CONF_FLUSH_INTERVAL, default=DEFAULT_FLUSH_INTERVAL
                ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=60)),
                vol.Optional(
                    CONF_MAX_BATCH_POINTS, default=DEFAULT_MAX_BATCH_POINTS
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
                vol.Optional(
                    CONF_QUEUE_MAXSIZE, default=DEFAULT_QUEUE_MAXSIZE
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=100000)),
                vol.Optional(
                    CONF_MAX_RETRIES, default=DEFAULT_MAX_RETRIES
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=20)),
                vol.Optional(
                    CONF_BACKOFF_BASE, default=DEFAULT_BACKOFF_BASE
                ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=60)),
                vol.Optional(
                    CONF_BACKOFF_MAX, default=DEFAULT_BACKOFF_MAX
                ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=600)),
                vol.Optional(
                    CONF_HEALTH_STALE_AFTER, default=DEFAULT_HEALTH_STALE_AFTER
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=86400)),
                vol.Optional(CONF_HEARTBEAT): vol.Schema(
                    {
                        vol.Optional(
                            CONF_HEARTBEAT_ENABLED, default=DEFAULT_HEARTBEAT_ENABLED
                        ): cv.boolean,
                        vol.Optional(
                            CONF_HEARTBEAT_INTERVAL, default=DEFAULT_HEARTBEAT_INTERVAL
                        ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                    }
                ),
                                vol.Optional(CONF_RUNS): vol.Schema(
                    {
                        vol.Optional(
                            CONF_RUNS_MODE, default=DEFAULT_RUNS_MODE
                        ): vol.In([RUNS_MODE_NONE, RUNS_MODE_ROLLING]),
                        vol.Optional(
                            CONF_RUNS_PERIOD, default=DEFAULT_RUNS_PERIOD
                        ): vol.Any(
                            vol.All(vol.Coerce(int), vol.Range(min=60, max=86400 * 30)),
                            cv.string,
                        ),
                        vol.Optional(CONF_RUNS_KEY_PREFIX): cv.string,
                    }
                ),
                vol.Optional(CONF_FORWARD_LOGS): vol.Schema(
                    {
                        vol.Optional(
                            CONF_LOGS_ENABLED, default=DEFAULT_LOGS_ENABLED
                        ): cv.boolean,
                        vol.Optional(
                            CONF_LOGS_LEVEL, default=DEFAULT_LOGS_LEVEL
                        ): vol.In(
                            ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
                        ),
                        vol.Optional(CONF_LOGS_LOGGERS, default=[]): vol.All(
                            cv.ensure_list, [cv.string]
                        ),
                        vol.Optional(
                            CONF_LOGS_CHANNEL, default=DEFAULT_LOGS_CHANNEL
                        ): cv.string,
                        vol.Optional(
                            CONF_LOGS_MAX_LENGTH, default=DEFAULT_LOGS_MAX_LENGTH
                        ): vol.All(vol.Coerce(int), vol.Range(min=50, max=4000)),
                    }
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

STATE_VALUE_SCHEMA = vol.Any(
    vol.All(vol.Coerce(float), lambda v: round(v, 2)),
    vol.Coerce(str),
    vol.Coerce(bool),
)

PAYLOAD_SCHEMA = vol.Schema(
    {
        vol.Required("asset_name"): str,
        vol.Optional("run_config"): vol.Schema(
            {
                vol.Required("client_key"): str,
                vol.Optional("name"): str,
            }
        ),
        vol.Required("data"): [
            {
                vol.Required("timestamp"): str,
                vol.Required("values"): [
                    {
                        vol.Required("channel"): str,
                        vol.Required("value"): STATE_VALUE_SCHEMA,
                    }
                ],
            }
        ],
    }
)
