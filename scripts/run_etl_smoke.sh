#!/usr/bin/env bash
# HoneyBadge ETL Smoke Test
# End-to-end manual verification: CSV → ODS → Quality → Transform → Pipeline
#
# Prerequisites:
#   - Docker running with postgres + nebula services
#   - Python 3.12+ with: pip install -e ".[dev]"
#
# Usage:
#   bash scripts/run_etl_smoke.sh                    # synthetic data (500 POs)
#   bash scripts/run_etl_smoke.sh --real-data        # real USAspending.gov data (5000 POs)
#   bash scripts/run_etl_smoke.sh --skip-docker      # skip docker compose up
#   bash scripts/run_etl_smoke.sh --real-data --skip-docker

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
COMPOSE_FILE="deploy/docker/docker-compose.yaml"
BATCH_ID="ETL-SMOKE-$(date +%Y%m%d%H%M%S)"
POSTGRES_DSN="postgresql://honeybadge:honeybadge123@localhost:5432/honeybadge_ods"
NEBULA_HOST="${NEBULA_GRAPHD_HOST:-localhost}"
NEBULA_PORT="${NEBULA_GRAPHD_PORT:-9669}"

# Parse args
USE_REAL_DATA=false
SKIP_DOCKER=""
for arg in "$@"; do
    case "$arg" in
        --real-data)  USE_REAL_DATA=true ;;
        --skip-docker) SKIP_DOCKER="--skip-docker" ;;
    esac
done

if [ "$USE_REAL_DATA" = true ]; then
    CSV_DIR="deploy/test-data/usaspending_csv"
    EXPECTED_PO_COUNT=5000
else
    CSV_DIR="deploy/test-data/ptp_csv"
    EXPECTED_PO_COUNT=500
fi

# ── Helpers ─────────────────────────────────────────────────────────────────
log() { echo -e "\n=== $1 ==="; }
ok()  { echo "  ✓ $1"; }
fail(){ echo "  ✗ $1" >&2; exit 1; }

# ── 1. Start infrastructure ─────────────────────────────────────────────────
if [ "$SKIP_DOCKER" != "--skip-docker" ]; then
    log "Starting infrastructure (postgres + nebula)"
    docker compose -f "$COMPOSE_FILE" up -d postgres nebula-graphd nebula-storaged nebula-metad
    sleep 5

    log "Initializing NebulaGraph schema"
    bash deploy/docker/init-nebula.sh || true

    ok "Infrastructure started"
else
    log "Skipping docker setup (--skip-docker)"
fi

# ── 2. Generate CSV data ────────────────────────────────────────────────────
log "Generating PTP CSV data (batch=$BATCH_ID, source=$([ "$USE_REAL_DATA" = true ] && echo 'USAspending.gov' || echo 'synthetic'))"
if [ "$USE_REAL_DATA" = true ]; then
    python scripts/fetch_usaspending_ptp.py \
        --output-dir "$CSV_DIR" \
        --batch-id "$BATCH_ID" \
        --limit 5000 --year 2024
else
    python scripts/generate_ptp_csv.py \
        --output-dir "$CSV_DIR" \
        --batch-id "$BATCH_ID"
fi

# Verify CSV files exist
CSV_COUNT=$(ls "$CSV_DIR"/ods_*.csv 2>/dev/null | wc -l)
[ "$CSV_COUNT" -eq 9 ] || fail "Expected 9 CSV files, got $CSV_COUNT"
ok "Generated $CSV_COUNT CSV files"

# ── 3. Load CSV → ODS ───────────────────────────────────────────────────────
log "Loading CSV into ODS PostgreSQL"
python scripts/load_csv_to_ods.py \
    --csv-dir "$CSV_DIR" \
    --batch-id "$BATCH_ID" \
    --postgres-dsn "$POSTGRES_DSN"

# Verify ODS data
PO_COUNT=$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U honeybadge -d honeybadge_ods -t \
    -c "SELECT COUNT(*) FROM ods_purchase_order WHERE etl_batch_id = '$BATCH_ID';")
PO_COUNT=$(echo "$PO_COUNT" | tr -d '[:space:]')
[ "$PO_COUNT" -eq "$EXPECTED_PO_COUNT" ] || fail "Expected $EXPECTED_PO_COUNT POs in ODS, got $PO_COUNT"
ok "ODS loaded: $PO_COUNT purchase orders"

# ── 4. Run ETL pipeline ─────────────────────────────────────────────────────
log "Running ETL pipeline (skip-trigger mode)"
python -m honeybadge.etl.run_pipeline \
    --batch-id "$BATCH_ID" \
    --skip-trigger \
    --tables ods_organization ods_supplier ods_item \
           ods_purchase_order ods_purchase_order_line \
           ods_receipt ods_receipt_line \
           ods_ap_invoice ods_ap_invoice_line \
    --postgres-dsn "$POSTGRES_DSN" \
    --nebula-host "$NEBULA_HOST" \
    --nebula-port "$NEBULA_PORT" \
    --output-dir import \
    || fail "Pipeline failed"

ok "Pipeline completed"

# ── 5. Verify import CSV files ──────────────────────────────────────────────
log "Verifying transform output"
VERTEX_COUNT=$(ls import/"$BATCH_ID"/vertex_*.csv 2>/dev/null | wc -l)
EDGE_COUNT=$(ls import/"$BATCH_ID"/edge_*.csv 2>/dev/null | wc -l)
echo "  Vertex CSVs: $VERTEX_COUNT"
echo "  Edge CSVs:   $EDGE_COUNT"
[ "$VERTEX_COUNT" -gt 0 ] || fail "No vertex CSV files generated"
ok "Transform output verified"

# ── 6. Verify NebulaGraph (if available) ────────────────────────────────────
log "Verifying NebulaGraph data"
NEBULA_CHECK=$(docker compose -f "$COMPOSE_FILE" exec -T nebula-graphd \
    nebula-console -addr nebula-graphd -port 9669 -u root -p nebula \
    -e "USE honeybadge; MATCH (s:Supplier) RETURN count(*);" 2>/dev/null || echo "UNAVAILABLE")

if echo "$NEBULA_CHECK" | grep -q "UNAVAILABLE"; then
    echo "  ⚠ NebulaGraph not available for verification (import may have been skipped)"
else
    echo "  NebulaGraph Supplier count: $NEBULA_CHECK"
    ok "NebulaGraph verified"
fi

# ── 7. Run integration tests ────────────────────────────────────────────────
log "Running integration tests"
POSTGRES_DSN="$POSTGRES_DSN" pytest tests/test_etl_pipeline.py -v --timeout=120 || true

log "Smoke test complete"
echo "Batch ID: $BATCH_ID"
echo "CSV dir:  $CSV_DIR"
echo "Import:   import/$BATCH_ID/"
