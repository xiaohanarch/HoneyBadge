#!/bin/bash
# NebulaGraph Schema Initialization Script
#
# Run from any directory after: cd deploy/docker && docker compose up -d
# Usage: bash init-nebula.sh
#
# What it does:
#   1. Waits for nebula-graphd to accept connections
#   2. Registers nebula-storaged with metad (ADD HOSTS — required in NebulaGraph v3)
#   3. Waits for storaged to come ONLINE
#   4. Creates the 'honeybadge' space
#   5. Applies schema: nebula-schema.ngql (tags + tag indexes)
#   6. Applies schema: nebula-edges.ngql (edges + edge indexes)
#   7. Rebuilds indexes
#
# Safe to re-run: all DDL statements use IF NOT EXISTS.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NETWORK="${NEBULA_NETWORK:-honeybadge-network}"
NEBULA_ADDR="${NEBULA_ADDR:-nebula-graphd}"
NEBULA_PORT="${NEBULA_PORT:-9669}"
NEBULA_USER="${NEBULA_USER:-root}"
NEBULA_PASSWORD="${NEBULA_PASSWORD:-nebula}"
CONSOLE_IMAGE="vesoft/nebula-console:v3.8.0"

# Run an inline nGQL statement
console_exec() {
    docker run --rm --network "$NETWORK" --entrypoint="" \
        "$CONSOLE_IMAGE" \
        nebula-console -addr "$NEBULA_ADDR" -P "$NEBULA_PORT" \
        -u "$NEBULA_USER" -password "$NEBULA_PASSWORD" \
        -e "$1"
}

# Run a .ngql file by piping it to nebula-console stdin
# Uses cat | docker run -i to avoid Windows Git Bash path translation issues with < redirect
console_file() {
    local file="$1"
    cat "${SCRIPT_DIR}/${file}" | docker run --rm -i --network "$NETWORK" --entrypoint="" \
        "$CONSOLE_IMAGE" \
        nebula-console -addr "$NEBULA_ADDR" -P "$NEBULA_PORT" \
        -u "$NEBULA_USER" -password "$NEBULA_PASSWORD"
}

echo "=========================================="
echo "HoneyBadge NebulaGraph Schema Initialization"
echo "=========================================="

# ---------------------------------------------------------------------------
# Step 1: Wait for graphd to accept connections
# ---------------------------------------------------------------------------
echo "Waiting for graphd to accept connections..."
for i in {1..30}; do
    if console_exec "SHOW HOSTS" 2>/dev/null; then
        echo "Graphd is ready."
        break
    fi
    echo "Attempt $i/30: graphd not ready yet..."
    sleep 5
done

# ---------------------------------------------------------------------------
# Step 2: Register storaged with metad
# NebulaGraph v3 requires explicit ADD HOSTS — not auto-registered.
# ---------------------------------------------------------------------------
echo "Registering storage node with metad (ADD HOSTS)..."
console_exec 'ADD HOSTS "nebula-storaged":9779;'

echo "Waiting for storaged to come ONLINE..."
for i in {1..30}; do
    STATUS=$(console_exec "SHOW HOSTS;" 2>/dev/null)
    if echo "$STATUS" | grep -q "ONLINE"; then
        echo "Storaged is ONLINE!"
        break
    fi
    echo "Attempt $i/30: storaged not ONLINE yet..."
    sleep 5
done

# ---------------------------------------------------------------------------
# Step 3: Create the honeybadge space
# ---------------------------------------------------------------------------
echo "Creating honeybadge space..."
console_exec "CREATE SPACE IF NOT EXISTS honeybadge (partition_num = 100, replica_factor = 1, vid_type = FIXED_STRING(64));"

echo "Waiting for space to propagate across cluster..."
sleep 10

# ---------------------------------------------------------------------------
# Step 4: Apply tags and tag indexes
# ---------------------------------------------------------------------------
echo "Applying nebula-schema.ngql (tags + tag indexes)..."
console_file "nebula-schema.ngql"

# ---------------------------------------------------------------------------
# Step 5: Apply edges and edge indexes
# ---------------------------------------------------------------------------
echo "Applying nebula-edges.ngql (edges + edge indexes)..."
console_file "nebula-edges.ngql"

# ---------------------------------------------------------------------------
# Step 6: Ensure indexes are created and rebuild
# ---------------------------------------------------------------------------
# NebulaGraph propagates schema changes (CREATE TAG/EDGE) to storaged
# asynchronously. When tags and tag indexes are applied in the same file,
# CREATE TAG INDEX may silently fail because the tag definition hasn't
# reached storaged yet. We wait for propagation, re-apply the schema
# (idempotent via IF NOT EXISTS) to catch any indexes that failed on the
# first pass, then rebuild with verification and retry.

echo "Waiting for schema to propagate across cluster..."
sleep 20

echo "Re-applying schema to catch any indexes that failed on first pass..."
console_file "nebula-schema.ngql"
console_file "nebula-edges.ngql"

echo "Waiting for index definitions to propagate..."
sleep 10

echo "Verifying indexes exist before rebuild..."
TAG_IDX_COUNT=$(console_exec "USE honeybadge; SHOW TAG INDEXES;" 2>&1 | grep -c "idx_" || true)
EDGE_IDX_COUNT=$(console_exec "USE honeybadge; SHOW EDGE INDEXES;" 2>&1 | grep -c "idx_" || true)
echo "Found $TAG_IDX_COUNT tag indexes, $EDGE_IDX_COUNT edge indexes"

echo "Rebuilding indexes (with retry)..."
for i in {1..5}; do
    RESULT=$(console_exec "USE honeybadge; REBUILD TAG INDEX; REBUILD EDGE INDEX;" 2>&1 || true)
    if ! echo "$RESULT" | grep -qE "without indexes|SemanticError"; then
        echo "Index rebuild successful on attempt $i."
        break
    fi
    echo "Attempt $i/5: index rebuild failed, waiting 10s before retry..."
    echo "$RESULT" | head -5
    sleep 10
done

echo "=========================================="
echo "Schema initialization complete!"
echo ""
echo "Verify with:"
echo "  SHOW TAGS;"
echo "  SHOW EDGES;"
echo "  SHOW TAG INDEXES;"
echo "  SHOW EDGE INDEXES;"
echo "=========================================="
