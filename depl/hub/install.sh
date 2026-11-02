#!/bin/bash
set -e

# Dynamically find the script's location and the repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
# Moves up two levels from depl/hub to reach the repo root
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." &> /dev/null && pwd)"

IMAGE_NAME="insights-hub:latest"
CLUSTER_NAME="insights"

echo "1. Building Docker image from repo root..."
# Passes the REPO_ROOT as the build context so it finds Dockerfile and src/
docker build --build-arg dev=true -t $IMAGE_NAME "$REPO_ROOT"

echo "2. Loading image into KinD cluster..."
kind load docker-image $IMAGE_NAME --name $CLUSTER_NAME

echo "3. Applying manifests..."
# Applies the manifest explicitly from the script's directory.
# This also guarantees the 'hub' namespace is created before we make the secret.
kubectl apply -f "$SCRIPT_DIR/insights-hub.yaml"

echo "4. Creating or updating Kubernetes Secret from .env..."
# Uses dry-run to generate the secret and apply it, preventing failures on subsequent script runs.
# (Adjust "$REPO_ROOT/.env" if your .env file is located somewhere else, like "$REPO_ROOT/src/.env")
if [ -f "$REPO_ROOT/.env" ]; then
    kubectl create secret generic hub-env --from-env-file="$REPO_ROOT/.env" -n hub --dry-run=client -o yaml | kubectl apply -f -
else
    echo "⚠️ Warning: .env file not found at $REPO_ROOT/.env. The secret was not created."
fi

echo "5. Restarting deployment..."
kubectl rollout restart deployment/insights-hub -n hub
kubectl rollout status deployment/insights-hub -n hub

echo "Deployment complete!"