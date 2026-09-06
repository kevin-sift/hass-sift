# Local hass-sift test harness (`integration` branch)

## Pieces
1. **mock Sift** — `python3 dev/mock_sift/server.py` → `:8765`, logs `dev/mock_sift/received.jsonl`
2. **Docker HA** — `./dev/run-ha.sh` → http://localhost:8123 with `custom_components/sift` mounted
3. **Limburg simulator** — `python3 dev/simulator/limburg_sim.py` posts representative entity_id channels (no live HA required)

## Closed-loop (no Kevin)
```bash
python3 dev/mock_sift/server.py &
./dev/run-ha.sh
# wait for HA; complete onboarding once if needed OR use simulator-only:
python3 dev/simulator/limburg_sim.py --ticks 30
tail -f dev/mock_sift/received.jsonl
```
