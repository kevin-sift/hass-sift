#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "${ROOT}/dev/ha-config/custom_components/sift"
cp -a "${ROOT}/custom_components/sift" "${ROOT}/dev/ha-config/custom_components/sift"
echo "synced sift → dev/ha-config/custom_components/sift"
