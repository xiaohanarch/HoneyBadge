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
#   3. (Approach B) Per-user Matrix accounts are provisioned at login via honeybadge-auth
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
# 3b. Fix worker LLM baseUrl: hiclaw-manager:8080 → aigw-local.hiclaw.io:8080
#
#     create-worker.sh generates openclaw.json with baseUrl=http://hiclaw-manager:8080/v1.
#     Higress requires Host: aigw-local.hiclaw.io to route AI requests.
#     docker-compose.yaml gives hiclaw-manager a network alias aigw-local.hiclaw.io,
#     so workers resolve this name to the manager's current IP via Docker DNS —
#     no hardcoded IPs needed.
# ---------------------------------------------------------------------------
log "Fixing worker LLM baseUrl (hiclaw-manager → aigw-local.hiclaw.io)..."
for worker in graph-worker analytics-worker; do
    docker exec "$MANAGER_CONTAINER" bash -c "
python3 << 'EOF'
import json, os, sys

paths = [
    '/tmp/${worker}-workspace/openclaw.json',
    '/root/hiclaw-fs/agents/${worker}/openclaw.json',
]

# Find the worker's openclaw.json (location varies by HiClaw version)
cfg_path = None
for p in paths:
    if os.path.exists(p):
        cfg_path = p
        break

if cfg_path is None:
    print('openclaw.json not found for ${worker}', file=sys.stderr)
    sys.exit(0)

with open(cfg_path) as f:
    cfg = json.load(f)

providers = cfg.get('models', {}).get('providers', {})
for name, p in providers.items():
    old = p.get('baseUrl', '')
    if 'hiclaw-manager:8080' in old:
        p['baseUrl'] = old.replace('hiclaw-manager:8080', 'aigw-local.hiclaw.io:8080')
        print(f'Patched {name}: {old} -> {p[\"baseUrl\"]}')

with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2)
print('done')
EOF
" && log "  → ${worker} baseUrl patched" || warn "  Failed to patch ${worker} baseUrl"

    # Sync patched config to MinIO
    docker exec "$MANAGER_CONTAINER" bash -c \
        "mc cp /root/hiclaw-fs/agents/${worker}/openclaw.json hiclaw/hiclaw-storage/agents/${worker}/openclaw.json 2>/dev/null && echo synced || true" \
        && log "  → ${worker} openclaw.json synced to MinIO" || warn "  MinIO sync skipped for ${worker}"
done

# ---------------------------------------------------------------------------
# 4. Per-user Matrix accounts (Approach B) + patch Manager allowlist
#    Per-user Matrix accounts are provisioned at login time by honeybadge-auth.
#    We must patch Manager's openclaw.json to allow @hb-* users to DM Manager.
# ---------------------------------------------------------------------------
log "Patching Manager allowlist for @hb-* users (Approach B)..."
docker exec "$MANAGER_CONTAINER" bash -c "
python3 -c \"
import json

cfg_path = '/root/manager-workspace/openclaw.json'
with open(cfg_path) as f:
    cfg = json.load(f)

hb_users = [
    '@admin:${MATRIX_DOMAIN}',
    '@hb-admin:${MATRIX_DOMAIN}',
    '@hb-analyst:${MATRIX_DOMAIN}',
    '@hb-auditor:${MATRIX_DOMAIN}',
    '@honeybadge-gateway:${MATRIX_DOMAIN}'
]

cfg['channels']['matrix']['dm'] = {'policy': 'allowlist', 'allowFrom': hb_users}
cfg['channels']['matrix']['groupAllowFrom'] = hb_users

with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2)
print('allowlist patched')
\"
" && log "  → Manager allowlist updated" || warn "  Failed to patch Manager allowlist"

# Sync to MinIO so it survives restarts
docker exec "$MANAGER_CONTAINER" bash -c \
    "mc cp /root/manager-workspace/openclaw.json hiclaw/hiclaw-storage/agents/manager/openclaw.json 2>/dev/null && echo synced || true" \
    && log "  → Synced to MinIO" || warn "  MinIO sync skipped (optional)"

# ---------------------------------------------------------------------------
# 5. Register MCP servers in each worker via mcporter config add
#
#    We bypass setup-mcp-server.sh (which requires a session cookie from the
#    Higress Console and can expire).  mcporter's CLI directly writes
#    /root/hiclaw-fs/config/mcporter.json inside the worker container, then
#    we persist that file to MinIO so it survives restarts.
# ---------------------------------------------------------------------------
log "Registering MCP servers in workers via mcporter..."

# Map: server-name → SSE endpoint inside the Docker network
declare -A MCP_SERVERS=(
    [honeybadge-nebula]="http://honeybadge-nebula-mcp:8000/sse"
    [honeybadge-audit]="http://honeybadge-audit-mcp:8000/sse"
    [honeybadge-cache]="http://honeybadge-cache-mcp:8000/sse"
)

for worker in graph-worker analytics-worker; do
    WORKER_CONTAINER="honeybadge-${worker}"
    log "  Configuring $worker..."
    for server_name in "${!MCP_SERVERS[@]}"; do
        endpoint="${MCP_SERVERS[$server_name]}"
        docker exec "$WORKER_CONTAINER" bash -c \
            "mcporter config add '$server_name' '$endpoint' --allow-http --yes 2>&1" \
            && log "    → $server_name added" \
            || warn "    $server_name already exists or failed"
    done

    # Persist mcporter.json to MinIO so it survives container restarts
    docker cp "${WORKER_CONTAINER}:/root/hiclaw-fs/config/mcporter.json" \
        "/tmp/${worker}-mcporter.json" 2>/dev/null && \
    docker cp "/tmp/${worker}-mcporter.json" \
        "${MANAGER_CONTAINER}:/tmp/${worker}-mcporter.json" && \
    docker exec "$MANAGER_CONTAINER" bash -c \
        "mc cp /tmp/${worker}-mcporter.json hiclaw/hiclaw-storage/agents/${worker}/config/mcporter.json 2>&1 | tail -1" \
        && log "    → mcporter.json synced to MinIO" \
        || warn "    MinIO sync failed (config still active in running container)"
done

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
log "Worker initialization complete!"
echo ""
echo "  Next steps:"
echo "  1. Restart workers to pick up their new MinIO config:"
echo "       docker compose restart hiclaw-graph-worker hiclaw-analytics-worker"
echo "  2. Start honeybadge-auth service (provisions Matrix accounts at login):"
echo "       docker compose up -d honeybadge-auth"
echo "  3. Access the UI: http://localhost:3000"
echo "     Login: admin/admin123"
echo ""
echo "  Monitor agents via Element Web: http://localhost:18888"
echo "  Inspect MinIO config:           http://localhost:19001  (admin/admin)"
