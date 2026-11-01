#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "${SCRIPT_DIR}"

if [ -f "${SCRIPT_DIR}/.env" ]; then
  set -a
  source "${SCRIPT_DIR}/.env"
  set +a
fi

export GATEWAY_NAME="${GATEWAY_NAME:-cluster-gateway}"
export GATEWAY_NAMESPACE="${GATEWAY_NAMESPACE:-default}"

echo "==> [gateway] Removing all HTTPRoutes and Gateway resources..."
kubectl delete httproutes.gateway.networking.k8s.io --all -A --ignore-not-found=true --timeout=10s 2>/dev/null || true
if [ -f "${SCRIPT_DIR}/gateway.yaml" ]; then
  envsubst < "${SCRIPT_DIR}/gateway.yaml" | kubectl delete -f - --ignore-not-found=true --timeout=10s 2>/dev/null || true
fi

echo "==> [gateway] Uninstalling Envoy Gateway Controller..."
helm uninstall "${GATEWAY_CLASS_NAME}" -n envoy-gateway-system --wait=false --ignore-not-found 2>/dev/null || true

# Force-terminate Envoy pods immediately (skips the 30-second termination grace period)
kubectl delete pods --all -n envoy-gateway-system --grace-period=0 --force --ignore-not-found=true 2>/dev/null || true
kubectl delete namespace envoy-gateway-system --ignore-not-found=true --timeout=20s 2>/dev/null || true

echo "==> [gateway] Removing Gateway API & Envoy CRDs..."
kubectl get crd -o name 2>/dev/null | grep -E 'gateway\.networking\.k8s\.io|gateway\.envoyproxy\.io' | xargs -r kubectl delete --ignore-not-found=true --timeout=15s 2>/dev/null || true

echo "==> [gateway] Teardown complete."
