#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

set -a
. "$SCRIPT_DIR/.env"
set +a



# 2. Render Helm values for OAuth2-Proxy
VARS_TO_SUBST='$NAMESPACE $OAUTH_CLIENT_ID $OAUTH_CLIENT_SECRET $OAUTH_COOKIE_KEY $OAUTH_ORG_NAME $OAUTH_TEAM_NAME $OAUTH2_PROXY_COOKIE_DOMAINS $OAUTH2_PROXY_WHITELIST_DOMAINS $AUTH_SUBDOMAIN $BASE_DOMAIN'
envsubst "$VARS_TO_SUBST" < "$SCRIPT_DIR/values.yaml" > "$SCRIPT_DIR/rendered-values.yaml"

# 3. Add & update Helm repo
helm repo add oauth2-proxy https://oauth2-proxy.github.io/manifests
helm repo update

echo "==> Deploying OAuth2-Proxy Helm release..."
helm upgrade --install github-oauth oauth2-proxy/oauth2-proxy \
  --namespace "${NAMESPACE}" \
  --create-namespace \
  -f "$SCRIPT_DIR/rendered-values.yaml"

rm -f "$SCRIPT_DIR/rendered-values.yaml"

# 4. Render and apply auth-route.yaml dynamically
echo "==> Applying HTTPRoute for ${AUTH_SUBDOMAIN}.${BASE_DOMAIN}..."
ROUTE_VARS='$GATEWAY_NAME $GATEWAY_NAMESPACE $AUTH_SUBDOMAIN $BASE_DOMAIN $NAMESPACE'
envsubst "$ROUTE_VARS" < "$SCRIPT_DIR/auth-route.yaml" | kubectl apply -f -


echo "==> oauth2-proxy installed successfully."