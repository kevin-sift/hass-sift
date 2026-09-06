# Spike: schemaless vs ingestion-config streaming (units + enums)

Audience: Kevin / Limburg Home / hass-sift `integration` work.  
Date: 2026-09-06.

## Question

Can hass-sift forward HA `unit_of_measurement` / `device_class` and map string states (`on`/`off`, Tesla status, HVAC) to **real Sift ENUM channels** without breaking `entity_id` channel names?

## Short answer

| Need | Schemaless REST (`/api/v2/ingest`) | Ingestion-config streaming (gRPC) |
|---|---|---|
| Channel name = `entity_id` | Yes | Yes |
| number / bool / string values | Yes | Yes |
| Channel **unit** metadata | **No** | Yes (`ChannelConfig.unit`) |
| Channel **ENUM** type + named variants | **No** (strings only) | Yes (`data_type=ENUM` + `enum_types`) |
| Ops complexity | Low (current path) | Higher (register config + flows) |

Schemaless value types are only string | boolean | number. Units/enums live on **ChannelConfig**, which schemaless never sends.

## Options

### A — Stay schemaless (default)

- Rules keep using `$1 == 'on'` / `$1 == 'charging'`.
- Units: document HA-side conventions (limburghome_ha °F / pCi/L) or emit companion string channel `sensor.foo.__unit` = `"°F"` (does not make Explore treat the primary channel as dimensioned).
- Pros: no migration; matches today’s `limburghome_ha`.
- Cons: false alerts from unit confusion remain a doc/process problem; enums stay brittle strings.

### B — Hybrid allowlist → config streaming

- Keep schemaless for the long tail of entities.
- For an allowlist (binaries, Tesla status, temps with known UoM), maintain an ingestion config + flow and stream those channels with `unit` + ENUM definitions.
- Channel **names stay `entity_id`** so existing Explore bookmarks/rules keep working **if** the channel already exists as string — **risk:** type change string→enum on an existing channel may be rejected or fork a new series; needs a dry-run on dev.
- Pros: real units + enums where it matters (radon, doors, wall connector).
- Cons: dual pipelines; must sync allowlist with HA filter; gRPC client in the add-on.

### C — Calculated channels / UDFs in Sift

- Leave ingest as strings; define calculated channels that map `'on'`/`'off'` → bool or enum-like labels.
- Pros: no hass-sift transport change.
- Cons: doesn’t fix channel unit metadata; duplication per asset; doesn’t help schemaless Explore unit display.

## Recommendation

1. **Ship P0 health + canary on schemaless** (unblocks “HA up / Sift cold”).
2. **Do not block** on enums/units for that.
3. Next spike (half-day): try **one** allowlisted binary (`binary_sensor.kitchenfridgedoor_contact`) via ingestion-config ENUM on a **dev** asset (`hass_sift_local_test`) and see whether renaming/type-upgrade is clean. If clean → design hybrid B. If messy → stay A + companion `.__unit` + rule docs.
4. Dual-asset note: `LimburgHome` proxy already uses Device.metric / °C / bool wifi — don’t force parity; document which asset is source of truth per signal.

## Refs

- https://docs.siftstack.com/documentation/reference/stream/schemaless-ingestion-reference
- https://docs.siftstack.com/documentation/reference/stream/ingestion-config-streaming-reference
- Limburg seed: `hass-sift/dev/simulator/ha_sim_entities.json`
