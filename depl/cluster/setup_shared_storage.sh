#!/bin/bash
# Determine the directory where this script resides
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source the .env file relative to the script directory
. "$SCRIPT_DIR/.env"
echo ${STORAGE_ACCOUNT_NAME}
echo ${STORAGE_ACCOUNT_KEY}
kubectl create secret generic azure-storage-secret \
  -n marimo \
  --from-literal=azurestorageaccountname=${STORAGE_ACCOUNT_NAME} \
  --from-literal=azurestorageaccountkey=${STORAGE_ACCOUNT_KEY}

echo "Creating shared PV&PVC"
kubectl apply -f "$SCRIPT_DIR/marimo-aks-shared-storage.yaml"

