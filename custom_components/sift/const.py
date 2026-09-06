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

DEFAULT_FLUSH_INTERVAL: Final = 0.25
DEFAULT_MAX_BATCH_POINTS: Final = 100
DEFAULT_QUEUE_MAXSIZE: Final = 2000
DEFAULT_MAX_RETRIES: Final = 5
DEFAULT_BACKOFF_BASE: Final = 0.5
DEFAULT_BACKOFF_MAX: Final = 30.0

DATA_SESSION: Final = "session"
DATA_WORKER: Final = "worker"
DATA_STATS: Final = "stats"
DATA_UNSUB: Final = "unsub_state_changed"
