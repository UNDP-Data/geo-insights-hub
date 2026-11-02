#!/bin/bash

# Determine the directory where this script resides
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Source the .env file relative to the script directory
. "$SCRIPT_DIR/.env"

echo "Deleting Marimo namespace and RBAC role"
kubectl delete -f "$SCRIPT_DIR/marimo-setup.yaml"

echo "Deleting KIND cluster: $CLUSTER_NAME..."
kind delete cluster --name $CLUSTER_NAME
kubectl config get-contexts
