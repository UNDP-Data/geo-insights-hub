#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
(
  cd "${ROOT_DIR}/"
  ./uninstall.sh
)
(
  cd "${ROOT_DIR}/"
  ./install.sh
)

