#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PRODCERT_DIR="${SCRIPT_DIR}/prodcert"

if [ ! -f "${SCRIPT_DIR}/.env" ]; then
  echo "Error: Missing ${SCRIPT_DIR}/.env file." >&2
  exit 1
fi

# Load static variables from .env
set -a
source "${SCRIPT_DIR}/.env"
set +a

# Validate required variables
: "${CLOUDFLARE_API_TOKEN:?Environment variable CLOUDFLARE_API_TOKEN must be set}"
: "${ACME_EMAIL:?Environment variable ACME_EMAIL must be set}"
: "${BASE_DOMAIN:?Environment variable BASE_DOMAIN must be set}"

# Dynamically calculate environment-specific endpoints and resource names
export LE_ENV="${LE_ENV:-staging}"
if [ "${LE_ENV}" = "prod" ]; then
  export ACME_SERVER="https://acme-v02.api.letsencrypt.org/directory"
else
  export ACME_SERVER="https://acme-staging-v02.api.letsencrypt.org/directory"
fi

export CERT_NAME="wildcard-${BASE_DOMAIN//./-}-cert"
export CERT_SECRET_NAME="wildcard-${BASE_DOMAIN//./-}-tls"

# Function to check if a certificate is valid for at least 30 days (2592000 seconds)
is_cert_valid() {
  local cert_path="$1"
  if [[ ! -f "$cert_path" ]]; then
    return 1
  fi
  # Returns 0 if valid > 30 days, 1 if expiring sooner or invalid
  if openssl x509 -checkend 2592000 -noout -in "$cert_path" >/dev/null 2>&1; then
    return 0
  else
    return 1
  fi
}

echo "==> [cert] Adding Jetstack Helm repository..."
helm repo add jetstack https://charts.jetstack.io --force-update >/dev/null 2>&1
helm repo update jetstack

echo "==> [cert] Installing/Upgrading cert-manager..."
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true \
  --set "extraArgs={--enable-gateway-api,--dns01-recursive-nameservers-only,--dns01-recursive-nameservers=1.1.1.1:53\,8.8.8.8:53}" \
  --wait \
  --timeout=2m

echo "==> [cert] Verifying webhook readiness..."
kubectl rollout status deployment/cert-manager-webhook -n cert-manager --timeout=60s

echo "==> [cert] Creating Cloudflare API Token Secret..."
kubectl create secret generic cloudflare-api-token \
  --namespace cert-manager \
  --from-literal=api-token="${CLOUDFLARE_API_TOKEN}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> [cert] Applying ClusterIssuer for domain '${BASE_DOMAIN}'..."
envsubst < "${SCRIPT_DIR}/le-cluster-issuer.yaml" | kubectl apply -f -

# --- PRODCERT REUSE LOGIC BEGIN ---
USED_LOCAL_PROD_CERT=false
if [[ "${LE_ENV}" == "prod" ]]; then
  if is_cert_valid "${PRODCERT_DIR}/fullchain.pem" && [[ -f "${PRODCERT_DIR}/privkey.pem" ]]; then
    echo "==> [cert] Valid local production certificates found (>30 days validity)."
    echo "==> [cert] Pre-creating TLS secret '${CERT_SECRET_NAME}' to skip DNS challenge..."

    kubectl create secret tls "${CERT_SECRET_NAME}" \
      --namespace "${CERT_NAMESPACE}" \
      --cert="${PRODCERT_DIR}/fullchain.pem" \
      --key="${PRODCERT_DIR}/privkey.pem" \
      --dry-run=client -o yaml | kubectl apply -f -

    USED_LOCAL_PROD_CERT=true

    # CRITICAL: Wait for cert-manager's internal cache to register the new secret
    echo "==> [cert] Waiting 5 seconds for cert-manager to sync the secret..."
    sleep 5
  else
    echo "==> [cert] Local production certificates missing or expiring in < 30 days. Issuing new ones..."
  fi
fi
# --- PRODCERT REUSE LOGIC END ---

# --- CONDITIONAL CERTIFICATE APPLICATION ---
if [[ "${USED_LOCAL_PROD_CERT}" == "true" ]]; then
  echo "==> [cert] Skipping live certificate request; using local prodcert files."
else
  echo "==> [cert] Applying Certificate '${CERT_NAME}' in namespace '${CERT_NAMESPACE}'..."
  envsubst < "${SCRIPT_DIR}/cluster-wide-cert.yaml" | kubectl apply -f -

  echo "==> [cert] Waiting for certificate '${CERT_NAME}' to be provisioned..."
  echo "         (Since we need new certs, the DNS-01 challenge may take a few minutes.)"

  # 1. Wait for the certificate resource to be registered in the API
  while ! kubectl get certificate "${CERT_NAME}" -n "${CERT_NAMESPACE}" > /dev/null 2>&1; do
    sleep 2
  done

  # 2. Block until Ready
  if ! kubectl wait --for=condition=Ready "certificate/${CERT_NAME}" -n "${CERT_NAMESPACE}" --timeout=600s; then
    echo "ERROR: Certificate provisioning timed out after 10 minutes." >&2
    echo "Run 'kubectl describe challenge -A' to check for DNS-01 errors." >&2
    exit 1
  fi
fi

# --- LOCAL FOLDER SYNC LOGIC BEGIN ---
if [[ "${LE_ENV}" == "prod" ]] && [[ "${USED_LOCAL_PROD_CERT}" == "false" ]]; then
  echo "==> [cert] Syncing active cluster certificates back to ${PRODCERT_DIR}..."
  mkdir -p "${PRODCERT_DIR}"

  kubectl get secret "${CERT_SECRET_NAME}" -n "${CERT_NAMESPACE}" \
    -o go-template='{{ index .data "tls.crt" | base64decode }}' > "${PRODCERT_DIR}/fullchain.pem"

  kubectl get secret "${CERT_SECRET_NAME}" -n "${CERT_NAMESPACE}" \
    -o go-template='{{ index .data "tls.key" | base64decode }}' > "${PRODCERT_DIR}/privkey.pem"

  chmod 600 "${PRODCERT_DIR}/privkey.pem"
  echo "==> [cert] Local prodcert folder successfully updated!"
fi
# --- LOCAL FOLDER SYNC LOGIC END ---

echo "==> [cert] Certificate '${CERT_NAME}' is successfully provisioned and ready!"