#!/usr/bin/env bash
#
# Cloud Agent install for hass-sift.
#
# Provides two testing paths:
#   1. Unit tests  -> Python venv with pytest (tests/ under a stubbed HA)
#   2. Full local HA -> Docker + compose to run the dev/ harness (real HA
#      container ingesting into the mock Sift server), see dev/README.md
#
# Idempotent: safe to re-run. Runs after the repo is checked out.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

# --- System packages -------------------------------------------------------
# python3-venv: create the unit-test virtualenv (stock image lacks ensurepip)
# docker.io + docker-compose-v2: run full Home Assistant via dev/docker-compose.yml
# fuse-overlayfs: storage driver for Docker inside the nested Cloud Agent VM
# --force-conf* keeps this non-interactive: fuse3 ships /etc/fuse.conf and would
# otherwise block on a conffile prompt when the file already exists.
APT_OPTS=(-y -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef)
sudo apt-get update -qq
sudo apt-get install "${APT_OPTS[@]}" \
  python3-venv python3-pip \
  docker.io docker-compose-v2 \
  fuse-overlayfs uidmap iptables

# --- Docker daemon config (nested container) -------------------------------
# The Cloud Agent VM is itself a container; the default overlay2 driver is not
# usable, so pin fuse-overlayfs. The daemon itself is started by start.sh.
sudo mkdir -p /etc/docker
echo '{"storage-driver":"fuse-overlayfs"}' | sudo tee /etc/docker/daemon.json >/dev/null

# --- Python venv for unit tests -------------------------------------------
# Component imports voluptuous + aiohttp; tests use pytest + pytest-asyncio.
# (Full Home Assistant is provided by the Docker harness, not this venv.)
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install pytest pytest-asyncio voluptuous aiohttp

echo "install.sh complete: venv ready (.venv) and Docker installed."
