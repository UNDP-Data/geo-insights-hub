#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

# Source .env to retrieve target namespace
if [ -f "$SCRIPT_DIR/.env" ]; then
  # shellcheck source=/dev/null
  . "$SCRIPT_DIR/.env"
else
  echo "[-] Warning: .env not found at $SCRIPT_DIR/.env. Falling back to default namespace."
fi

NAMESPACE="${NAMESPACE:-default}"

echo "=================================================="
echo "==> Uninstalling OAuth2 Proxy & Associated Resources"
echo "=================================================="

echo "[*] Removing Helm release 'github-oauth' from namespace '${NAMESPACE}'..."
helm uninstall github-oauth -n "${NAMESPACE}" 2>/dev/null || true

echo "[*] Deleting Gateway API HTTPRoute from namespace '${NAMESPACE}'..."
kubectl delete httproute github-oauth-route -n "${NAMESPACE}" --ignore-not-found=true

echo "[*] Deleting cert-manager Certificate and TLS secret..."
kubectl delete certificate auth-cert -n default --ignore-not-found=true
kubectl delete secret auth-cert -n default --ignore-not-found=true
#deleteauth route
kubectl delete -f $SCRIPT_DIR/auth-route.yaml --ignore-not-found=true

# Optional: Prompt to purge the entire namespace if not default/kube-system
if [ "${NAMESPACE}" != "default" ] && [ "${NAMESPACE}" != "kube-system" ]; then
  kubectl delete namespace $NAMESPACE --ignore-not-found=true
fi



echo "==> Uninstallation complete."