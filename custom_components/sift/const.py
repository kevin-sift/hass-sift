"""Constants for Home Assistant Sift custom component."""

from typing import Final

DOMAIN = "sift"

CONF_API_KEY: Final = "api_key"
CONF_API_URI: Final = "api_uri"
CONF_ASSET: Final = "asset"
CONF_FILTER: Final = "filter"

CONF_FLUSH_INTERVAL: Final = "flush_interval"
CONF_MAX_BATCH_POINTS: Final = "max_batch_points"
CONF_QUEUE_MAXSIZE: Final = "queue_maxsize"
CONF_MAX_RETRIES: Final = "max_retries"
CONF_BACKOFF_BASE: Final = "backoff_base"
CONF_BACKOFF_MAX: Final = "backoff_max"

CONF_FORWARD_LOGS: Final = "forward_logs"
CONF_LOGS_ENABLED: Final = "enabled"
CONF_LOGS_LEVEL: Final = "level"
CONF_LOGS_LOGGERS: Final = "loggers"
CONF_LOGS_CHANNEL: Final = "channel"
CONF_LOGS_MAX_LENGTH: Final = "max_message_length"

CONF_HEALTH_STALE_AFTER: Final = "health_stale_after"
DEFAULT_HEALTH_STALE_AFTER: Final = 300  # seconds

CONF_HEARTBEAT: Final = "heartbeat"
CONF_HEARTBEAT_ENABLED: Final = "enabled"
CONF_HEARTBEAT_INTERVAL: Final = "interval"
DEFAULT_HEARTBEAT_ENABLED: Final = False
DEFAULT_HEARTBEAT_INTERVAL: Final = 60

DEFAULT_FLUSH_INTERVAL: Final = 0.25
DEFAULT_MAX_BATCH_POINTS: Final = 100
DEFAULT_QUEUE_MAXSIZE: Final = 2000
DEFAULT_MAX_RETRIES: Final = 5
DEFAULT_BACKOFF_BASE: Final = 0.5
DEFAULT_BACKOFF_MAX: Final = 30.0

DEFAULT_LOGS_ENABLED: Final = False
DEFAULT_LOGS_LEVEL: Final = "WARNING"
DEFAULT_LOGS_CHANNEL: Final = "homeassistant.log"
DEFAULT_LOGS_MAX_LENGTH: Final = 500

# Never forward our own logger (avoids recursion / feedback loops).
SIFT_LOGGER_PREFIX: Final = "custom_components.sift"

DATA_SESSION: Final = "session"
DATA_WORKER: Final = "worker"
DATA_STATS: Final = "stats"
DATA_UNSUB: Final = "unsub_state_changed"
DATA_LOG_HANDLER: Final = "log_handler"
DATA_HEARTBEAT_ENTITY: Final = "heartbeat_entity"
DATA_UNSUB_HEARTBEAT: Final = "unsub_heartbeat"

HEARTBEAT_ENTITY_ID: Final = "binary_sensor.sift_heartbeat"

# Opt-in attribute forwarding (schemaless channels: {entity_id}.{attr})
CONF_FORWARD_ATTRIBUTES: Final = "forward_attributes"
CONF_ATTR_ENTITY_ID: Final = "entity_id"
CONF_ATTR_DOMAIN: Final = "domain"
CONF_ATTR_ATTRIBUTES: Final = "attributes"
DEFAULT_FORWARD_ATTRIBUTES: Final = []
