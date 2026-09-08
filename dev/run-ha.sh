#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
sudo docker rm -f hass-sift-test >/dev/null 2>&1 || true
sudo docker run -d \
  --name hass-sift-test \
  --restart unless-stopped \
  -p 8123:8123 \
  -e TZ=America/Los_Angeles \
  --add-host=host.docker.internal:host-gateway \
  -v "${ROOT}/dev/ha-config:/config" \
  ghcr.io/home-assistant/home-assistant:stable
echo "HA starting on http://localhost:8123"
