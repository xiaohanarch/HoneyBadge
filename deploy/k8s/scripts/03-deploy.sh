#!/bin/bash
# ============================================================
# Step 3: Deploy all manifests to k3s (run on ECS)
# Prerequisite: 00-install-k3s.sh, 01-apply-secrets.sh, 02-setup-acr-pull-secret.sh done
# ============================================================
set -e

REPO_DIR="/opt/honeybadge"
BRANCH="ralph/k8s-deployment"

echo "=== Cloning/updating repo ==="
if [ -d "$REPO_DIR/.git" ]; then
  cd $REPO_DIR && git fetch origin && git checkout $BRANCH && git reset --hard origin/$BRANCH
else
  git clone -b $BRANCH https://github.com/xiaohanarch/HoneyBadge.git $REPO_DIR
  cd $REPO_DIR
fi

echo "=== Applying Kustomize manifests ==="
cd $REPO_DIR/deploy/k8s
kubectl apply -k .

echo "=== Waiting for NebulaGraph cluster ==="
kubectl -n honeybadge rollout status statefulset/nebula-metad --timeout=180s
kubectl -n honeybadge rollout status statefulset/nebula-storaged --timeout=180s
sleep 10
kubectl -n honeybadge rollout status deployment/nebula-graphd --timeout=180s

echo "=== Waiting for infra (Redis + PostgreSQL) ==="
kubectl -n honeybadge rollout status statefulset/redis --timeout=60s
kubectl -n honeybadge rollout status statefulset/postgres --timeout=60s

echo "=== Waiting for HiClaw Manager (this takes ~90s) ==="
kubectl -n honeybadge rollout status deployment/hiclaw-manager --timeout=300s

echo "=== Waiting for remaining services ==="
for deploy in honeybadge-server honeybadge-auth honeybadge-permissions \
              honeybadge-nebula-mcp honeybadge-audit-mcp honeybadge-cache-mcp frontend; do
  kubectl -n honeybadge rollout status deployment/${deploy} --timeout=120s || true
done

for deploy in hiclaw-graph-worker hiclaw-analytics-worker; do
  kubectl -n honeybadge rollout status deployment/${deploy} --timeout=180s || true
done

echo ""
echo "=== Deployment complete! ==="
kubectl -n honeybadge get pods -o wide
echo ""
echo "Access URLs:"
echo "  Frontend:    http://8.130.95.169      (Traefik Ingress port 80)"
echo "  Auth API:    http://8.130.95.169/auth/"
echo "  Matrix:      http://8.130.95.169:30167"
echo "  Element Web: http://8.130.95.169:30888"
echo ""
echo "Next step: run 04-init-nebula.sh"
