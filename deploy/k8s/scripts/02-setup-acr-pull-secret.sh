#!/bin/bash
# ============================================================
# Step 2: Configure ACR pull secret on k3s
# Run on ECS after k3s install
# ACR: registry.cn-hangzhou.aliyuncs.com/honeybadge
# ============================================================
set -e

NAMESPACE="honeybadge"
ACR_REGISTRY="registry.cn-hangzhou.aliyuncs.com"
# ACR credentials — set via env vars or interactive prompt
# Export before running: export ACR_USER="..." ACR_PASS="..."
ACR_USER="${ACR_USER:-}"
ACR_PASS="${ACR_PASS:-}"

if [ -z "$ACR_USER" ]; then
  echo "Enter your Alibaba Cloud ACR username:"
  read -r ACR_USER
fi
if [ -z "$ACR_PASS" ]; then
  echo "Enter your ACR password:"
  read -rs ACR_PASS
fi

echo ""
echo "=== Creating ACR pull secret ==="
kubectl -n $NAMESPACE create secret docker-registry acr-pull-secret \
  --docker-server="$ACR_REGISTRY" \
  --docker-username="$ACR_USER" \
  --docker-password="$ACR_PASS" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "=== Patching default ServiceAccount to use pull secret ==="
kubectl -n $NAMESPACE patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "acr-pull-secret"}]}'

echo ""
echo "=== ACR pull secret configured ==="
echo "Next step: push images to ACR, then run 03-deploy.sh"
