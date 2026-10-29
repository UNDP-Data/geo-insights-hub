#!/usr/bin/env bash
set -euo pipefail

# 1. Locate script directory and load environment variables
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    . "$SCRIPT_DIR/.env"
    set +a
else
    echo "Error: .env file not found in $SCRIPT_DIR" >&2
    exit 1
fi

echo "==> Deploying standalone oauth2-proxy to namespace '${NAMESPACE}'..."

# 2. Define all variables needed for envsubst across the standalone manifest
EXPORTED_VARS='${NAMESPACE} ${OAUTH_CLIENT_ID} ${OAUTH_CLIENT_SECRET} ${OAUTH_COOKIE_KEY} ${OAUTH_ORG_NAME} ${OAUTH_TEAM_NAME} ${OAUTH2_PROXY_COOKIE_DOMAINS} ${OAUTH2_PROXY_WHITELIST_DOMAINS} ${OAUTH2_PROXY_EMAIL_DOMAINS} ${AUTH_SUBDOMAIN} ${BASE_DOMAIN}'

# 3. Render and apply the standalone manifest directly to kubectl
envsubst "$EXPORTED_VARS" < "$SCRIPT_DIR/oauth.yaml" | kubectl apply -f -

echo "==> oauth2-proxy and Envoy Gateway route applied successfully for https://${AUTH_SUBDOMAIN}.${BASE_DOMAIN}"