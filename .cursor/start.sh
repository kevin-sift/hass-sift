#!/usr/bin/env bash
#
# Cloud Agent per-boot start for hass-sift: bring up the Docker daemon so the
# dev/ full-local-HA harness can run. Idempotent; returns once dockerd is ready.
set -euo pipefail

if sudo docker info >/dev/null 2>&1; then
  echo "dockerd already running."
  exit 0
fi

sudo mkdir -p /etc/docker
echo '{"storage-driver":"fuse-overlayfs"}' | sudo tee /etc/docker/daemon.json >/dev/null

# Launch dockerd detached so it survives this start script returning.
sudo bash -c 'nohup dockerd >/var/log/dockerd.log 2>&1 &'

for _ in $(seq 1 30); do
  if sudo docker info >/dev/null 2>&1; then
    echo "dockerd ready."
    exit 0
  fi
  sleep 1
done

echo "ERROR: dockerd did not become ready in time; last log lines:" >&2
sudo tail -n 20 /var/log/dockerd.log >&2 || true
exit 1
