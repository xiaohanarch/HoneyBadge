# Scale Test Data to 700K Vertices / 1M Edges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scale HoneyBadge test data from ~27K vertices / ~220K edges to ~700K vertices / ~1M edges by scaling entity counts while preserving business relationships and 1-2% noise/anomaly rates.

**Architecture:** Modify `generate_test_data.py` NUM_* constants to achieve target volumes. The generator's entity-ratio logic (e.g., PO has 1-8 lines) naturally scales since line counts are per-transaction. Increase header entities proportionally so line counts reach ~580K. NebulaGraph import via `load-test-data.py` remains unchanged (batch_size may be tuned).

**Tech Stack:** Python 3, NebulaGraph Python client, CSV (nebula-importer format)

---

## Task 1: Backup & Create Scaled Generation Script

**Files:**
- Modify: `scripts/generate_test_data.py` (backup original to `scripts/generate_test_data.py.bak`)
- Create: `scripts/generate_test_data_scaled.py`

- [ ] **Step 1: Create backup of original**

```bash
cp scripts/generate_test_data.py scripts/generate_test_data.py.bak
```

- [ ] **Step 2: Create scaled generation script based on original**

Copy `scripts/generate_test_data.py.bak` → `scripts/generate_test_data_scaled.py`.

- [ ] **Step 3: Compute and set scaled NUM_* constants**

Target: ~700K vertices, ~1M edges.

Current totals (from CSV line counts, excluding header):
```
Master data (~800): Supplier(100), Customer(80), Item(500), Org(10), Employee(50), Warehouse(5), GLAccount(30), Currency(8), UOM(15)
+ BOM(50), BOMComponent(260), Contract(200), SupplierQualification(336)
= ~2,444

Transaction headers (~26K): PR(1000), PO(3000), Receipt(2500), Invoice(3000), Payment(2000), SO(2000), Shipment(1800), ARInvoice(1500), ARReceipt(1000), GLJournalEntry(5000), XLAEvent(6000), ApprovalRecord(5000)
= ~33,000

Line items (~94K from CSV counts): PR Line(2992), PO Line(13381), Receipt Line(7468), Invoice Line(8884), SO Line(10966), Shipment Line(5434), GLJournalLine(24731), AccountingDistribution(21165)
= ~94,021

Total vertices: ~129K (but CSV rows show ~155K including edges-as-vertices)
```

Scaled constants for `scripts/generate_test_data_scaled.py`:

| Entity | Original | Scale | New Value |
|--------|----------|-------|-----------|
| NUM_SUPPLIERS | 100 | 4x | 400 |
| NUM_CUSTOMERS | 80 | 4x | 320 |
| NUM_ITEMS | 500 | 4x | 2000 |
| NUM_ORGANIZATIONS | 10 | 4x | 40 |
| NUM_EMPLOYEES | 50 | 4x | 200 |
| NUM_WAREHOUSES | 5 | 4x | 20 |
| NUM_GL_ACCOUNTS | 30 | 4x | 120 |
| NUM_CURRENCIES | 8 | 4x | 32 |
| NUM_UOMS | 15 | 4x | 60 |
| NUM_BOMS | 50 | 4x | 200 |
| NUM_BOM_COMPONENTS | 260 | 4x | 1040 |
| NUM_CONTRACTS | 200 | 4x | 800 |
| NUM_SUPPLIER_QUALIFICATIONS | 336 | 4x | 1344 |
| NUM_PURCHASE_REQUISITIONS | 1000 | 4x | 4000 |
| NUM_PURCHASE_ORDERS | 3000 | 4x | 12000 |
| NUM_RECEIPTS | 2500 | 4x | 10000 |
| NUM_INVOICES | 3000 | 4x | 12000 |
| NUM_PAYMENTS | 2000 | 4x | 8000 |
| NUM_SALES_ORDERS | 2000 | 4x | 8000 |
| NUM_SHIPMENTS | 1800 | 4x | 7200 |
| NUM_AR_INVOICES | 1500 | 4x | 6000 |
| NUM_AR_RECEIPTS | 1000 | 4x | 4000 |
| NUM_GL_JOURNAL_ENTRIES | 5000 | 4x | 20000 |
| NUM_XLA_EVENTS | 6000 | 4x | 24000 |
| NUM_APPROVAL_RECORDS | 5000 | 4x | 20000 |

Line items scale automatically (1-8 per header, avg ~4.5), giving ~700K vertices total.

Set at top of `generate_test_data_scaled.py`:
```python
# Scaled entity counts for 700K vertex / 1M edge target
NUM_SUPPLIERS = 400
NUM_CUSTOMERS = 320
NUM_ITEMS = 2000
NUM_ORGANIZATIONS = 40
NUM_EMPLOYEES = 200
NUM_WAREHOUSES = 20
NUM_GL_ACCOUNTS = 120
NUM_CURRENCIES = 32
NUM_UOMS = 60
NUM_BOMS = 200
NUM_PURCHASE_REQUISITIONS = 4000
NUM_PURCHASE_ORDERS = 12000
NUM_RECEIPTS = 10000
NUM_INVOICES = 12000
NUM_PAYMENTS = 8000
NUM_SALES_ORDERS = 8000
NUM_SHIPMENTS = 7200
NUM_AR_INVOICES = 6000
NUM_AR_RECEIPTS = 4000
NUM_GL_JOURNAL_ENTRIES = 20000
NUM_XLA_EVENTS = 24000
NUM_APPROVAL_RECORDS = 20000
NUM_CONTRACTS = 800
```

Also update comment: `# Transaction counts (scaled for 700K vertices / 1M edges - full production dataset)`

