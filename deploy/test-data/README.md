# HoneyBadge Phase 1 Test Data Generator

## Overview

This directory contains a comprehensive test data generator for simulating Oracle EBS / ERP data in NebulaGraph. The generator produces 1M+ realistic records across all business domains.

## Data Summary

| Domain | Entity | Count |
|--------|--------|-------|
| **Master Data** | Suppliers | 550 |
| | Customers | 480 |
| | Items | 5,200 |
| | Organizations | 120 |
| | Employees | 220 |
| | Warehouses | 12 |
| | GL Accounts | 200 |
| | BOMs | 800 |
| **Procurement (PTP)** | Purchase Requisitions | 15,000 |
| | Purchase Orders | 52,000 |
| | Receipts | 46,000 |
| | Invoices | 49,000 |
| | Payments | 42,000 |
| **Order-to-Cash (OTC)** | Sales Orders | 31,000 |
| | Shipments | 29,000 |
| | AR Invoices | 26,000 |
| | AR Receipts | 21,000 |
| **Accounting** | GL Journal Entries | 80,000 |
| | XLA Events | 100,000 |
| **Other** | Contracts | 3,000 |
| | Approval Records | 90,000 |

**Total Records: 1,000,000+**

## Intentional Anomalies for Testing

The generator creates realistic anomalies for fraud detection and anomaly testing:

| Anomaly Type | Rate | Description |
|--------------|------|-------------|
| **Three-way Match Failure** | 5% | Amount deviation > 10% between PO, Receipt, and Invoice |
| **Temporal Sequence Violation** | 2% | Documents with out-of-order dates |
| **Duplicate Invoices** | 1% | Invoice numbers repeated |
| **Expired Qualifications** | 8% | Suppliers with expired certifications |

## VID Format

All vertex IDs follow the format: `{EntityPrefix}:{BusinessKey}`

| Entity | Prefix | Example VID |
|--------|--------|-------------|
| Supplier | SUP | SUP:00001 |
| Customer | CUS | CUS:00001 |
| Item | ITM | ITM:000001 |
| Purchase Order | PO | PO:00000001 |
| Receipt | RCV | RCV:00000001 |
| Invoice | INV | INV:00000001 |
| Payment | PAY | PAY:00000001 |
| Sales Order | SO | SO:00000001 |
| Shipment | SHP | SHP:00000001 |
| AR Invoice | ARI | ARI:00000001 |
| AR Receipt | ARR | ARR:00000001 |
| GL Journal Entry | JLE | JLE:00000001 |
| XLA Event | XLA | XLA:0000000001 |
| Approval Record | APR | APR:0000000001 |

## Directory Structure

```
deploy/test-data/
├── vertices/
│   ├── Supplier.csv
│   ├── Customer.csv
│   ├── Item.csv
│   ├── Organization.csv
│   ├── Employee.csv
│   ├── Warehouse.csv
│   ├── BOM.csv
│   ├── BOMComponent.csv
│   ├── PurchaseOrder.csv
│   ├── PurchaseOrderLine.csv
│   ├── Receipt.csv
│   ├── ReceiptLine.csv
│   ├── Invoice.csv
│   ├── InvoiceLine.csv
│   ├── Payment.csv
│   ├── SalesOrder.csv
│   ├── SalesOrderLine.csv
│   ├── Shipment.csv
│   ├── ShipmentLine.csv
│   ├── ARInvoice.csv
│   ├── ARReceipt.csv
│   ├── GLJournalEntry.csv
│   ├── GLJournalLine.csv
│   ├── GLAccount.csv
│   ├── XLAEvent.csv
│   ├── AccountingDistribution.csv
│   ├── ApprovalRecord.csv
│   ├── Contract.csv
│   ├── Currency.csv
│   ├── UOM.csv
│   └── SupplierQualification.csv
├── edges/
│   ├── PLACED_WITH.csv
│   ├── HAS_PO_LINE.csv
│   ├── ORDERS_ITEM.csv
│   ├── HAS_RECEIPT.csv
│   ├── HAS_RECEIPT_LINE.csv
│   ├── HAS_INVOICE.csv
│   ├── ORDERED_BY.csv
│   ├── SUPPLIES_ITEM.csv
│   ├── HAS_QUALIFICATION.csv
│   ├── INVOICED_BY.csv
│   ├── PAYS_INVOICE.csv
│   ├── PAID_TO.csv
│   ├── SOLD_TO.csv
│   ├── HAS_SO_LINE.csv
│   ├── SELLS_ITEM.csv
│   ├── HAS_SHIPMENT.csv
│   ├── HAS_SHIPMENT_LINE.csv
│   ├── HAS_AR_INVOICE.csv
│   ├── RECEIVED_FROM.csv
│   ├── APPLIES_TO.csv
│   ├── BOM_FOR.csv
│   ├── USES_COMPONENT.csv
│   ├── PARENT_ORG.csv
│   ├── BELONGS_TO_ORG.csv
│   ├── RECEIVED_AT.csv
│   ├── SHIPPED_FROM.csv
│   ├── HAS_JOURNAL_LINE.csv
│   ├── POSTED_TO.csv
│   ├── ACCOUNTING_FOR.csv
│   ├── DISTRIBUTED_TO.csv
│   ├── APPROVED_BY.csv
│   ├── APPROVAL_FOR.csv
│   ├── CONTRACT_WITH.csv
│   ├── UNDER_CONTRACT.csv
│   ├── HAS_PR_LINE.csv
│   ├── CONVERTS_TO_PO.csv
│   └── CONTAINS_PAYMENT.csv
└── README.md (this file)
```

