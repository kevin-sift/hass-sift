# Local hass-sift test harness

## Pieces
1. **mock Sift** — `python3 dev/mock_sift/server.py` → `:8765`, logs `dev/mock_sift/received.jsonl`
2. **Docker HA** — `./dev/run-ha.sh` (or `dev/docker-compose.yml`) → http://localhost:8123 with `custom_components/sift` mounted
3. **Limburg simulator** — `python3 dev/simulator/limburg_sim.py` posts representative entity_id channels (no live HA required)

## Closed-loop (no Kevin)
```bash
python3 dev/mock_sift/server.py &
./dev/run-ha.sh
# wait for HA; complete onboarding once if needed OR use simulator-only:
python3 dev/simulator/limburg_sim.py --ticks 30
tail -f dev/mock_sift/received.jsonl
```

## Cloud Agent (Cursor) full-HA dry-run

The Cloud Agent environment (`.cursor/environment.json`) already installs Docker
+ Compose and a Python venv, and starts the Docker daemon on boot — no real Sift
API key is needed for this path (the mock is enough).

```bash
# 1. Copy the component under test into the HA config dir (creates parent if missing)
./dev/sync-component.sh

# 2. Start the mock Sift ingest server (host :8765, writes received.jsonl)
python3 dev/mock_sift/server.py &

# 3. Bring up Home Assistant in Docker (mounts dev/ha-config, publishes :8123)
sudo docker compose -f dev/docker-compose.yml up -d
#    (equivalently: ./dev/run-ha.sh)

# 4. Watch the component load and ingest reach the mock
sudo docker logs -f hass-sift-test | grep -i sift      # "Sift ingest ready ..."
tail -f dev/mock_sift/received.jsonl                    # canary / heartbeat / log channels
```

The bundled `dev/ha-config/configuration.yaml` auto-toggles
`input_boolean.sift_canary` every 15s and enables the heartbeat canary, so a
filtered `state_changed`, the heartbeat, and a forwarded log line all reach the
mock without any HA onboarding or manual UI clicks.

If `dockerd` is not running (e.g. after a manual stop), re-run `bash
.cursor/start.sh`.

### Typed / Hybrid-B ingest (needs secrets, later)

The typed gRPC "runs:" ingest config is commented out in
`dev/ha-config/configuration.yaml`: it requires the `integration`-branch
component plus a real Sift deployment (gRPC endpoint + API key), so it is not
part of the default mock dry-run.
