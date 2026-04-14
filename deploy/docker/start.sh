#!/bin/bash
# HoneyBadge Full Stack Startup Script
#
# Automates the complete startup sequence:
#   1. docker compose up -d
#   2. Wait for HiClaw Manager healthy (MinIO endpoint)
#   3. Wait for honeybadge-server + honeybadge-auth healthy
#   4. Init NebulaGraph schema (idempotent)
#   5. Init HiClaw workers (allowlist + reasoning fix)
#   6. Restart workers to pick up new config
#   7. Print status summary
#
# Usage:
#   bash deploy/docker/start.sh           # full startup (from project root)
#   bash deploy/docker/start.sh --skip-init  # just docker compose up -d (regular restart)
#
# Safe to re-run: all init steps are idempotent.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve paths (works from any directory)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yaml"
ENV_FILE="$SCRIPT_DIR/.env"

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
SKIP_INIT=false
for arg in "$@"; do
    case "$arg" in
        --skip-init) SKIP_INIT=true ;;
        --help|-h)
            echo "Usage: bash deploy/docker/start.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-init   Skip init scripts (just docker compose up -d)"
            echo "  --help, -h    Show this help"
            exit 0
            ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

step() { echo -e "\n${CYAN}${BOLD}[$1/7]${NC} ${BOLD}$2${NC}"; }
log()  { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
die()  { echo -e "  ${RED}✗${NC} $*" >&2; exit 1; }

COMPOSE_CMD="docker compose -f $COMPOSE_FILE --env-file $ENV_FILE"

echo -e "${BOLD}HoneyBadge Full Stack Startup${NC}"
echo "============================================"

# ---------------------------------------------------------------------------
# Step 1: docker compose up -d
# ---------------------------------------------------------------------------
step 1 "Starting containers..."
$COMPOSE_CMD up -d
log "Containers started"

if [ "$SKIP_INIT" = true ]; then
    echo ""
    echo -e "${GREEN}${BOLD}Done!${NC} (--skip-init: skipped init scripts)"
    echo "  Frontend: http://localhost:3000"
    echo "  Login:    admin/admin123"
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 2: Wait for HiClaw Manager (MinIO health endpoint)
# ---------------------------------------------------------------------------
step 2 "Waiting for HiClaw Manager to be ready..."
MANAGER_CONTAINER="honeybadge-hiclaw-manager"
MAX_WAIT=120
ELAPSED=0
while ! docker exec "$MANAGER_CONTAINER" curl -sf http://localhost:9000/minio/health/live &>/dev/null; do
    if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
        die "HiClaw Manager not ready after ${MAX_WAIT}s. Check: docker logs $MANAGER_CONTAINER"
    fi
    echo -n "."
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done
echo ""
log "HiClaw Manager ready (${ELAPSED}s)"

# ---------------------------------------------------------------------------
# Step 3: Wait for honeybadge-server and honeybadge-auth
# ---------------------------------------------------------------------------
step 3 "Waiting for honeybadge services..."

wait_healthy() {
    local name="$1"
    local max="$2"
    local elapsed=0
    while true; do
        local health
        health=$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "missing")
        if [ "$health" = "healthy" ]; then
            log "$name healthy (${elapsed}s)"
            return 0
        fi
        if [ "$elapsed" -ge "$max" ]; then
            warn "$name not healthy after ${max}s (status: $health) — continuing anyway"
            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
}

wait_healthy "honeybadge-server" 90
wait_healthy "honeybadge-auth" 90

# ---------------------------------------------------------------------------
# Step 4: Init NebulaGraph schema
# ---------------------------------------------------------------------------
step 4 "Initializing NebulaGraph schema..."
bash "$PROJECT_ROOT/deploy/docker/init-nebula.sh"
log "NebulaGraph schema initialized"

# ---------------------------------------------------------------------------
# Step 5: Init HiClaw workers (includes allowlist + reasoning fix)
# ---------------------------------------------------------------------------
step 5 "Initializing HiClaw workers..."
bash "$PROJECT_ROOT/deploy/hiclaw/init-workers.sh"
log "Workers initialized (allowlist patched, reasoning removed)"

# ---------------------------------------------------------------------------
# Step 6: Restart workers to pick up new config
# ---------------------------------------------------------------------------
step 6 "Restarting workers..."
$COMPOSE_CMD restart hiclaw-graph-worker hiclaw-analytics-worker
log "Workers restarted"

# Wait briefly for workers to connect to Manager
echo -n "  Waiting for workers to connect"
for i in $(seq 1 6); do
    echo -n "."
    sleep 5
done
echo ""
log "Workers should be connected"

# ---------------------------------------------------------------------------
# Step 7: Status summary
# ---------------------------------------------------------------------------
step 7 "Status summary"
echo ""
$COMPOSE_CMD ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null \
    || $COMPOSE_CMD ps
echo ""
echo -e "${GREEN}${BOLD}All done!${NC}"
echo ""
echo "  Frontend:        http://localhost:3000"
echo "  Login:           admin/admin123  ·  analyst/analyst123  ·  auditor/auditor123"
echo "  Element Web:     http://localhost:18888"
echo "  MinIO Console:   http://localhost:19001  (admin/admin1234)"
echo "  Higress Console: http://localhost:18001  (admin/admin1234)"
echo ""
echo "  Health check:    curl http://localhost:8090/api/health"
echo ""
