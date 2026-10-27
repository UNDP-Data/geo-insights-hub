#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> [1/5] Creating KinD Cluster..."
(
  cd "${ROOT_DIR}/cluster"
  ./create.sh
)

echo "==> [2/5] Starting Cloud Provider KinD"
(
  cd "${ROOT_DIR}/ingress/cloud-provider-kind"
  ./install.sh
)

echo "==> [4/5] Installing Envoy  Gateway API..."
(
  cd "${ROOT_DIR}/ingress/gateway"
  ./install.sh

)


echo "==> [3/5] Installing Cert-Manager & Certificates..."
(
  cd "${ROOT_DIR}/cert"
  ./install.sh
)



echo "==> [4/5] Installing OAuth & Auth Routes..."
(
  cd "${ROOT_DIR}/oauth"
  ./install.sh

)



echo "==> [5/5] Installing Insights Hub..."
(
  cd "${ROOT_DIR}/hub"
  ./install.sh

)

echo "==> Installation complete! All services deployed."