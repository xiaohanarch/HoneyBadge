#!/bin/bash
# Matrix Account Initialization Script
# Registers HiClaw bot accounts on the Conduit homeserver.
#
# Usage (run from host after `docker-compose up -d matrix-conduit`):
#   bash deploy/docker/init-matrix.sh
#
# Accounts created:
#   @honeybadge-gateway:matrix.local  — used by honeybadge-server (gateway bot)
#   @honeybadge-manager:matrix.local  — HiClaw Manager
#   @graph-worker:matrix.local        — HiClaw Graph Worker
#   @analytics-worker:matrix.local    — HiClaw Analytics Worker

set -e

MATRIX_URL="${MATRIX_URL:-http://localhost:8008}"
MATRIX_GATEWAY_PASSWORD="${MATRIX_GATEWAY_PASSWORD:-gateway-dev-pass}"
MATRIX_MANAGER_PASSWORD="${MATRIX_MANAGER_PASSWORD:-manager-dev-pass}"
MATRIX_GRAPH_WORKER_PASSWORD="${MATRIX_GRAPH_WORKER_PASSWORD:-graph-worker-dev-pass}"
MATRIX_ANALYTICS_WORKER_PASSWORD="${MATRIX_ANALYTICS_WORKER_PASSWORD:-analytics-worker-dev-pass}"

echo "=========================================="
echo "HoneyBadge Matrix Account Initialization"
echo "Homeserver: $MATRIX_URL"
echo "=========================================="

# Wait for Conduit to be ready
echo "Waiting for Matrix homeserver to be ready..."
for i in $(seq 1 30); do
    if curl -sf "$MATRIX_URL/health" > /dev/null 2>&1; then
        echo "Matrix homeserver is ready!"
        break
    fi
    echo "Attempt $i/30: Matrix not ready yet, retrying in 5s..."
    sleep 5
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Matrix homeserver did not become ready in time."
        exit 1
    fi
done

# Register a single account. Ignores M_USER_IN_USE (already registered).
register_account() {
    local username="$1"
    local password="$2"

    echo ""
    echo "Registering @${username}:matrix.local ..."

    RESPONSE=$(curl -sf -X POST \
        -H "Content-Type: application/json" \
        -d "{\"username\": \"${username}\", \"password\": \"${password}\", \"auth\": {\"type\": \"m.login.dummy\"}}" \
        "${MATRIX_URL}/_matrix/client/v3/register" 2>&1) || true

    if echo "$RESPONSE" | grep -q '"M_USER_IN_USE"'; then
        echo "  Already registered (skipped)."
    elif echo "$RESPONSE" | grep -q '"user_id"'; then
        echo "  Registered successfully."
    else
        echo "  WARNING: Unexpected response: $RESPONSE"
    fi
}

register_account "honeybadge-gateway"   "$MATRIX_GATEWAY_PASSWORD"
register_account "honeybadge-manager"   "$MATRIX_MANAGER_PASSWORD"
register_account "graph-worker"         "$MATRIX_GRAPH_WORKER_PASSWORD"
register_account "analytics-worker"     "$MATRIX_ANALYTICS_WORKER_PASSWORD"

echo ""
echo "=========================================="
echo "Matrix account initialization complete!"
echo "Accounts:"
echo "  @honeybadge-gateway:matrix.local"
echo "  @honeybadge-manager:matrix.local"
echo "  @graph-worker:matrix.local"
echo "  @analytics-worker:matrix.local"
echo "=========================================="