## Prerequisites

- Python 3.10+
- Required packages (install from requirements.txt):
  ```bash
  pip install -r requirements.txt
  ```

## Usage

### Basic Usage

Generate test data with default settings:

```bash
python scripts/generate_test_data.py
```

This will create CSV files in `deploy/test-data/` directory.

### Custom Output Directory

```bash
python scripts/generate_test_data.py --output-dir /path/to/output
```

### Custom Random Seed

For reproducible data across runs:

```bash
python scripts/generate_test_data.py --seed 12345
```

### Custom Batch Size

Control how many records per CSV file:

```bash
python scripts/generate_test_data.py --batch-size 50000
```

## CSV Format

### Vertex CSV Format

```csv
vid,properties
SUP:00001,"{""supplier_number"": ""SUP00001"", ""supplier_name"": ""..."", ...}"
SUP:00002,"{""supplier_number"": ""SUP00002"", ...}"
```

### Edge CSV Format

```csv
src_vid,dst_vid,rank,properties
PO:00000001,SUP:00001,0,"{""order_date"": ""2024-04-01T00:00:00.000000Z"", ...}"
PO:00000001,POL:00000001-1,0,"{""org_id"": 1000, ...}"
```

## NebulaGraph Importer Configuration

Create a YAML configuration file for nebula-importer:

