#!/usr/bin/env python3
"""Replay representative limburghome_ha entity updates into schemaless ingest.

Seeded from Home Assistant agent export (Sift history), not invented Open/Closed
enums. Channel = HA entity_id. binary_sensor states are on/off strings.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SEED_JSON = Path(__file__).resolve().parent / "ha_sim_entities.json"


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def load_entities(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return list(data.get("entities") or [])


def sample_value(ent: dict, previous):
    dtype = ent.get("dtype") or "string"
    if dtype == "float":
        if ent.get("example_values"):
            # rare sensors: usually hold steady
            if previous is not None and random.random() < 0.9:
                return previous
            return random.choice(ent["example_values"])
        lo, hi = ent.get("example_range") or [0.0, 1.0]
        if previous is not None and random.random() < 0.3:
            # small jitter around previous
            span = max(hi - lo, 1e-6)
            return round(min(hi, max(lo, previous + random.uniform(-0.05, 0.05) * span)), 2)
        return round(random.uniform(lo, hi), 2)
    if dtype == "string" and ent.get("domain") == "binary_sensor":
        # on/off — prefer off (closed / clear), occasional on
        if previous is None:
            return "off"
        if previous == "on":
            return "off" if random.random() < 0.7 else "on"
        return "on" if random.random() < 0.15 else "off"
    if dtype == "string":
        vals = ent.get("example_values") or ["unknown"]
        if previous is not None and random.random() < 0.85:
            return previous
        return random.choice(vals)
    return previous if previous is not None else "unknown"


def post(uri: str, key: str, asset: str, channel: str, value) -> None:
    body = {
        "asset_name": asset,
        "data": [
            {
                "timestamp": now_iso(),
                "values": [{"channel": channel, "value": value}],
            }
        ],
    }
    req = urllib.request.Request(
        uri,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def change_weight(ent: dict) -> float:
    rate = (ent.get("change_rate") or "").lower()
    if "frequent" in rate:
        return 3.0
    if "moderate" in rate:
        return 1.5
    if "bursty" in rate:
        return 1.2
    if "slow" in rate:
        return 0.4
    if "rare" in rate or "very rare" in rate:
        return 0.15
    return 1.0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--uri", default="http://127.0.0.1:8765/api/v2/ingest")
    p.add_argument("--api-key", default="local-test-key")
    p.add_argument("--asset", default="hass_sift_local_test")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--ticks", type=int, default=20)
    p.add_argument("--seed-json", type=Path, default=SEED_JSON)
    args = p.parse_args()

    entities = load_entities(args.seed_json)
    if not entities:
        raise SystemExit(f"no entities in {args.seed_json}")

    state = {e["entity_id"]: sample_value(e, None) for e in entities}
    weights = [change_weight(e) for e in entities]

    for i in range(args.ticks):
        k = min(4, len(entities))
        chosen = random.choices(entities, weights=weights, k=k)
        # unique by entity_id
        seen = set()
        for ent in chosen:
            eid = ent["entity_id"]
            if eid in seen:
                continue
            seen.add(eid)
            value = sample_value(ent, state[eid])
            state[eid] = value
            post(args.uri, args.api_key, args.asset, eid, value)
            print(f"[{i}] {eid}={value}")
        # Forced door-open burst mid-run (binary_sensor on)
        if i == max(1, args.ticks // 2):
            door = "binary_sensor.kitchenfridgedoor_contact"
            if door in state:
                post(args.uri, args.api_key, args.asset, door, "on")
                state[door] = "on"
                print(f"[{i}] FORCE {door}=on")
        time.sleep(args.interval)
    print(f"done ({len(entities)} seed entities)")


if __name__ == "__main__":
    main()
