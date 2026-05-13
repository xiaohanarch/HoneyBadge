#!/bin/bash
# HoneyBadge NebulaGraph Seed Runner
#
# Wraps `deploy/docker/nebula_seed.py` in a one-shot Python container so the
# host doesn't need a Python interpreter or nebula3-python installed.
#
# The Python script uses `INSERT VERTEX/EDGE IF NOT EXISTS`, so re-running
# is safe (idempotent).
#
# Usage:
#   bash deploy/docker/seed-nebula.sh
#
# Env overrides:
#   NEBULA_HOST     (default: honeybadge-nebula-graphd)
#   NEBULA_PORT     (default: 9669)
#   NEBULA_USER     (default: root)
#   NEBULA_PASSWORD (default: nebula)
#   PIP_INDEX_URL   (default: aliyun mirror — for CN-friendly speed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
NETWORK="${NETWORK:-honeybadge-network}"
NEBULA_HOST="${NEBULA_HOST:-honeybadge-nebula-graphd}"
NEBULA_PORT="${NEBULA_PORT:-9669}"
NEBULA_USER="${NEBULA_USER:-root}"
NEBULA_PASSWORD="${NEBULA_PASSWORD:-nebula}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[seed]${NC} $*"; }
die()  { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    die "Docker network '$NETWORK' not found — run 'docker compose up -d' first."
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${NEBULA_HOST}\$"; then
    die "NebulaGraph container '$NEBULA_HOST' not running."
fi

log "Seeding NebulaGraph at ${NEBULA_HOST}:${NEBULA_PORT}..."

docker run --rm \
    --network "$NETWORK" \
    -e NEBULA_HOST="$NEBULA_HOST" \
    -e NEBULA_PORT="$NEBULA_PORT" \
    -e NEBULA_USER="$NEBULA_USER" \
    -e NEBULA_PASSWORD="$NEBULA_PASSWORD" \
    -v "$PROJECT_ROOT/deploy/docker/nebula_seed.py:/seed.py:ro" \
    python:3.11-slim \
    sh -c "pip install -q -i ${PIP_INDEX_URL} nebula3-python && python /seed.py"

log "Seed complete."
