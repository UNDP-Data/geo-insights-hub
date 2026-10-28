#!/usr/bin/env bash
set -euo pipefail

# 1. Locate script directory and load environment variables if present
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    . "$SCRIPT_DIR/.env"
    set +a
else
    # Fallback defaults if .env is missing
    NAMESPACE="${NAMESPACE:-auth}"
    AUTH_SUBDOMAIN="${AUTH_SUBDOMAIN:-auth}"
    BASE_DOMAIN="${BASE_DOMAIN:-undpgeohub.org}"
fi

echo "==> Starting teardown of OAuth2 authentication resources..."

# 2. Delete Envoy Gateway routing resources in the default namespace
echo "==> Removing HTTPRoute for ${AUTH_SUBDOMAIN}.${BASE_DOMAIN}..."
kubectl delete httproute github-oauth-route -n default --ignore-not-found

# 3. Delete the auth namespace (this automatically cascades and destroys
#    the deployment, services, secrets, and ReferenceGrant inside it)
echo "==> Deleting namespace '${NAMESPACE}' and all internal resources..."
kubectl delete namespace "${NAMESPACE}" --ignore-not-found

echo "==> Teardown complete. All OAuth2 proxy and gateway components have been removed."