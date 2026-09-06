#!/usr/bin/env python3
"""Replay representative Limburg-like HA entity updates into schemaless ingest.

Does not require a live Home Assistant — exercises the same payload shape
hass-sift emits (channel = entity_id).
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from datetime import datetime, timezone

# Seeded from research dossier / known limburghome_ha channels.
ENTITIES = [
    ("sensor.kitchenfridge_temperature", "float", 38.0, 45.0),  # °F-ish
    ("sensor.garagefridge_temperature", "float", 35.0, 50.0),
    ("sensor.kitchenfridge_battery", "float", 15.0, 100.0),
    ("sensor.garagefridge_battery", "float", 15.0, 100.0),
    ("binary_sensor.kitchenfridgedoor_contact", "enum", ["Open", "Closed"], None),
    ("binary_sensor.garagefridgedoor_contact", "enum", ["Open", "Closed"], None),
    # dossier used KitchenFridgeDoor.contact style on Device asset; hass-sift uses entity_id
    ("sensor.teslawallconnector_wifi_wifi_connected", "bool", None, None),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sample_value(kind, a, b):
    if kind == "float":
        return round(random.uniform(a, b), 2)
    if kind == "enum":
        return random.choice(a)
    if kind == "bool":
        return random.choice([True, False])
    return str(a)


def post(uri: str, key: str, asset: str, channel: str, value) -> None:
    body = {
        "asset_name": asset,
        "data": [{"timestamp": now_iso(), "values": [{"channel": channel, "value": value}]}],
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


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--uri", default="http://127.0.0.1:8765/api/v2/ingest")
    p.add_argument("--api-key", default="local-test-key")
    p.add_argument("--asset", default="hass_sift_local_test")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--ticks", type=int, default=20)
    args = p.parse_args()

    # Hold last enum/bool so door isn't pure noise every tick
    state = {}
    for channel, kind, a, b in ENTITIES:
        state[channel] = sample_value(kind, a, b)

    for i in range(args.ticks):
        # Update a random subset each tick (change-only vibe)
        for channel, kind, a, b in random.sample(ENTITIES, k=min(3, len(ENTITIES))):
            if kind == "enum" and random.random() < 0.7:
                value = state[channel]  # often unchanged
            else:
                value = sample_value(kind, a, b)
                state[channel] = value
            post(args.uri, args.api_key, args.asset, channel, value)
            print(f"[{i}] {channel}={value}")
        # Occasional "door left open"
        if i == args.ticks // 2:
            door = "binary_sensor.kitchenfridgedoor_contact"
            post(args.uri, args.api_key, args.asset, door, "Open")
            print(f"[{i}] FORCE {door}=Open")
        time.sleep(args.interval)
    print("done")


if __name__ == "__main__":
    main()
