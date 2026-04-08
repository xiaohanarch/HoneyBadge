#!/bin/bash
# NebulaGraph Schema Initialization Script
# Usage: docker-compose --profile tools up -d
#        docker exec -it honeybadge-nebula-console
# Or directly: docker exec -it honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula

set -e

echo "=========================================="
echo "HoneyBadge NebulaGraph Schema Initialization"
echo "=========================================="

# Wait for NebulaGraph to be ready
echo "Waiting for NebulaGraph to be ready..."
for i in {1..30}; do
    if docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula -e "SHOW HOSTS" 2>/dev/null | grep -q "ONLINE"; then
        echo "NebulaGraph is ready!"
        break
    fi
    echo "Attempt $i/30: NebulaGraph not ready yet..."
    sleep 5
done

echo "Creating Space and Schema..."

# Create Space
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
CREATE SPACE IF NOT EXISTS honeybadge (partition_num = 100, replica_factor = 1, vid_type = FIXED_STRING(64));
EOF

sleep 5

# Use the space
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
USE honeybadge;
EOF

# Create Tags (from init-schema.ngql)
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
USE honeybadge;

-- Master Data Tags
CREATE TAG IF NOT EXISTS Supplier(supplier_number STRING NOT NULL, supplier_name STRING NOT NULL, supplier_type STRING, status STRING, country STRING, city STRING, address STRING, contact_person STRING, contact_phone STRING, contact_email STRING, bank_account STRING, bank_name STRING, tax_id STRING, currency STRING DEFAULT "CNY", payment_terms STRING, credit_rating STRING, registration_date TIMESTAMP, qualification_expiry TIMESTAMP, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Customer(customer_number STRING NOT NULL, customer_name STRING NOT NULL, customer_type STRING, status STRING, country STRING, city STRING, address STRING, contact_person STRING, contact_phone STRING, contact_email STRING, credit_limit DOUBLE, payment_terms STRING, tax_id STRING, currency STRING DEFAULT "CNY", sales_region STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Item(item_number STRING NOT NULL, item_name STRING NOT NULL, item_description STRING, item_type STRING, category STRING, uom STRING, standard_cost DOUBLE, list_price DOUBLE, weight DOUBLE, weight_uom STRING, lead_time_days INT64, safety_stock DOUBLE, min_order_qty DOUBLE, status STRING, abc_class STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Organization(org_code STRING NOT NULL, org_name STRING NOT NULL, org_type STRING, parent_org_code STRING, legal_entity STRING, country STRING, city STRING, status STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Employee(employee_number STRING NOT NULL, employee_name STRING NOT NULL, position STRING, department STRING, email STRING, phone STRING, manager_id STRING, hire_date TIMESTAMP, status STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Warehouse(warehouse_code STRING NOT NULL, warehouse_name STRING NOT NULL, warehouse_type STRING, location STRING, capacity DOUBLE, status STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS BOM(bom_number STRING NOT NULL, bom_name STRING, bom_type STRING, effective_from TIMESTAMP, effective_to TIMESTAMP, quantity DOUBLE DEFAULT 1.0, uom STRING, status STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS BOMComponent(component_seq INT64, quantity_per DOUBLE NOT NULL, uom STRING, effective_from TIMESTAMP, effective_to TIMESTAMP, yield_rate DOUBLE DEFAULT 1.0, wip_supply_type STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Currency(currency_code STRING NOT NULL, currency_name STRING, symbol STRING, decimal_places INT64 DEFAULT 2, is_base_currency BOOL DEFAULT false, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS UOM(uom_code STRING NOT NULL, uom_name STRING, uom_class STRING, base_uom STRING, conversion_rate DOUBLE DEFAULT 1.0, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);
EOF

echo "Creating procurement tags..."
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
USE honeybadge;

CREATE TAG IF NOT EXISTS PurchaseRequisition(pr_number STRING NOT NULL, pr_type STRING, description STRING, status STRING, requester STRING, request_date TIMESTAMP, need_by_date TIMESTAMP, total_amount DOUBLE, currency STRING DEFAULT "CNY", approval_date TIMESTAMP, approver STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS PurchaseRequisitionLine(line_number INT64 NOT NULL, quantity DOUBLE NOT NULL, unit_price DOUBLE, amount DOUBLE, uom STRING, need_by_date TIMESTAMP, suggested_vendor STRING, status STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS PurchaseOrder(po_number STRING NOT NULL, po_type STRING, description STRING, status STRING, buyer STRING, order_date TIMESTAMP, approved_date TIMESTAMP, total_amount DOUBLE NOT NULL, currency STRING DEFAULT "CNY", exchange_rate DOUBLE DEFAULT 1.0, payment_terms STRING, freight_terms STRING, ship_to_location STRING, bill_to_location STRING, close_date TIMESTAMP, cancel_reason STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS PurchaseOrderLine(line_number INT64 NOT NULL, line_type STRING, quantity DOUBLE NOT NULL, unit_price DOUBLE NOT NULL, amount DOUBLE NOT NULL, uom STRING, need_by_date TIMESTAMP, promised_date TIMESTAMP, received_quantity DOUBLE DEFAULT 0, invoiced_quantity DOUBLE DEFAULT 0, status STRING, tax_code STRING, tax_rate DOUBLE DEFAULT 0, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Receipt(receipt_number STRING NOT NULL, receipt_type STRING, receipt_date TIMESTAMP NOT NULL, status STRING, receiver STRING, total_quantity DOUBLE, warehouse STRING, comments STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS ReceiptLine(line_number INT64 NOT NULL, received_quantity DOUBLE NOT NULL, accepted_quantity DOUBLE, rejected_quantity DOUBLE DEFAULT 0, uom STRING, inspection_status STRING, lot_number STRING, sublocation STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS SupplierQualification(qualification_id STRING NOT NULL, qualification_type STRING, status STRING, issue_date TIMESTAMP, expiry_date TIMESTAMP, issuing_body STRING, scope STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);
EOF

echo "Creating payable tags..."
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
USE honeybadge;

CREATE TAG IF NOT EXISTS Invoice(invoice_number STRING NOT NULL, invoice_type STRING, invoice_date TIMESTAMP NOT NULL, due_date TIMESTAMP, status STRING, total_amount DOUBLE NOT NULL, tax_amount DOUBLE DEFAULT 0, currency STRING DEFAULT "CNY", exchange_rate DOUBLE DEFAULT 1.0, payment_method STRING, description STRING, gl_date TIMESTAMP, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS InvoiceLine(line_number INT64 NOT NULL, line_type STRING, quantity DOUBLE, unit_price DOUBLE, amount DOUBLE NOT NULL, tax_code STRING, tax_rate DOUBLE, description STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Payment(payment_number STRING NOT NULL, payment_type STRING, payment_date TIMESTAMP NOT NULL, amount DOUBLE NOT NULL, currency STRING DEFAULT "CNY", exchange_rate DOUBLE DEFAULT 1.0, status STRING, bank_account STRING, payment_method STRING, check_number STRING, cleared_date TIMESTAMP, void_date TIMESTAMP, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS PaymentBatch(batch_number STRING NOT NULL, batch_date TIMESTAMP, total_amount DOUBLE, payment_count INT64, status STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);
EOF

echo "Creating OTC tags..."
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
USE honeybadge;

CREATE TAG IF NOT EXISTS SalesOrder(so_number STRING NOT NULL, order_type STRING, order_date TIMESTAMP NOT NULL, status STRING, total_amount DOUBLE NOT NULL, currency STRING DEFAULT "CNY", exchange_rate DOUBLE DEFAULT 1.0, payment_terms STRING, ship_to_address STRING, bill_to_address STRING, salesperson STRING, requested_date TIMESTAMP, scheduled_date TIMESTAMP, cancel_reason STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS SalesOrderLine(line_number INT64 NOT NULL, quantity DOUBLE NOT NULL, unit_price DOUBLE NOT NULL, amount DOUBLE NOT NULL, uom STRING, shipped_quantity DOUBLE DEFAULT 0, invoiced_quantity DOUBLE DEFAULT 0, status STRING, tax_code STRING, tax_rate DOUBLE DEFAULT 0, scheduled_ship_date TIMESTAMP, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Shipment(shipment_number STRING NOT NULL, shipment_date TIMESTAMP NOT NULL, status STRING, carrier STRING, tracking_number STRING, total_quantity DOUBLE, warehouse STRING, delivery_date TIMESTAMP, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS ShipmentLine(line_number INT64 NOT NULL, shipped_quantity DOUBLE NOT NULL, uom STRING, lot_number STRING, serial_number STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS ARInvoice(invoice_number STRING NOT NULL, invoice_type STRING, invoice_date TIMESTAMP NOT NULL, due_date TIMESTAMP, status STRING, total_amount DOUBLE NOT NULL, tax_amount DOUBLE DEFAULT 0, currency STRING DEFAULT "CNY", exchange_rate DOUBLE DEFAULT 1.0, payment_terms STRING, gl_date TIMESTAMP, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS ARReceipt(receipt_number STRING NOT NULL, receipt_type STRING, receipt_date TIMESTAMP NOT NULL, amount DOUBLE NOT NULL, currency STRING DEFAULT "CNY", status STRING, payment_method STRING, bank_account STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);
EOF

echo "Creating GL tags..."
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
USE honeybadge;

CREATE TAG IF NOT EXISTS GLAccount(account_code STRING NOT NULL, account_name STRING NOT NULL, account_type STRING, parent_account STRING, level INT64, is_leaf BOOL DEFAULT true, currency STRING, status STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS GLJournalEntry(journal_number STRING NOT NULL, journal_name STRING, journal_source STRING, journal_category STRING, period_name STRING, gl_date TIMESTAMP NOT NULL, status STRING, total_debit DOUBLE, total_credit DOUBLE, description STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS GLJournalLine(line_number INT64 NOT NULL, debit_amount DOUBLE DEFAULT 0, credit_amount DOUBLE DEFAULT 0, description STRING, reference STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS XLAEvent(event_id STRING NOT NULL, event_class STRING, event_type STRING, event_date TIMESTAMP NOT NULL, accounting_date TIMESTAMP, status STRING, source_doc_type STRING, source_doc_id STRING, description STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS AccountingDistribution(distribution_id STRING NOT NULL, line_number INT64, debit_amount DOUBLE DEFAULT 0, credit_amount DOUBLE DEFAULT 0, currency STRING DEFAULT "CNY", accounting_class STRING, posted_flag BOOL DEFAULT false, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS ApprovalRecord(approval_id STRING NOT NULL, doc_type STRING, doc_number STRING, approval_action STRING, approver STRING, approval_date TIMESTAMP, comments STRING, approval_level INT64, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);

CREATE TAG IF NOT EXISTS Contract(contract_number STRING NOT NULL, contract_type STRING, contract_name STRING, status STRING, start_date TIMESTAMP, end_date TIMESTAMP, total_amount DOUBLE, currency STRING DEFAULT "CNY", description STRING, org_id INT64, dept_id INT64, data_scope STRING, created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true);
EOF

echo "Creating Edge Types..."
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
USE honeybadge;

-- Procurement Edges
CREATE EDGE TYPE IF NOT EXISTS PLACED_WITH(order_date TIMESTAMP, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_PO_LINE(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS ORDERS_ITEM(quantity DOUBLE, unit_price DOUBLE, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS CONVERTS_TO_PO(conversion_date TIMESTAMP, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_PR_LINE(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_RECEIPT(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_RECEIPT_LINE(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_INVOICE(match_status STRING, match_date TIMESTAMP, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS ORDERED_BY(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_QUALIFICATION(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS SUPPLIES_ITEM(priority INT64, unit_price DOUBLE, lead_time_days INT64, status STRING, effective_from TIMESTAMP, effective_to TIMESTAMP, org_id INT64, dept_id INT64);

-- Payable Edges
CREATE EDGE TYPE IF NOT EXISTS HAS_INVOICE_LINE(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS INVOICED_BY(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS PAYS_INVOICE(paid_amount DOUBLE, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS PAID_TO(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS CONTAINS_PAYMENT(org_id INT64, dept_id INT64);

-- OTC Edges
CREATE EDGE TYPE IF NOT EXISTS SOLD_TO(order_date TIMESTAMP, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_SO_LINE(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS SELLS_ITEM(quantity DOUBLE, unit_price DOUBLE, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_SHIPMENT(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_SHIPMENT_LINE(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_AR_INVOICE(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS RECEIVED_FROM(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS APPLIES_TO(applied_amount DOUBLE, org_id INT64, dept_id INT64);

-- Master Data Edges
CREATE EDGE TYPE IF NOT EXISTS BOM_FOR(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS USES_COMPONENT(quantity_per DOUBLE, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS PARENT_ORG(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS BELONGS_TO_ORG(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS RECEIVED_AT(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS SHIPPED_FROM(org_id INT64, dept_id INT64);

-- Accounting Edges
CREATE EDGE TYPE IF NOT EXISTS ACCOUNTING_FOR(event_class STRING, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS POSTED_TO(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS HAS_JOURNAL_LINE(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS DISTRIBUTED_TO(org_id INT64, dept_id INT64);

-- Approval/Contract Edges
CREATE EDGE TYPE IF NOT EXISTS APPROVED_BY(org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS APPROVAL_FOR(doc_type STRING, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS CONTRACT_WITH(party_type STRING, org_id INT64, dept_id INT64);
CREATE EDGE TYPE IF NOT EXISTS UNDER_CONTRACT(org_id INT64, dept_id INT64);
EOF

echo "Creating Indexes..."
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
USE honeybadge;

CREATE TAG INDEX idx_supplier_number ON Supplier(supplier_number(64));
CREATE TAG INDEX idx_customer_number ON Customer(customer_number(64));
CREATE TAG INDEX idx_item_number ON Item(item_number(64));
CREATE TAG INDEX idx_org_code ON Organization(org_code(64));
CREATE TAG INDEX idx_employee_number ON Employee(employee_number(64));
CREATE TAG INDEX idx_po_number ON PurchaseOrder(po_number(64));
CREATE TAG INDEX idx_pr_number ON PurchaseRequisition(pr_number(64));
CREATE TAG INDEX idx_receipt_number ON Receipt(receipt_number(64));
CREATE TAG INDEX idx_invoice_number ON Invoice(invoice_number(64));
CREATE TAG INDEX idx_payment_number ON Payment(payment_number(64));
CREATE TAG INDEX idx_so_number ON SalesOrder(so_number(64));
CREATE TAG INDEX idx_shipment_number ON Shipment(shipment_number(64));
CREATE TAG INDEX idx_ar_invoice_number ON ARInvoice(invoice_number(64));
CREATE TAG INDEX idx_ar_receipt_number ON ARReceipt(receipt_number(64));
CREATE TAG INDEX idx_journal_number ON GLJournalEntry(journal_number(64));
CREATE TAG INDEX idx_contract_number ON Contract(contract_number(64));
CREATE TAG INDEX idx_bom_number ON BOM(bom_number(64));

CREATE TAG INDEX idx_po_status ON PurchaseOrder(status(20));
CREATE TAG INDEX idx_invoice_status ON Invoice(status(20));
CREATE TAG INDEX idx_so_status ON SalesOrder(status(20));
CREATE TAG INDEX idx_supplier_status ON Supplier(status(20));
CREATE TAG INDEX idx_item_status ON Item(status(20));

CREATE TAG INDEX idx_po_org ON PurchaseOrder(org_id);
CREATE TAG INDEX idx_invoice_org ON Invoice(org_id);
CREATE TAG INDEX idx_so_org ON SalesOrder(org_id);
CREATE TAG INDEX idx_supplier_org ON Supplier(org_id);

CREATE TAG INDEX idx_po_date_status ON PurchaseOrder(order_date, status(20));
CREATE TAG INDEX idx_invoice_date_status ON Invoice(invoice_date, status(20));
CREATE TAG INDEX idx_so_date_status ON SalesOrder(order_date, status(20));
CREATE TAG INDEX idx_po_org_status ON PurchaseOrder(org_id, status(20));
CREATE TAG INDEX idx_invoice_org_status ON Invoice(org_id, status(20));

CREATE EDGE INDEX idx_has_invoice_status ON HAS_INVOICE(match_status(20));
CREATE EDGE INDEX idx_supplies_item_status ON SUPPLIES_ITEM(status(20));
CREATE EDGE INDEX idx_placed_with_org ON PLACED_WITH(org_id);
CREATE EDGE INDEX idx_sold_to_org ON SOLD_TO(org_id);
EOF

echo "Rebuilding indexes..."
sleep 5
docker exec honeybadge-nebula-graphd nebula-console -addr localhost -port 9669 -u root -p nebula << 'EOF'
USE honeybadge;
REBUILD TAG INDEX;
REBUILD EDGE INDEX;
EOF

echo "=========================================="
echo "Schema initialization complete!"
echo "=========================================="
echo "Run: SHOW TAGS and SHOW EDGES to verify"
