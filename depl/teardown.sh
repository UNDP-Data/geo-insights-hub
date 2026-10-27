#!/usr/bin/env bash
set -eo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"


echo "==> [1/5] Deleting Insights Hub..."
if [ -f "${ROOT_DIR}/hub/uninstall.sh" ]; then
  (cd "${ROOT_DIR}/hub" && ./uninstall.sh)
fi

echo "==> [4/5] Tearing down Gateway API"
if [ -d "${ROOT_DIR}/ingress/gateway" ]; then
  (cd "${ROOT_DIR}/ingress/gateway" && ./uninstall.sh)
fi

echo "==> [2/5] Tearing down OAuth..."
if [ -f "${ROOT_DIR}/oauth/uninstall.sh" ]; then
  (cd "${ROOT_DIR}/oauth" && ./uninstall.sh)
fi

echo "==> [3/5] Tearing down Cert-Manager..."
if [ -f "${ROOT_DIR}/cert/uninstall.sh" ]; then
  (cd "${ROOT_DIR}/cert" && ./uninstall.sh)
fi

echo "==> [4/5] Tearing down Cloud Provider KinD..."
if [ -d "${ROOT_DIR}/ingress/cloud-provider-kind" ]; then
  (cd "${ROOT_DIR}/ingress/cloud-provider-kind" && ./uninstall.sh)
fi




echo "==> [5/5] Deleting KinD Cluster..."
if [ -f "${ROOT_DIR}/cluster/delete.sh" ]; then
  (cd "${ROOT_DIR}/cluster" && ./delete.sh)
fi

echo "==> Teardown complete."