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

echo "==> [gateway] Removing Gateway resource..."
if [ -f "${SCRIPT_DIR}/gateway.yaml" ]; then
  envsubst < "${SCRIPT_DIR}/gateway.yaml" | kubectl delete -f - --ignore-not-found=true 2>/dev/null || true
fi


echo "==> [gateway] Removing Gateway API CRDs..."
kubectl get crd -o name 2>/dev/null | grep 'gateway.networking.k8s.io' | xargs -r kubectl delete --ignore-not-found=true


echo "==> [gateway] Uninstalling Envoy Gateway Controller..."
helm uninstall $GATEWAY_CLASS_NAME -n envoy-gateway-system --ignore-not-found 2>/dev/null || true
kubectl delete namespace envoy-gateway-system --ignore-not-found 2>/dev/null || true

echo "==> [gateway] Teardown complete."