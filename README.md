# Sift Home Assistant Custom Component

Prototype custom component that ingests Home Assistant data into Sift's Hardware Observability Platform (https://siftstack.com/).

## Installation

Copy `custom_components/sift/` in this repo to `<config_dir>/custom_components/sift/` where `<config_dir>` is where your Home Assistant unique configurations are stored (for example where `configuration.yaml` is stored).

Once the custom component is installed, add the following to your `configuration.yaml`. Use the correct API URI, API key, and asset name for your Sift deployment. Prefer `!secret` for the API key.

```yaml
sift:
  api_uri: https://<uri>/api/v2/ingest
  api_key: !secret sift_api_key
  asset: my_hass_asset_name
```

### Filtering

```yaml
sift:
  api_uri: https://<uri>/api/v2/ingest
  api_key: !secret sift_api_key
  asset: my_hass_asset_name
  filter:
    include_domains:
      - sensor
    exclude_domains:
      - number
      - media_player
      - weather
      - todo
      - switch
```

An empty / omitted filter matches **all** entities. Prefer an include list to limit event volume.

### Optional ingest tuning (v0.2+)

All optional; defaults shown:

```yaml
sift:
  api_uri: https://<uri>/api/v2/ingest
  api_key: !secret sift_api_key
  asset: my_hass_asset_name
  flush_interval: 0.25      # seconds between batch flushes
  max_batch_points: 100     # max points per POST
  queue_maxsize: 2000       # bounded queue; drop-oldest when full
  max_retries: 5            # retries for 408/429/5xx/network
  backoff_base: 0.5         # seconds
  backoff_max: 30           # seconds
```

## Behavior (v0.2)

- Listens to `state_changed`, channels named as full `entity_id` (unchanged).
- Skips `unknown` / `unavailable` / empty / removed entities.
- Uses **one** shared `aiohttp` session, a **bounded queue**, and a **single worker** that batches points into schemaless POSTs.
- Retries transient HTTP/network failures with exponential backoff. **Does not** retry 401/403 (sets `auth_failed` in stats).
- When the queue is full, **oldest** points are dropped (`dropped_points` counter).
- Runtime stats live at `hass.data["sift"]["stats"]` (for a future health `binary_sensor`): `last_success`, `consecutive_failures`, `dropped_points`, `queue_depth`, `auth_failed`, `last_error`.
- No recorder backfill — points missed while Sift/API was unreachable are not replayed.

## Technical Notes

* Prototype; manually installed. Future work: health entities, Config Flow / HACS.
* Uses Sift [Schemaless Ingestion](https://docs.siftstack.com/documentation/reference/stream/schemaless-ingestion-reference). Enumerated string states show up as log/string data in Sift.

### Optional log forwarding (v0.3+)

Forward selected Home Assistant log lines to a Sift **string** channel (schemaless). Off by default. Uses the same ingest queue as state changes.

```yaml
sift:
  api_uri: https://<uri>/api/v2/ingest
  api_key: !secret sift_api_key
  asset: my_hass_asset_name
  forward_logs:
    enabled: true
    level: WARNING          # DEBUG | INFO | WARNING | ERROR | CRITICAL
    loggers: []             # empty = homeassistant.* tree (except custom_components.sift)
    # loggers:
    #   - homeassistant.components.http
    #   - custom_components
    channel: homeassistant.log
    max_message_length: 500
```

Notes:

* Values look like `WARNING homeassistant.core: Something happened`.
* Obvious `api_key` / `token` / `bearer` / `password` snippets are redacted to `***`.
* The component never forwards its own `custom_components.sift*` logs (recursion guard).
* Log volume can be high — prefer `WARNING`+ and a logger allowlist.