```yaml
version: v1
description: HoneyBadge Phase 1 Test Data
remove_temp_files: false

spaces:
  - name: honeybadge
    partition: 100
    replica_factor: 1
    vertex_edge_files:
      - path: ./vertices/Supplier.csv
        tags:
          - name: Supplier
      - path: ./vertices/Customer.csv
        tags:
          - name: Customer
      - path: ./vertices/Item.csv
        tags:
          - name: Item
      - path: ./vertices/Organization.csv
        tags:
          - name: Organization
      - path: ./vertices/Employee.csv
        tags:
          - name: Employee
      - path: ./vertices/Warehouse.csv
        tags:
          - name: Warehouse
      - path: ./vertices/PurchaseOrder.csv
        tags:
          - name: PurchaseOrder
      - path: ./vertices/PurchaseOrderLine.csv
        tags:
          - name: PurchaseOrderLine
      - path: ./vertices/Receipt.csv
        tags:
          - name: Receipt
      - path: ./vertices/ReceiptLine.csv
        tags:
          - name: ReceiptLine
      - path: ./vertices/Invoice.csv
        tags:
          - name: Invoice
      - path: ./vertices/InvoiceLine.csv
        tags:
          - name: InvoiceLine
      - path: ./vertices/Payment.csv
        tags:
          - name: Payment
      - path: ./vertices/SalesOrder.csv
        tags:
          - name: SalesOrder
      - path: ./vertices/SalesOrderLine.csv
        tags:
          - name: SalesOrderLine
      - path: ./vertices/Shipment.csv
        tags:
          - name: Shipment
      - path: ./vertices/ShipmentLine.csv
        tags:
          - name: ShipmentLine
      - path: ./vertices/ARInvoice.csv
        tags:
          - name: ARInvoice
      - path: ./vertices/ARReceipt.csv
        tags:
          - name: ARReceipt
      - path: ./vertices/GLJournalEntry.csv
        tags:
          - name: GLJournalEntry
      - path: ./vertices/GLJournalLine.csv
        tags:
          - name: GLJournalLine
      - path: ./vertices/GLAccount.csv
        tags:
          - name: GLAccount
      - path: ./vertices/XLAEvent.csv
        tags:
          - name: XLAEvent
      - path: ./vertices/AccountingDistribution.csv
        tags:
          - name: AccountingDistribution
      - path: ./vertices/ApprovalRecord.csv
        tags:
          - name: ApprovalRecord
      - path: ./vertices/Contract.csv
        tags:
          - name: Contract
      - path: ./vertices/BOM.csv
        tags:
          - name: BOM
      - path: ./vertices/BOMComponent.csv
        tags:
          - name: BOMComponent
      - path: ./vertices/SupplierQualification.csv
        tags:
          - name: SupplierQualification
      - path: ./vertices/Currency.csv
        tags:
          - name: Currency
      - path: ./vertices/UOM.csv
        tags:
          - name: UOM
      - path: ./vertices/PurchaseRequisition.csv
        tags:
          - name: PurchaseRequisition
      - path: ./vertices/PurchaseRequisitionLine.csv
        tags:
          - name: PurchaseRequisitionLine
    relation_files:
      - path: ./edges/PLACED_WITH.csv
        name: PLACED_WITH
      - path: ./edges/HAS_PO_LINE.csv
        name: HAS_PO_LINE
      - path: ./edges/ORDERS_ITEM.csv
        name: ORDERS_ITEM
      - path: ./edges/HAS_RECEIPT.csv
        name: HAS_RECEIPT
      - path: ./edges/HAS_RECEIPT_LINE.csv
        name: HAS_RECEIPT_LINE
      - path: ./edges/HAS_INVOICE.csv
        name: HAS_INVOICE
      - path: ./edges/ORDERED_BY.csv
        name: ORDERED_BY
      - path: ./edges/INVOICED_BY.csv
        name: INVOICED_BY
      - path: ./edges/PAYS_INVOICE.csv
        name: PAYS_INVOICE
      - path: ./edges/PAID_TO.csv
        name: PAID_TO
      - path: ./edges/SOLD_TO.csv
        name: SOLD_TO
      - path: ./edges/HAS_SO_LINE.csv
        name: HAS_SO_LINE
      - path: ./edges/SELLS_ITEM.csv
        name: SELLS_ITEM
      - path: ./edges/HAS_SHIPMENT.csv
        name: HAS_SHIPMENT
      - path: ./edges/HAS_SHIPMENT_LINE.csv
        name: HAS_SHIPMENT_LINE
      - path: ./edges/HAS_AR_INVOICE.csv
        name: HAS_AR_INVOICE
      - path: ./edges/RECEIVED_FROM.csv
        name: RECEIVED_FROM
      - path: ./edges/APPLIES_TO.csv
        name: APPLIES_TO
      - path: ./edges/PARENT_ORG.csv
        name: PARENT_ORG
      - path: ./edges/BELONGS_TO_ORG.csv
        name: BELONGS_TO_ORG
      - path: ./edges/RECEIVED_AT.csv
        name: RECEIVED_AT
      - path: ./edges/SHIPPED_FROM.csv
        name: SHIPPED_FROM
      - path: ./edges/HAS_JOURNAL_LINE.csv
        name: HAS_JOURNAL_LINE
      - path: ./edges/POSTED_TO.csv
        name: POSTED_TO
      - path: ./edges/ACCOUNTING_FOR.csv
        name: ACCOUNTING_FOR
      - path: ./edges/DISTRIBUTED_TO.csv
        name: DISTRIBUTED_TO
      - path: ./edges/APPROVED_BY.csv
        name: APPROVED_BY
      - path: ./edges/APPROVAL_FOR.csv
        name: APPROVAL_FOR
      - path: ./edges/CONTRACT_WITH.csv
        name: CONTRACT_WITH
      - path: ./edges/SUPPLIES_ITEM.csv
        name: SUPPLIES_ITEM
      - path: ./edges/HAS_QUALIFICATION.csv
        name: HAS_QUALIFICATION
      - path: ./edges/BOM_FOR.csv
        name: BOM_FOR
      - path: ./edges/USES_COMPONENT.csv
        name: USES_COMPONENT
```

