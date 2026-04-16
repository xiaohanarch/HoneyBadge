#!/bin/bash
# Fix script: Create the 4 tags that failed during bulk init-nebula.sh
# Also ALTER Invoice to add v2.0 fields (pay_group, source).
#
# Root cause 1: NebulaGraph meta heartbeat race condition when creating
# many new tags in rapid succession. Running individually with pauses fixes it.
# Root cause 2: NebulaGraph requires DOUBLE defaults to use float literals
# (DEFAULT 0.0, not DEFAULT 0). Integer literals cause "Invalid param!" error.
#
# Usage: bash deploy/docker/fix-missing-tags.sh

set -e

NETWORK="${NEBULA_NETWORK:-honeybadge-network}"
NEBULA_ADDR="${NEBULA_ADDR:-nebula-graphd}"
NEBULA_PORT="${NEBULA_PORT:-9669}"
NEBULA_USER="${NEBULA_USER:-root}"
NEBULA_PASSWORD="${NEBULA_PASSWORD:-nebula}"
CONSOLE_IMAGE="vesoft/nebula-console:v3.8.0"

console_exec() {
    docker run --rm --network "$NETWORK" --entrypoint="" \
        "$CONSOLE_IMAGE" \
        nebula-console -addr "$NEBULA_ADDR" -P "$NEBULA_PORT" \
        -u "$NEBULA_USER" -password "$NEBULA_PASSWORD" \
        -e "$1"
}

echo "=========================================="
echo "Fix: Create missing v2.0 tags + ALTER Invoice"
echo "=========================================="

# --- 1. POShipment (24 properties) ---
echo ""
echo "[1/6] Creating POShipment..."
console_exec 'USE honeybadge; CREATE TAG IF NOT EXISTS POShipment(shipment_number INT64 NOT NULL, shipment_type STRING, quantity DOUBLE NOT NULL, quantity_received DOUBLE DEFAULT 0.0, quantity_billed DOUBLE DEFAULT 0.0, quantity_cancelled DOUBLE DEFAULT 0.0, need_by_date TIMESTAMP, promised_date TIMESTAMP, ship_to_location STRING, receiving_routing STRING, match_option STRING DEFAULT "R", price_override DOUBLE, amount DOUBLE, status STRING, accrue_on_receipt_flag STRING DEFAULT "Y", inspection_required_flag STRING DEFAULT "N", org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);'
echo "  Waiting for schema propagation..."
sleep 8

# --- 2. PaymentSchedule (20 properties) ---
echo "[2/6] Creating PaymentSchedule..."
console_exec 'USE honeybadge; CREATE TAG IF NOT EXISTS PaymentSchedule(schedule_id STRING NOT NULL, installment_number INT64 DEFAULT 1, due_date TIMESTAMP NOT NULL, gross_amount DOUBLE NOT NULL, amount_remaining DOUBLE, payment_status STRING, discount_date TIMESTAMP, discount_amount_available DOUBLE DEFAULT 0.0, second_discount_date TIMESTAMP, second_discount_amount DOUBLE DEFAULT 0.0, third_discount_date TIMESTAMP, third_discount_amount DOUBLE DEFAULT 0.0, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);'
echo "  Waiting for schema propagation..."
sleep 8

# --- 3. GLBalance (15 properties) ---
echo "[3/6] Creating GLBalance..."
console_exec 'USE honeybadge; CREATE TAG IF NOT EXISTS GLBalance(period_name STRING NOT NULL, currency_code STRING, period_net_dr DOUBLE DEFAULT 0.0, period_net_cr DOUBLE DEFAULT 0.0, begin_balance_dr DOUBLE DEFAULT 0.0, begin_balance_cr DOUBLE DEFAULT 0.0, translated_flag STRING DEFAULT "N", org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);'
echo "  Waiting for schema propagation..."
sleep 8

# --- 4. XLAJournalLine (17 properties) ---
echo "[4/6] Creating XLAJournalLine..."
console_exec 'USE honeybadge; CREATE TAG IF NOT EXISTS XLAJournalLine(ae_line_num INT64 NOT NULL, accounting_class STRING, entered_dr DOUBLE DEFAULT 0.0, entered_cr DOUBLE DEFAULT 0.0, accounted_dr DOUBLE DEFAULT 0.0, accounted_cr DOUBLE DEFAULT 0.0, currency_code STRING, currency_conversion_rate DOUBLE DEFAULT 1.0, description STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);'
echo "  Waiting for schema propagation..."
sleep 8

# --- 5. ALTER Invoice to add v2.0 fields ---
echo "[5/6] Adding pay_group and source to Invoice tag..."
console_exec 'USE honeybadge; ALTER TAG Invoice ADD (pay_group STRING, source STRING);'
echo "  Waiting for schema propagation..."
sleep 8

# --- 6. Rebuild indexes ---
echo "[6/6] Rebuilding indexes..."
console_exec "USE honeybadge; REBUILD TAG INDEX; REBUILD EDGE INDEX;"

echo ""
echo "=========================================="
echo "Verifying..."
echo "=========================================="

# Verify all 4 tags now exist
for tag in POShipment PaymentSchedule GLBalance XLAJournalLine; do
    RESULT=$(console_exec "USE honeybadge; DESCRIBE TAG $tag;" 2>&1)
    if echo "$RESULT" | grep -q "NOT NULL\|string\|int64\|double\|timestamp\|bool"; then
        echo "  $tag: OK"
    else
        echo "  $tag: FAILED - $RESULT"
    fi
done

# Verify Invoice has new fields
RESULT=$(console_exec "USE honeybadge; DESCRIBE TAG Invoice;" 2>&1)
if echo "$RESULT" | grep -q "pay_group"; then
    echo "  Invoice.pay_group: OK"
else
    echo "  Invoice.pay_group: MISSING"
fi
if echo "$RESULT" | grep -q "source"; then
    echo "  Invoice.source: OK"
else
    echo "  Invoice.source: MISSING"
fi

echo ""
echo "Done! Now re-run: python scripts/load-test-data.py"
echo "=========================================="
