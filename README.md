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

## Behavior (v0.2+)

- Listens to `state_changed`, channels named as full `entity_id` by default.
- Optional `channel_map` renames selected entity channels (v0.5.1+; opt-in; single-name, no dual-publish).
- Optional `forward_attributes` adds `{base}.{attr}` channels (v0.5+; opt-in; `base` respects `channel_map`).
- Skips `unknown` / `unavailable` / empty / removed entities.
- Uses **one** shared `aiohttp` session, a **bounded queue**, and a **single worker** that batches points into schemaless POSTs.
- Retries transient HTTP/network failures with exponential backoff. **Does not** retry 401/403 (sets `auth_failed` in stats).
- When the queue is full, **oldest** points are dropped (`dropped_points` counter).
- Runtime stats live at `hass.data["sift"]["stats"]` and are exposed as diagnostic entities (v0.4+): `last_success`, `consecutive_failures`, `dropped_points`, `queue_depth`, `auth_failed`, `last_error`.
- No recorder backfill — points missed while Sift/API was unreachable are not replayed.


### Optional attribute forwarding (v0.5+)

Opt-in only (default empty = unchanged). On each qualifying `state_changed`, selected entity **attributes** are also enqueued as separate schemaless channels, using the same ingest worker / queue / batch / backoff as state.

**Channel naming**

* Entity state: full `entity_id` by default, e.g. `climate.thermostat` (or `channel_map` rename)
* Attributes: `{base}.{attr}`, e.g. `climate.thermostat.hvac_action` (or mapped base)

**Allowlist** — list rules by exact `entity_id` **or** by `domain`, each with an `attributes` list:

```yaml
sift:
  api_uri: https://<uri>/api/v2/ingest
  api_key: !secret sift_api_key
  asset: limburghome_ha
  filter:
    include_domains:
      - climate
      - sensor
  forward_attributes:
    - entity_id: climate.thermostat
      attributes:
        - hvac_action
        - temperature
        - target_temp_high
        - target_temp_low
    # Or domain-wide (unioned with entity rules):
    # - domain: climate
    #   attributes:
    #     - hvac_action
```

Notes:

* Values are coerced like state (number / bool / string). `None`, `unknown`, `unavailable`, and empty strings are skipped.
* Attribute forwarding still requires the entity to pass `filter` and to have a usable state (same early exits as state ingest). Heartbeat is not double-enqueued.
* Prefer specific `entity_id` rules over broad `domain` lists to limit channel count.


### Optional channel map (v0.5.1+)

Rename selected Home Assistant `entity_id`s to dotted Sift channel names on asset ingest (e.g. Limburg Home → `limburghome_ha`). Opt-in only; empty / omitted map = today's behavior (channel = `entity_id`).

**Semantics (single-name resolve — no dual-publish)**

* State: `channel = channel_map.get(entity_id, entity_id)`
* Attributes: `base = channel_map.get(entity_id, entity_id)` then `{base}.{attr}`
* Unmapped entities (e.g. `weather.ksna`) keep their existing names without an entry

```yaml
sift:
  api_uri: https://<uri>/api/v2/ingest
  api_key: !secret sift_api_key
  asset: limburghome_ha
  channel_map:
    sensor.garagefridge_temperature: home.garage.fridge.temperature
    climate.thermostat: home.living.thermostat
  # forward_attributes still work; mapped bases apply:
  # climate.thermostat.hvac_action → home.living.thermostat.hvac_action
```

**House deploy notes**

* Adding a mapping changes the Sift channel name going forward; historical data under the old `entity_id` name is not rewritten.
* Prefer mapping only entities you care about in LHI / Limburg Home views; leave the rest unmapped.
* Empty mapped names are rejected by config validation.
* Heartbeat / log channels are unchanged by `channel_map` (they are not entity state ingest).

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