## Import into NebulaGraph

### Step 1: Initialize NebulaGraph Schema

First, create the space and schema in NebulaGraph:

```bash
# Connect to NebulaGraph
nebula-console -addr localhost -port 9669 -user root -password nebula

# Run schema initialization
:source deploy/nebula/init-schema.ngql
:source deploy/nebula/init-edge-types.ngql
:source deploy/nebula/init-indexes.ngql
```

### Step 2: Import Data with nebula-importer

```bash
# Download nebula-importer if not already installed
# https://github.com/vesoft-inc/nebula-importer/releases

# Run the importer
./nebula-importer --config ./deploy/test-data/import.yaml --local timezone=Asia/Shanghai
```

### Step 3: Rebuild Indexes (if needed)

After import, rebuild indexes for optimal query performance:

```bash
nebula-console -addr localhost -port 9669 -user root -password nebula
:source deploy/nebula/rebuild-indexes.ngql
```

## Sample openCypher Queries

After importing, you can run these sample queries:

### Find PO with Three-way Match Issues

```cypher
MATCH (po:PurchaseOrder)-[:HAS_INVOICE]->(inv:Invoice)
WHERE inv.match_status IN ['UNMATCHED', 'PARTIAL']
RETURN po.po_number, po.total_amount, inv.invoice_number, inv.total_amount
LIMIT 50
```

### Find Suppliers with Expired Qualifications

```cypher
MATCH (sup:Supplier)-[:HAS_QUALIFICATION]->(sq:SupplierQualification)
WHERE sq.status = 'EXPIRED'
RETURN sup.supplier_number, sup.supplier_name, sq.qualification_type, sq.expiry_date
```

### Trace PO to Payment

```cypher
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(sup:Supplier)
      -[:HAS_INVOICE]->(inv:Invoice)<-[:PAYS_INVOICE]-(pay:Payment)
WHERE po.po_number = 'PO00000001'
RETURN po.po_number, sup.supplier_name, inv.invoice_number, inv.total_amount, pay.payment_number, pay.amount
```

### Find High-Value Orders by Organization

```cypher
MATCH (po:PurchaseOrder)
WHERE po.org_id = 1001 AND po.total_amount > 100000
RETURN po.po_number, po.order_date, po.total_amount, po.status
ORDER BY po.total_amount DESC
LIMIT 20
```

### Count Entities by Type

```cypher
MATCH (n)
RETURN labels(n)[0] as entity_type, count(*) as count
ORDER BY count DESC
```

## Performance Notes

- Generation time: ~5-10 minutes for full dataset
- CSV file count: ~70 vertex files, ~40 edge files
- Total CSV size: ~2-3 GB
- Import time: Varies based on NebulaGraph hardware (typically 15-30 minutes)

## Data Refresh

To regenerate test data with new anomalies:

```bash
# Remove old data
rm -rf deploy/test-data/vertices/*.csv deploy/test-data/edges/*.csv

# Regenerate
python scripts/generate_test_data.py --seed $(date +%s)
```

## Troubleshooting

### Out of Memory

If you encounter memory issues during generation, reduce batch size:

```bash
python scripts/generate_test_data.py --batch-size 5000
```

### Import Failures

Check nebula-importer logs for detailed error messages. Common issues:

1. Schema mismatch - ensure tags and edge types match the CSV headers
2. VID format issues - ensure VIDs match the FIXED_STRING(64) format
3. Property type mismatches - check timestamp formats and numeric values

## License

Proprietary - HoneyBadge Team
