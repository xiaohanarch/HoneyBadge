#!/bin/bash
# ============================================================
# Step 2b: Create ACR repos (run locally, once before first push)
# ACR namespace: honeybadge  |  Region: cn-hangzhou
# NOTE: Personal Edition requires manual repo creation
# ============================================================
# Install Alibaba Cloud CLI first: https://aliyun.com/cli
# aliyun configure  (enter your AccessKey ID + Secret + region=cn-hangzhou)
# ============================================================

REGION="cn-hangzhou"
NAMESPACE="honeybadge"

REPOS=(
  honeybadge-server
  honeybadge-auth
  honeybadge-permissions
  honeybadge-nebula-mcp
  honeybadge-audit-mcp
  honeybadge-cache-mcp
  honeybadge-frontend
)

echo "=== Creating ACR repos in namespace: $NAMESPACE ==="
for repo in "${REPOS[@]}"; do
  echo "Creating repo: $repo"
  aliyun cr CreateRepository \
    --RegionId "$REGION" \
    --RepoNamespace "$NAMESPACE" \
    --RepoName "$repo" \
    --RepoType PUBLIC \
    --Summary "HoneyBadge $repo" 2>/dev/null || echo "  (already exists or failed, skipping)"
done

echo ""
echo "=== All repos ready ==="
echo "Login command for Docker:"
echo "  docker login registry.cn-hangzhou.aliyuncs.com"
