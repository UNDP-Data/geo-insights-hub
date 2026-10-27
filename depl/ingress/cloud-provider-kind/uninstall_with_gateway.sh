#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "${SCRIPT_DIR}"

# 1. Load environment variables for accurate manifest rendering during deletion
if [ -f "${SCRIPT_DIR}/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/.env"
  set +a
fi

export GATEWAY_NAME="${GATEWAY_NAME:-cluster-gateway}"
export GATEWAY_NAMESPACE="${GATEWAY_NAMESPACE:-default}"
export CERT_SECRET_NAME="${CERT_SECRET_NAME:-wildcard-undpgeohub-org-tls}"

echo "==> [ingress] Removing Ingress / Gateway resources..."

# 2. Delete optional demo app if present
if [ -f "${SCRIPT_DIR}/demo-app.yaml" ]; then
  if command -v envsubst >/dev/null 2>&1; then
    envsubst < "${SCRIPT_DIR}/demo-app.yaml" | kubectl delete -f - --ignore-not-found=true 2>/dev/null || true
  else
    kubectl delete -f "${SCRIPT_DIR}/demo-app.yaml" --ignore-not-found=true 2>/dev/null || true
  fi
fi

# 3. Delete Gateway resource (clean up routes/listeners before killing the controller)
if [ -f "${SCRIPT_DIR}/gateway.yaml" ]; then
  if command -v envsubst >/dev/null 2>&1; then
    envsubst < "${SCRIPT_DIR}/gateway.yaml" | kubectl delete -f - --ignore-not-found=true 2>/dev/null || true
  else
    kubectl delete -f "${SCRIPT_DIR}/gateway.yaml" --ignore-not-found=true 2>/dev/null || true
  fi
else
  # Direct fallback if manifest was moved or deleted
  kubectl delete gateway "${GATEWAY_NAME}" -n "${GATEWAY_NAMESPACE}" --ignore-not-found=true 2>/dev/null || true
fi

echo "==> [ingress] Removing Gateway API CRDs..."
kubectl get crd -o name 2>/dev/null | grep 'gateway.networking.k8s.io' | xargs -r kubectl delete --ignore-not-found=true

# 4. Stop and wipe the cloud-provider-kind docker compose stack
if [ -f "${SCRIPT_DIR}/docker-compose-gateway.yaml" ]; then
  echo "==> [ingress] Stopping cloud-provider-kind container via docker compose..."
  docker compose -f "${SCRIPT_DIR}/docker-compose-gateway.yaml" down -v --remove-orphans
fi

echo "==> [ingress] Teardown complete."