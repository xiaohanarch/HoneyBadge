#!/bin/bash
# HoneyBadge Worker Initialization Script
# Run this ONCE after first `docker compose up -d` to register HiClaw Workers.
#
# What it does:
#   1. Copies worker SOUL.md files into HiClaw Manager's MinIO-accessible filesystem
#   2. Calls create-worker.sh for each worker (inside Manager container)
#      → creates Matrix user accounts in Tuwunel
#      → creates Higress consumer entries
#      → generates openclaw.json in MinIO (workers need this to start)
#   3. Creates the honeybadge-gateway Matrix account (used by honeybadge-server)
#   4. Registers HoneyBadge MCP servers in Higress AI Gateway
#
# After this script succeeds, workers will start on next restart (they keep
# retrying with restart: unless-stopped until their MinIO config exists).
#
# Usage:
#   cd deploy/docker && docker compose up -d
#   # Wait ~60s for hiclaw-manager to become healthy
#   bash ../../deploy/hiclaw/init-workers.sh
#
# Re-run after: docker compose down -v (data volumes wiped)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MANAGER_CONTAINER="${MANAGER_CONTAINER:-honeybadge-hiclaw-manager}"
REG_TOKEN="${HICLAW_REGISTRATION_TOKEN:-honeybadge-reg-token}"
MATRIX_DOMAIN="${HICLAW_MATRIX_DOMAIN:-matrix-local.hiclaw.io}"
GATEWAY_PASSWORD="${MATRIX_GATEWAY_PASSWORD:-gateway-dev-pass}"

# ANSI colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[init]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
die()  { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Verify Manager container is running and healthy
# ---------------------------------------------------------------------------
log "Checking HiClaw Manager container..."
if ! docker inspect "$MANAGER_CONTAINER" &>/dev/null; then
    die "Container '$MANAGER_CONTAINER' not found. Run 'docker compose up -d' first."
fi

STATUS=$(docker inspect --format='{{.State.Status}}' "$MANAGER_CONTAINER")
if [ "$STATUS" != "running" ]; then
    die "Container '$MANAGER_CONTAINER' is not running (status: $STATUS)."
fi

log "Waiting for MinIO to be ready inside Manager..."
RETRIES=20
until docker exec "$MANAGER_CONTAINER" curl -sf http://localhost:9000/minio/health/live &>/dev/null; do
    RETRIES=$((RETRIES - 1))
    if [ "$RETRIES" -eq 0 ]; then
        die "MinIO is not ready after waiting. Check: docker logs $MANAGER_CONTAINER"
    fi
    echo -n "."
    sleep 5
done
echo ""
log "MinIO is ready."

# ---------------------------------------------------------------------------
# 2. Upload worker SOUL.md files into MinIO via mc (inside Manager container)
#    MinIO bucket path: hiclaw-storage/agents/{WORKER_NAME}/SOUL.md
#    The mc alias 'hiclaw' is pre-configured by start-mc-mirror.sh
# ---------------------------------------------------------------------------
log "Uploading worker SOUL.md files to MinIO..."

for worker in graph-worker analytics-worker; do
    SOUL_SRC="$PROJECT_ROOT/hiclaw/workers/$worker/agent/SOUL.md"
    # Copy SOUL.md into manager's tmp, then upload to MinIO via mc
    docker cp "$SOUL_SRC" "$MANAGER_CONTAINER:/tmp/${worker}-SOUL.md"
    docker exec "$MANAGER_CONTAINER" bash -c \
        "mc cp /tmp/${worker}-SOUL.md hiclaw/hiclaw-storage/agents/${worker}/SOUL.md"
    log "  → ${worker}/SOUL.md uploaded to MinIO"

    # Upload skills if they exist
    SKILLS_DIR="$PROJECT_ROOT/hiclaw/workers/$worker/agent/skills"
    if [ -d "$SKILLS_DIR" ]; then
        docker cp "$SKILLS_DIR" "$MANAGER_CONTAINER:/tmp/${worker}-skills"
        docker exec "$MANAGER_CONTAINER" bash -c \
            "mc mirror /tmp/${worker}-skills/ hiclaw/hiclaw-storage/agents/${worker}/skills/"
        log "  → ${worker}/skills/ uploaded to MinIO"
    fi
done

# ---------------------------------------------------------------------------
# 3. Register workers using create-worker.sh (runs inside Manager container)
#    This creates Matrix users, Higress consumers, and generates openclaw.json
# ---------------------------------------------------------------------------
log "Registering graph-worker..."
docker exec "$MANAGER_CONTAINER" bash -c \
    "create-worker.sh --name graph-worker --skills file-sync,mcporter 2>&1" \
    && log "  → graph-worker registered" \
    || warn "  create-worker.sh for graph-worker failed (may already exist)"

log "Registering analytics-worker..."
docker exec "$MANAGER_CONTAINER" bash -c \
    "create-worker.sh --name analytics-worker --skills file-sync,mcporter 2>&1" \
    && log "  → analytics-worker registered" \
    || warn "  create-worker.sh for analytics-worker failed (may already exist)"

# ---------------------------------------------------------------------------
# 4. Create honeybadge-gateway Matrix account (used by honeybadge-server)
#    honeybadge-server connects to Tuwunel as this user to send DMs to Manager
# ---------------------------------------------------------------------------
log "Creating honeybadge-gateway Matrix account..."
docker exec "$MANAGER_CONTAINER" bash -c "
    register_appservice_user() {
        curl -sf -X POST http://localhost:6167/_matrix/client/v3/register \
            -H 'Content-Type: application/json' \
            -d '{
                \"username\": \"honeybadge-gateway\",
                \"password\": \"${GATEWAY_PASSWORD}\",
                \"auth\": {\"type\": \"m.login.registration_token\", \"token\": \"${REG_TOKEN}\"}
            }' 2>&1
    }
    register_appservice_user
" && log "  → honeybadge-gateway account created" \
  || warn "  Gateway account creation failed (may already exist — safe to ignore)"

# ---------------------------------------------------------------------------
# 5. Register MCP servers in Higress AI Gateway
# ---------------------------------------------------------------------------
log "Registering MCP servers in Higress..."
if docker exec "$MANAGER_CONTAINER" which setup-mcp-server.sh &>/dev/null; then
    # Copy MCP yaml configs into Manager, then register them
    for yaml_file in "$SCRIPT_DIR"/mcp-honeybadge-*.yaml; do
        fname=$(basename "$yaml_file")
        docker cp "$yaml_file" "$MANAGER_CONTAINER:/tmp/$fname"
        docker exec "$MANAGER_CONTAINER" bash -c \
            "HIGRESS_ADMIN_URL=http://localhost:8001 setup-mcp-server.sh /tmp/$fname 2>&1" \
            && log "  → registered $fname" \
            || warn "  Failed to register $fname (may already exist)"
    done
else
    warn "setup-mcp-server.sh not found in Manager container."
    warn "Register MCP servers manually via Higress console: http://localhost:18001"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
log "Worker initialization complete!"
echo ""
echo "  Next steps:"
echo "  1. Restart workers to pick up their new MinIO config:"
echo "       docker compose restart hiclaw-graph-worker hiclaw-analytics-worker"
echo "  2. Restart honeybadge-server to connect to Matrix:"
echo "       docker compose restart honeybadge-server"
echo "  3. Access the UI: http://localhost:3000"
echo "     Login: admin/admin123"
echo ""
echo "  Monitor agents via Element Web: http://localhost:18888"
echo "  Inspect MinIO config:           http://localhost:19001  (admin/admin)"
