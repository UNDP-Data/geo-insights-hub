#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "${SCRIPT_DIR}"

echo "==> [cloud-provider] Starting Cloud Provider KinD (LoadBalancer mode only)..."
docker compose up -d --force-recreate