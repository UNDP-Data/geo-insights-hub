#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "${SCRIPT_DIR}"

# 1. Load configuration
if [ -f "${SCRIPT_DIR}/.env" ]; then
  set -a
  source "${SCRIPT_DIR}/.env"
  set +a
fi

#export CERT_SECRET_NAME="${CERT_SECRET_NAME:-wildcard-${BASE_DOMAIN//./-}-tls}"
#export GATEWAY_NAME="${GATEWAY_NAME:-cluster-gateway}"
#export GATEWAY_NAMESPACE="${GATEWAY_NAMESPACE:-default}"
#export GATEWAY_CLASS_NAME="${GATEWAY_CLASS_NAME:-eg}"

# 2. Install Envoy Gateway
echo "==> [gateway] Installing Envoy Gateway..."
# Clean up any leftover certgen jobs or admission secrets from previous failed runs in the SYSTEM namespace
kubectl delete job eg-gateway-helm-certgen -n envoy-gateway-system --ignore-not-found
kubectl delete secret eg-admission -n envoy-gateway-system --ignore-not-found

helm upgrade --install $GATEWAY_CLASS_NAME oci://docker.io/envoyproxy/gateway-helm \
  --version v0.0.0-latest \
  --namespace envoy-gateway-system \
  --create-namespace \
  --wait \
  --timeout 10m

# 3. Ensure CRDs are ready
echo "==> [gateway] Waiting for Gateway API CRDs to be registered..."
kubectl wait --for=condition=Established crd/gateways.gateway.networking.k8s.io --timeout=30s

# 4. Apply the Gateway
echo "==> [gateway] Applying Gateway '${GATEWAY_NAME}'..."
envsubst < "${SCRIPT_DIR}/gateway.yaml" | kubectl apply -f -

echo "==> [gateway] Waiting for Envoy to receive an IP from the cloud provider..."
sleep 5
kubectl get gateway -A