#!/bin/bash
# ============================================================
# Step 4: Initialize NebulaGraph schema (run on ECS, once)
# ============================================================
set -e

echo "=== Running NebulaGraph init Job ==="
kubectl apply -f /opt/honeybadge/deploy/k8s/jobs/init-nebula.yaml

echo "=== Waiting for init-nebula Job to complete ==="
kubectl -n honeybadge wait --for=condition=complete job/init-nebula --timeout=300s

echo "=== NebulaGraph schema initialized ==="
kubectl -n honeybadge logs job/init-nebula
