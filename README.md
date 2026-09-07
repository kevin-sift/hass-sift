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
- Runtime stats live at `hass.data["sift"]["stats"]` and are exposed as diagnostic entities (v0.4+): `last_success`, `consecutive_failures`, `dropped_points`, `queue_depth`, `auth_failed`, `last_error`.
- No recorder backfill — points missed while Sift/API was unreachable are not replayed.

## Technical Notes

* Prototype; manually installed. Future work: Config Flow / HACS.
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

### Health diagnostics + heartbeat canary (v0.4+)

Always creates diagnostic entities so HA (and Limburg Home) can see cold ingest while the HA UI still looks fine:

| Entity | Meaning |
|---|---|
| `binary_sensor.sift_ingest_ok` | `on` if last HTTP 200 within `health_stale_after` and auth OK; else `off` |
| `sensor.sift_last_success` | ISO timestamp of last successful POST |
| `sensor.sift_consecutive_failures` | int |
| `sensor.sift_queue_depth` | current queue depth |
| `sensor.sift_dropped_points` | cumulative drop-oldest overflows |

Optional heartbeat (off by default) toggles a canary entity on an interval **and** force-enqueues it through the same ingest queue (bypasses entity filter):

```yaml
sift:
  api_uri: https://<uri>/api/v2/ingest
  api_key: !secret sift_api_key
  asset: limburghome_ha
  health_stale_after: 300   # seconds without success → sift_ingest_ok off
  heartbeat:
    enabled: true
    interval: 60            # toggles binary_sensor.sift_heartbeat + forces ingest
```

Canary channel / entity: `binary_sensor.sift_heartbeat` (values `on`/`off`).

**Limburg Home validation**

1. Deploy `custom_components/sift/` (v0.4.0+) and enable `heartbeat.enabled: true`.
2. Confirm HA entities appear: `binary_sensor.sift_ingest_ok`, `sensor.sift_last_success`, `binary_sensor.sift_heartbeat`.
3. On asset `limburghome_ha`, channel `binary_sensor.sift_heartbeat` should update about every `interval` seconds.
4. Kill API key / block network → within ≤1–2 flush+backoff cycles, `binary_sensor.sift_ingest_ok` goes `off`; HA otherwise healthy.
5. Restore → sensor returns `on`; canary resumes without HA restart.
6. Existing channels keep the same `entity_id` names/types.

### Optional typed channels / Hybrid B (v0.6+)

Opt-in **IngestionConfig** streaming for an allowlisted set of entities (units + descriptions). The long tail stays on schemaless REST. Empty / omitted allowlist = **unchanged default**.

See [docs/hybrid-b-typed-channels.md](docs/hybrid-b-typed-channels.md) and the spike [docs/hass-sift-schemaless-vs-config-stream-2026-09-06.md](docs/hass-sift-schemaless-vs-config-stream-2026-09-06.md).

```yaml
sift:
  api_uri: https://<uri>/api/v2/ingest
  api_key: !secret sift_api_key
  asset: limburghome_ha          # dry-run: use a throwaway asset first
  ingestion_config:
    client_key: limburghome-ha-v1   # stable; do not bump casually
    # grpc_uri / rest_uri optional — derived from api_uri host when omitted
    typed_channels:
      - entity_id: sensor.office_temperature
        unit: °F
        description: Office temperature
        data_type: double
```

Notes:

* Channel names remain full `entity_id`. One flow per entity (`ha_typed.{entity_id}`).
* Requires `pip install 'sift-stack-py[sift-stream]'` in the HA env when typed_channels is non-empty (not a default manifest requirement).
* **Type-upgrade risk:** promoting an existing schemaless string channel to typed `DOUBLE`/`ENUM` on the same asset may be rejected or fork series — prefer a throwaway asset for dry-run; see docs.
