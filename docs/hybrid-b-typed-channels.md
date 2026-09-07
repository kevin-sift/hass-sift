# Hybrid B — typed allowlist via IngestionConfig (v0.6)

**Status:** vertical slice landed on `feature/hybrid-b-typed-ingestion-config`  
**Spike:** [hass-sift-schemaless-vs-config-stream-2026-09-06.md](./hass-sift-schemaless-vs-config-stream-2026-09-06.md)  
**Sibling:** PR #5 (`feature/forward-attributes`, v0.5.0) is separate — this branch is from `main` so the PRs stay stackable.

## What shipped

| Path | When | Transport | Units / enums |
|---|---|---|---|
| Schemaless REST `/api/v2/ingest` | Default; all non-allowlisted entities | Existing `IngestWorker` | No |
| IngestionConfig streaming (gRPC) | `ingestion_config.typed_channels` non-empty | `sift_client.IngestionConfigStreamingClient` | Yes (`ChannelConfig.unit` + description) |

- Channel **names stay full `entity_id`**.
- One flow per allowlisted entity: `ha_typed.{entity_id}` (additive via `add_new_flows`; no reorder of siblings).
- Stable `client_key` default: **`limburghome-ha-v1`** (do **not** bump unless incompatible schema break).
- Empty / omitted `typed_channels` → **zero behavior change** (no `sift_client` import).

## How to enable (one temp sensor °F)

```yaml
sift:
  api_uri: https://<host>/api/v2/ingest
  api_key: !secret sift_api_key
  asset: limburghome_ha   # or hass_sift_local_test for dry-run
  filter:
    include_domains:
      - sensor
  ingestion_config:
    client_key: limburghome-ha-v1
    # Optional overrides — otherwise derived from api_uri host
    # grpc_uri: <host>:443
    # rest_uri: https://<host>
    typed_channels:
      - entity_id: sensor.office_temperature
        # unit / description optional; defaults from HA attributes:
        # unit_of_measurement → device_class map → ""
        # friendly_name → entity_id
        unit: °F
        description: Office temperature
        data_type: double
```

**Dependency (typed path only):** install in the HA environment:

```bash
pip install 'sift-stack-py[sift-stream]'
```

Not listed in `manifest.json` `requirements` so schemaless-only installs stay light (no native `sift-stream-bindings` wheel). If typed is configured but the package is missing, setup logs an error and **falls back to schemaless** for those entities.

## Unit resolution order

1. YAML `unit:` override  
2. HA `attributes.unit_of_measurement`  
3. Small `device_class` fallback map (`temperature`→`°C`, `humidity`→`%`, …)  
4. Empty string

## Dry-run / type-upgrade risks (honest)

Schemaless has been writing many `limburghome_ha` channels as **string | number | bool** without a registered `ChannelConfig`. Turning the **same** `entity_id` into a typed `DOUBLE`/`ENUM` under IngestionConfig may:

- be rejected by Sift,
- fork a second series, or
- otherwise behave unexpectedly.

**Recommendation before production:**

1. Dry-run on a **throwaway asset** (`hass_sift_local_test`) with one allowlisted temp sensor.  
2. Prefer **additive** typed channels on a fresh asset rather than in-place string→number/enum upgrades on `limburghome_ha`.  
3. If you must upgrade an existing channel, treat it as an incompatible contract break: bump `client_key` (e.g. `limburghome-ha-v2`) only after validating Explore/rules, and expect bookmarks/rules may need retargeting.  
4. This component’s schema guard refuses **unit/type changes** on an already-registered typed channel within a process lifetime (loud error, drop send) — it does not auto-rekey.

## Architecture for expansion

- `typed_channels.py` — allowlist + unit/description/data_type resolution  
- `typed_ingest.py` — `TypedStreamBackend` protocol, `SiftClientTypedBackend`, `TypedIngestWorker` queue  
- `__init__.py` — routes allowlisted `state_changed` to typed worker; else schemaless  
- Future: ENUM variants for binaries / Tesla status; companion attribute channels (PR #5) remain schemaless unless separately allowlisted

## Refs

- https://docs.siftstack.com/documentation/reference/stream/ingestion-config-streaming-reference  
- https://docs.siftstack.com/documentation/reference/stream/schemaless-ingestion-reference  
- Limburg Home sift_client patterns: `limburg-home-ingest` `ingest/sift_stream.py` + client_key note
