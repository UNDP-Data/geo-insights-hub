#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "${SCRIPT_DIR}"

# 1. Load domain/gateway configuration
if [ -f "${SCRIPT_DIR}/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/.env"
  set +a
fi

export CERT_SECRET_NAME="${CERT_SECRET_NAME:-wildcard-${BASE_DOMAIN//./-}-tls}"

# 2. Launch cloud-provider-kind via docker compose
echo "==> [ingress] Starting Cloud Provider KinD (Gateway mode)..."
docker compose  -f docker-compose-gateway.yaml up -d

# 3. Wait for the cloud-provider-kind container to install the Gateway API CRDs
echo "==> [ingress] Waiting for Gateway API CRDs to be registered..."
until kubectl get crd gateways.gateway.networking.k8s.io >/dev/null 2>&1; do
  sleep 1
done
kubectl wait --for=condition=Established crd/gateways.gateway.networking.k8s.io --timeout=30s

# 4. Apply the parameterized Gateway resource
echo "==> [ingress] Applying Gateway '${GATEWAY_NAME}'..."
envsubst < "${SCRIPT_DIR}/gateway.yaml" | kubectl apply -f -
kubectl get gateway -A