- [ ] **Step 4: Update BATCH_SIZE for performance**

In `generate_test_data_scaled.py`, change:
```python
BATCH_SIZE = 5000  # Increased from 50 for better I/O performance with large datasets
```

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_test_data_scaled.py
git commit -m "feat(test-data): add scaled generation script targeting 700K vertices"
```

---

## Task 2: Generate Scaled CSV Data

**Files:**
- Modify: `scripts/generate_test_data_scaled.py`
- Output: `deploy/test-data/csv/vertices/*.csv` and `deploy/test-data/csv/edges/*.csv`

- [ ] **Step 1: Clear existing CSV files**

```bash
rm -rf deploy/test-data/csv/vertices/*.csv deploy/test-data/csv/edges/*.csv
```

- [ ] **Step 2: Run scaled generation**

```bash
python scripts/generate_test_data_scaled.py --output-dir deploy/test-data/csv
```

Expected runtime: 10-30 minutes depending on hardware. The script prints progress every phase.

- [ ] **Step 3: Verify vertex and edge counts**

```bash
find deploy/test-data/csv/vertices -name "*.csv" | while read f; do echo "$(tail -n +2 "$f" | wc -l) $(basename $f)"; done | sort -n
find deploy/test-data/csv/edges -name "*.csv" | while read f; do echo "$(tail -n +2 "$f" | wc -l) $(basename $f)"; done | sort -n
```

Verify total vertices ≈ 700K (±10%) and total edges ≈ 1M (±10%).

- [ ] **Step 4: Commit generated data reference**

```bash
git add -f deploy/test-data/csv/
git commit -m "feat(test-data): generate 700K vertex / 1M edge dataset"
```

---

## Task 3: Import Data into NebulaGraph

**Files:**
- Modify: `scripts/load-test-data.py` (batch size tuning only, if needed)

- [ ] **Step 1: Verify NebulaGraph is running**

```bash
# Check via docker-compose
docker ps | grep nebula
```

- [ ] **Step 2: Clear existing data in honeybadge space (optional, for clean import)**

```bash
python -c "
from nebula3.Config import Config
from nebula3.gclient.net import ConnectionPool
pool = ConnectionPool()
ok = pool.init([('localhost', 9669)], Config())
session = pool.get_session('root', 'nebula')
session.execute('USE honeybadge')
session.execute('SUBMIT JOB COMPACT')
import time; time.sleep(5)
session.execute('LOOKUP ON Supplier YIELD id(vertex) AS vid | LIMIT 1')
# Check counts before clearing
for tag in ['Supplier', 'PurchaseOrder', 'Invoice', 'Item', 'SalesOrder']:
    r = session.execute(f'MATCH (n:`{tag}`) RETURN count(n) AS cnt')
    if r.is_succeeded():
        print(f'{tag}: {r.row_values(0)[0].as_int()}')
pool.close()
"
```

- [ ] **Step 3: Run data load with increased batch size**

```bash
python scripts/load-test-data.py --host localhost --port 9669 --space honeybadge --batch-size 200
```

Expected runtime: 30-60 minutes for 1M edges.

- [ ] **Step 4: Verify import counts**

```bash
python -c "
from nebula3.Config import Config
from nebula3.gclient.net import ConnectionPool
pool = ConnectionPool()
pool.init([('localhost', 9669)], Config())
session = pool.get_session('root', 'nebula')
session.execute('USE honeybadge')
total_v = 0
total_e = 0
for tag in ['Supplier', 'Customer', 'Item', 'PurchaseOrder', 'PurchaseOrderLine', 'Receipt', 'ReceiptLine', 'Invoice', 'InvoiceLine', 'Payment', 'SalesOrder', 'SalesOrderLine', 'Shipment', 'ShipmentLine', 'GLJournalEntry', 'GLJournalLine', 'AccountingDistribution', 'XLAEvent', 'ApprovalRecord']:
    r = session.execute(f'MATCH (n:\`{tag}\`) RETURN count(n) AS cnt')
    if r.is_succeeded() and r.row_size() > 0:
        cnt = r.row_values(0)[0].as_int()
        total_v += cnt
        print(f'{tag}: {cnt:,}')
print(f'Total vertices: {total_v:,}')

for edge in ['HAS_PO_LINE', 'HAS_RECEIPT_LINE', 'HAS_INVOICE_LINE', 'HAS_SO_LINE', 'HAS_SHIPMENT_LINE', 'PLACED_WITH', 'RECEIVED_FROM', 'SUPPLIES_ITEM', 'HAS_JOURNAL_LINE', 'POSTED_TO']:
    r = session.execute(f'MATCH ()-[e:\`{edge}\`]->() RETURN count(e) AS cnt')
    if r.is_succeeded() and r.row_size() > 0:
        cnt = r.row_values(0)[0].as_int()
        total_e += cnt
        print(f'{edge}: {cnt:,}')
print(f'Total edges (sample): {total_e:,}')
pool.close()
"
```

---

## Verification Checklist

- [ ] Total vertices ≥ 650K (target 700K)
- [ ] Total edges ≥ 900K (target 1M)
- [ ] Key entity ratios preserved (e.g., PO:POLine ≈ 1:4.5)
- [ ] Noise data rate ~1-2% maintained (THREE_WAY_MATCH_FAILURE_RATE, TEMPORAL_VIOLATION_RATE, DUPLICATE_INVOICE_RATE unchanged)
- [ ] Business relationships intact (e.g., Receipt → PO → Supplier, Invoice → PO)
- [ ] NebulaGraph import completes without errors
