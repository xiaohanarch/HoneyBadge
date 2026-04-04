# Receivable Domain Ontology (OTC) — 应收域本体（订单到收款流程）

> Version: v1.0
> Date: 2026-04-04
> Domain: Order-to-Cash (OTC) — 订单到收款
> NebulaGraph Space: honeybadge

---

## 1. Entity Definitions — 实体定义

### 1.1 SalesOrder (销售订单, SO)

**Business Meaning (业务含义)**:
A commitment to sell goods or services to a Customer at agreed terms. The SO is the starting point of the Order-to-Cash (OTC) cycle. Once booked (status=BOOKED), it represents a binding sales contract that the company must fulfill.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `so_number` | STRING NOT NULL | Unique identifier (e.g., "SO-2026-00001") |
| `order_type` | STRING | STANDARD (标准销售订单) / RETURN (退货订单) / INTERNAL (内部订单) |
| `order_date` | TIMESTAMP NOT NULL | Date order was placed |
| `status` | STRING | DRAFT / BOOKED / SHIPPED / INVOICED / CLOSED / CANCELLED |
| `total_amount` | DOUBLE NOT NULL | Total order value including tax |
| `currency` | STRING DEFAULT "CNY" | Transaction currency |
| `exchange_rate` | DOUBLE DEFAULT 1.0 | Exchange rate for foreign currency |
| `payment_terms` | STRING | NET30 / NET60 / PREPAID / COD |
| `ship_to_address` | STRING | Delivery destination address |
| `bill_to_address` | STRING | Invoice billing address |
| `salesperson` | STRING | Employee number of the sales person |
| `requested_date` | TIMESTAMP | Customer requested delivery date |
| `scheduled_date` | TIMESTAMP | Confirmed scheduled shipment date |
| `cancel_reason` | STRING | Reason for cancellation if applicable |

**Status Lifecycle**:
```
DRAFT → BOOKED → SHIPPED → INVOICED → CLOSED
              ↓                        ↓
         CANCELLED                PARTIALLY_SHIPPED
```

- DRAFT: Created but not yet confirmed
- BOOKED: Confirmed and legally binding sales contract
- SHIPPED: At least partial shipment has occurred
- INVOICED: At least one invoice has been created
- CLOSED: Fully shipped and invoiced, or formally closed
- CANCELLED: Terminated before fulfillment

**VID Format**: `SO:{so_number}` (e.g., `SO:SO-2026-00001`)

---

### 1.2 SalesOrderLine (销售订单行, SOLine)

**Business Meaning (业务含义)**:
Individual line items within a Sales Order specifying the Item, quantity, unit price, and delivery requirements. Tracks how much has been shipped (shipped_quantity) and invoiced (invoiced_quantity).

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `line_number` | INT64 NOT NULL | Line sequence number |
| `quantity` | DOUBLE NOT NULL | Ordered quantity |
| `unit_price` | DOUBLE NOT NULL | Selling price |
| `amount` | DOUBLE NOT NULL | line_amount = quantity × unit_price |
| `uom` | STRING | Unit of measure |
| `shipped_quantity` | DOUBLE DEFAULT 0 | Total quantity shipped across all shipments |
| `invoiced_quantity` | DOUBLE DEFAULT 0 | Total quantity invoiced |
| `status` | STRING | OPEN / PARTIAL / SHIPPED / INVOICED / CLOSED |
| `tax_code` | STRING | Tax classification |
| `tax_rate` | DOUBLE DEFAULT 0 | Tax rate |
| `scheduled_ship_date` | TIMESTAMP | Scheduled ship date for this line |

**Business Rule**: `amount = quantity × unit_price`

**VID Format**: `SOL:{so_number}:{line_number}` (e.g., `SOL:SO-2026-00001:1`)

---

### 1.3 Shipment (发货单)

**Business Meaning (业务含义)**:
A document confirming that goods have been shipped to the customer. Shipment confirms the transfer of ownership (risk and title) from seller to buyer, which typically triggers the right to invoice.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `shipment_number` | STRING NOT NULL | Unique identifier (e.g., "SHIP-2026-00001") |
| `shipment_date` | TIMESTAMP NOT NULL | Date goods were shipped |
| `status` | STRING | PLANNED / PICKED / SHIPPED / DELIVERED / CANCELLED |
| `carrier` | STRING | Shipping carrier name (e.g., "SF Express", "DHL") |
| `tracking_number` | STRING | Carrier tracking number |
| `total_quantity` | DOUBLE | Total quantity shipped |
| `warehouse` | STRING | Warehouse code where shipment originated |
| `delivery_date` | TIMESTAMP | Actual or estimated delivery date |

**Status Lifecycle**:
```
PLANNED → PICKED → SHIPPED → DELIVERED
                    ↓
              CANCELLED
```

**VID Format**: `SHIP:{shipment_number}` (e.g., `SHIP:SHIP-2026-00001`)

---

### 1.4 ShipmentLine (发货单行)

**Business Meaning (业务含义)**:
Individual line items within a Shipment.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `line_number` | INT64 NOT NULL | Line sequence number |
| `shipped_quantity` | DOUBLE NOT NULL | Quantity shipped on this line |
| `uom` | STRING | Unit of measure |
| `lot_number` | STRING | Lot/batch number for traceability |
| `serial_number` | STRING | Serial number (if applicable) |

**VID Format**: `SHIPL:{shipment_number}:{line_number}` (e.g., `SHIPL:SHIP-2026-00001:1`)

---

### 1.5 ARInvoice (应收发票, AR Invoice)

**Business Meaning (业务含义)**:
An invoice issued to a Customer requesting payment for goods/services delivered. AR Invoice creates the accounts receivable (money owed by customer). Follows the Shipment in the OTC cycle.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `invoice_number` | STRING NOT NULL | Unique identifier (e.g., "AR-2026-00001") |
| `invoice_type` | STRING | INVOICE (标准发票) / CREDIT_MEMO (贷项通知单/红字发票) / DEBIT_MEMO (借项通知单) |
| `invoice_date` | TIMESTAMP NOT NULL | Invoice issue date |
| `due_date` | TIMESTAMP | Payment due date |
| `status` | STRING | DRAFT / COMPLETE / COLLECTED / CANCELLED |
| `total_amount` | DOUBLE NOT NULL | Invoice total |
| `tax_amount` | DOUBLE DEFAULT 0 | Tax portion |
| `currency` | STRING DEFAULT "CNY" | Invoice currency |
| `exchange_rate` | DOUBLE DEFAULT 1.0 | Exchange rate for foreign currency |
| `payment_terms` | STRING | Payment terms |
| `gl_date` | TIMESTAMP | GL posting date |

**Status Lifecycle**:
```
DRAFT → COMPLETE → COLLECTED
                   ↓
             CANCELLED
```

- DRAFT: Created but not yet confirmed
- COMPLETE: Confirmed and sent to customer
- COLLECTED: Payment received
- CANCELLED: Cancelled (requires credit memo for previously complete invoices)

**VID Format**: `ARI:{invoice_number}` (e.g., `ARI:AR-2026-00001`)

---

### 1.6 ARReceipt (应收收款, AR Receipt)

**Business Meaning (业务含义)**:
A record of payment received from a Customer. AR Receipt reduces the customer's outstanding balance and increases cash.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `receipt_number` | STRING NOT NULL | Unique identifier (e.g., "ARR-2026-00001") |
| `receipt_type` | STRING | STANDARD (标准收款) / MISC (杂项收款) |
| `receipt_date` | TIMESTAMP NOT NULL | Date payment was received |
| `amount` | DOUBLE NOT NULL | Receipt amount |
| `currency` | STRING DEFAULT "CNY" | Receipt currency |
| `status` | STRING | CONFIRMED / APPLIED / REVERSED |
| `payment_method` | STRING | WIRE / CHECK / CASH / CREDIT_CARD |
| `bank_account` | STRING | Bank account that received the payment |

**Status Lifecycle**:
```
CONFIRMED → APPLIED → REVERSED
```

- CONFIRMED: Payment received and logged
- APPLIED: Payment applied to customer invoices
- REVERSED: Payment reversed (e.g., returned check)

**VID Format**: `ARR:{receipt_number}` (e.g., `ARR:ARR-2026-00001`)

---

## 2. Relationship Definitions — 关系定义

### 2.1 SOLD_TO (销售订单卖给客户)

**Direction**: SalesOrder → Customer
**Edge Properties**: `order_date TIMESTAMP`

**Business Meaning (业务含义)**:
Links a Sales Order to the Customer (buyer). This is the counterparty relationship for the sales transaction.

---

### 2.2 HAS_SO_LINE (销售订单包含行)

**Direction**: SalesOrder → SalesOrderLine

**Business Meaning**: The line items that make up the Sales Order.

---

### 2.3 SELLS_ITEM (SO行销售物料)

**Direction**: SalesOrderLine → Item

**Business Meaning (业务含义)**:
Links the SO line to the Item being sold. Used for sales analytics by product.

---

### 2.4 HAS_SHIPMENT (销售订单对应发货)

**Direction**: SalesOrder → Shipment

**Business Meaning (业务含义)**:
Links a Sales Order to the Shipment(s) created against it. One SO can have multiple shipments (partial shipments to different addresses or on different dates).

---

### 2.5 HAS_SHIPMENT_LINE (发货单包含行)

**Direction**: Shipment → ShipmentLine

**Business Meaning**: The line items within a shipment.

---

### 2.6 SHIPPED_FROM (从仓库发货)

**Direction**: Shipment → Warehouse

**Business Meaning (业务含义)**:
The warehouse from which the goods were shipped.

---

### 2.7 HAS_AR_INVOICE (销售订单对应应收发票)

**Direction**: SalesOrder → ARInvoice

**Business Meaning (业务含义)**:
Links an SO to the AR Invoice(s) created from it.

---

### 2.8 RECEIVED_FROM (收款来自客户)

**Direction**: ARReceipt → Customer

**Business Meaning (业务含义)**:
Links a Receipt to the Customer who made the payment.

---

### 2.9 APPLIES_TO (收款核销应收发票)

**Direction**: ARReceipt → ARInvoice
**Edge Properties**: `applied_amount DOUBLE` — portion of receipt applied to this invoice

**Business Meaning (业务含义)**:
Links a Receipt to the Invoice(s) it pays. One Receipt can apply to multiple Invoices (customer paying multiple invoices in one payment), and one Invoice can be paid by multiple Receipts (partial payments).

**Business Rule**: `SUM(ARReceipt.APPLIES_TO.applied_amount for all receipts applied to one invoice) <= ARInvoice.total_amount`

---

## 3. OTC Temporal Constraints — 订单到收款时序约束

**CRITICAL BUSINESS RULE — OTC Temporal Sequence**:

The OTC process has strict temporal ordering:

```
SO.order_date ≤ Shipment.shipment_date ≤ ARInvoice.invoice_date ≤ ARReceipt.receipt_date
```

| Stage | Document | Date Field | Constraint |
|-------|----------|------------|------------|
| 1 | SalesOrder | order_date | Must be earliest |
| 2 | Shipment | shipment_date | Must be after SO.order_date |
| 3 | ARInvoice | invoice_date | Must be after Shipment.shipment_date |
| 4 | ARReceipt | receipt_date | Must be after ARInvoice.invoice_date |

**Violations and Their Business Implications**:
| Violation Type | Implication |
|---------------|-------------|
| Shipment.shipment_date < SO.order_date | Retroactive shipment — possible data entry error or fraud |
| ARInvoice.date < Shipment.date | Pre-invoice — billing before shipment is unusual unless特殊情况 |
| ARReceipt.date < ARInvoice.date | Advance receipt — may indicate payment before invoice issued |

---

## 4. Business Rules — 业务规则

### Rule 1: Shipment Quantity Constraint (发货数量约束)

**Rule Definition**: Total `shipped_quantity` across all Shipments for a given SOLine should not exceed `SOLine.quantity`.

**Business Meaning**: Cannot ship more than was ordered. Overshipment may indicate:
1. Data entry error
2. Customer agreement not captured in system
3. Potential revenue recognition issues

**Tolerance**: In practice, some systems allow small overage (e.g., < 1%) due to rounding or packing quantities.

---

### Rule 2: Credit Limit Enforcement (信用额度控制)

**Rule Definition**: A Customer's total outstanding ARInvoice amount (status=COMPLETE, not COLLECTED) should not exceed their credit_limit.

**Business Meaning**: Credit limits protect the company from over-extending to customers who may not pay. Exceeding credit limit indicates:
1. Customer financial stress
2. Sales team bypassing credit controls
3. Need for credit review

**Detection Query**:
```ngql
-- Find customers where total outstanding > credit limit
MATCH (so:SalesOrder)-[:SOLD_TO]->(c:Customer),
      (so)-[:HAS_AR_INVOICE]->(inv:ARInvoice)
WHERE inv.ARInvoice.status == "COMPLETE"
  AND NOT (inv)<-[:APPLIES_TO]-(:ARReceipt)  -- Not yet paid
WITH c.Customer.customer_number AS customer_number,
     c.Customer.customer_name AS customer_name,
     c.Customer.credit_limit AS credit_limit,
     sum(inv.ARInvoice.total_amount) AS total_outstanding
WHERE total_outstanding > c.Customer.credit_limit
RETURN customer_number, customer_name, credit_limit, total_outstanding,
       (total_outstanding - credit_limit) AS over_limit_amount
```

---

### Rule 3: Receipt Application Integrity (收款核销完整性)

**Rule Definition**: `SUM(Receipt.applied_amount for all ARReceipt applied to an ARInvoice) = ARInvoice.total_amount` when fully applied.

**Business Meaning**: Ensures payments are correctly applied to invoices. Mismatches indicate:
1. Data entry errors
2. Partial application pending
3. Unidentified payments (cash not matched to invoice)

---

### Rule 4: Invoice to Shipment Consistency (发票与发货一致性)

**Rule Definition**: ARInvoice total_amount should be based on actual shipped quantities, not ordered quantities.

**Business Meaning**: Revenue should be recognized for goods actually delivered. Invoicing for undelivered goods overstates revenue.

---

## 5. Example nGQL Queries — nGQL 查询示例

### Query 1: Customer Order and Shipment Status (客户订单及发货状态)

**Business Context**: Sales rep checks the status of all orders for a specific customer to provide delivery updates.

```ngql
-- Find all Sales Orders for a customer with shipment details
MATCH (so:SalesOrder)-[:SOLD_TO]->(c:Customer)
WHERE c.Customer.customer_number == "C001"
OPTIONAL MATCH (so)-[:HAS_SO_LINE]->(sol:SalesOrderLine)
OPTIONAL MATCH (so)-[:HAS_SHIPMENT]->(ship:Shipment)
WITH so, c, sol, ship,
     -- Calculate shipment progress
     CASE
       WHEN so.SalesOrder.status IN ["SHIPPED", "INVOICED", "CLOSED"]
            AND sol.SalesOrderLine.quantity > 0
       THEN (sol.SalesOrderLine.shipped_quantity / sol.SalesOrderLine.quantity) * 100
       ELSE 0
     END AS ship_complete_pct
RETURN so.SalesOrder.so_number AS so_number,
       so.SalesOrder.order_date AS order_date,
       so.SalesOrder.status AS order_status,
       so.SalesOrder.total_amount AS order_amount,
       collect({
         line_number: sol.SalesOrderLine.line_number,
         item: sol.SalesOrderLine.line_number,  -- Would join to Item in real query
         ordered_qty: sol.SalesOrderLine.quantity,
         shipped_qty: sol.SalesOrderLine.shipped_quantity,
         ship_pct: ship_complete_pct
       }) AS line_details,
       collect(DISTINCT ship.Shipment.shipment_number) AS shipment_numbers,
       collect(DISTINCT ship.Shipment.status) AS shipment_statuses
ORDER BY so.SalesOrder.order_date DESC
LIMIT 20;
```

---

### Query 2: Customer AR Aging Analysis (客户应收账龄分析)

**Business Context**: Collections team reviews outstanding invoices by customer and age to prioritize collection efforts.

```ngql
-- Analyze AR aging by customer
-- Show outstanding invoices categorized by how overdue they are
MATCH (inv:ARInvoice)<-[:HAS_AR_INVOICE]-(so:SalesOrder)-[:SOLD_TO]->(c:Customer)
WHERE inv.ARInvoice.status == "COMPLETE"
  AND NOT (inv)<-[:APPLIES_TO]-(:ARReceipt)  -- Unpaid invoices only
WITH c.Customer.customer_number AS customer_number,
     c.Customer.customer_name AS customer_name,
     c.Customer.credit_limit AS credit_limit,
     inv.ARInvoice.invoice_number AS invoice_number,
     inv.ARInvoice.invoice_date AS invoice_date,
     inv.ARInvoice.due_date AS due_date,
     inv.ARInvoice.total_amount AS invoice_amount,
     inv.ARInvoice.currency AS currency,
     -- Calculate days overdue
     datetime_diff(now(), inv.ARInvoice.due_date) / 86400 AS days_overdue
WITH customer_number,
     customer_name,
     credit_limit,
     collect({
       invoice_number: invoice_number,
       invoice_date: invoice_date,
       due_date: due_date,
       amount: invoice_amount,
       days_overdue: days_overdue,
       aging_bucket: CASE
         WHEN days_overdue > 90 THEN "OVERDUE_90+"
         WHEN days_overdue > 60 THEN "OVERDUE_61-90"
         WHEN days_overdue > 30 THEN "OVERDUE_31-60"
         WHEN days_overdue > 0 THEN "OVERDUE_1-30"
         ELSE "NOT_YET_DUE"
       END
     }) AS invoices,
     sum(invoice_amount) AS total_outstanding
-- Unwind to get per-invoice detail while maintaining customer-level aggregation
UNWIND invoices AS inv
WITH customer_number,
     customer_name,
     credit_limit,
     inv.invoice_number AS invoice_number,
     inv.invoice_date AS invoice_date,
     inv.due_date AS due_date,
     inv.amount AS amount,
     inv.days_overdue AS days_overdue,
     inv.aging_bucket AS aging_bucket,
     total_outstanding,
     (total_outstanding - credit_limit) AS over_limit_amount,
     CASE
       WHEN total_outstanding > credit_limit THEN "EXCEEDED"
       WHEN total_outstanding > credit_limit * 0.8 THEN "WARNING"
       ELSE "OK"
     END AS credit_status
ORDER BY days_overdue DESC
LIMIT 100;
```

---

### Query 3: SO to AR Invoice Complete Trace (订单到发票完整追溯)

**Business Context**: Finance team traces a sales order through to invoicing and payment for revenue recognition audit.

```ngql
-- Full OTC lifecycle trace: SO → Shipment → ARInvoice → ARReceipt
MATCH (so:SalesOrder)-[:SOLD_TO]->(c:Customer)
WHERE so.SalesOrder.so_number == "SO-2026-0001"
OPTIONAL MATCH (so)-[:HAS_SO_LINE]->(sol:SalesOrderLine)
OPTIONAL MATCH (so)-[:HAS_SHIPMENT]->(ship:Shipment)-[:HAS_SHIPMENT_LINE]->(sl:ShipmentLine)
OPTIONAL MATCH (so)-[:HAS_AR_INVOICE]->(inv:ARInvoice)
OPTIONAL MATCH (inv)<-[:APPLIES_TO]-(arr:ARReceipt)
RETURN
  -- Customer info
  c.Customer.customer_name AS customer_name,
  -- SO Info
  so.SalesOrder.so_number AS so_number,
  so.SalesOrder.order_date AS order_date,
  so.SalesOrder.total_amount AS so_amount,
  so.SalesOrder.status AS so_status,
  -- SO Line summary
  count(DISTINCT sol.SalesOrderLine.line_number) AS line_count,
  sum(sol.SalesOrderLine.quantity) AS total_ordered_qty,
  -- Shipment info
  collect(DISTINCT ship.Shipment.shipment_number) AS shipment_numbers,
  sum(sl.ShipmentLine.shipped_quantity) AS total_shipped_qty,
  -- AR Invoice info
  collect(DISTINCT inv.ARInvoice.invoice_number) AS invoice_numbers,
  inv.ARInvoice.total_amount AS invoice_amount,
  inv.ARInvoice.invoice_date AS invoice_date,
  inv.ARInvoice.status AS invoice_status,
  -- AR Receipt info
  collect(DISTINCT arr.ARReceipt.receipt_number) AS receipt_numbers,
  arr.ARReceipt.amount AS receipt_amount,
  arr.ARReceipt.receipt_date AS receipt_date;
```

---

### Query 4: On-Time Shipment Performance (准时发货率分析)

**Business Context**: Operations team monitors how often the company ships orders by the scheduled date.

```ngql
-- Analyze on-time shipment performance
-- Compare actual shipment_date vs scheduled_ship_date
MATCH (so:SalesOrder)-[:HAS_SO_LINE]->(sol:SalesOrderLine),
      (so)-[:HAS_SHIPMENT]->(ship:Shipment)
WHERE so.SalesOrder.status IN ["SHIPPED", "INVOICED", "CLOSED"]
  AND sol.SalesOrderLine.scheduled_ship_date IS NOT NULL
  AND ship.Shipment.shipment_date IS NOT NULL
  AND so.SalesOrder.order_date >= datetime_add(now(), INTERVAL -90 DAY)
WITH so.SalesOrder.so_number AS so_number,
     so.SalesOrder.order_date AS order_date,
     sol.SalesOrderLine.line_number AS line_number,
     sol.SalesOrderLine.scheduled_ship_date AS scheduled_date,
     ship.Shipment.shipment_date AS actual_ship_date,
     -- Calculate days variance (positive = late, negative = early)
     datetime_diff(ship.Shipment.shipment_date, sol.SalesOrderLine.scheduled_ship_date) / 86400 AS days_variance,
     CASE
       WHEN ship.Shipment.shipment_date <= sol.SalesOrderLine.scheduled_ship_date THEN "ON_TIME"
       ELSE "LATE"
     END AS shipment_status
WITH shipment_status,
     count(*) AS order_line_count,
     avg(days_variance) AS avg_days_variance,
     min(days_variance) AS max_early_days,
     max(days_variance) AS max_late_days
RETURN shipment_status,
       order_line_count,
       round(avg_days_variance, 1) AS avg_variance_days,
       max_early_days,
       max_late_days,
       (order_line_count * 100.0 / sum(order_line_count) OVER ()) AS pct_of_total
ORDER BY shipment_status;
```

---

### Query 5: AR Receipt Application Status (收款核销状态)

**Business Context**: AR accountant verifies that all receipts are properly applied to invoices and identifies any unallocated cash.

```ngql
-- Find AR Receipts that are CONFIRMED but not yet APPLIED
-- These represent unallocated cash that needs to be matched to invoices
MATCH (arr:ARReceipt)-[:RECEIVED_FROM]->(c:Customer)
WHERE arr.ARReceipt.status == "CONFIRMED"
  AND NOT (arr)-[:APPLIES_TO]->(:ARInvoice)
WITH arr.ARReceipt.receipt_number AS receipt_number,
     arr.ARReceipt.receipt_date AS receipt_date,
     arr.ARReceipt.amount AS receipt_amount,
     arr.ARReceipt.currency AS currency,
     arr.ARReceipt.payment_method AS payment_method,
     c.Customer.customer_name AS customer_name,
     datetime_diff(now(), arr.ARReceipt.receipt_date) / 86400 AS days_unapplied
RETURN receipt_number,
       receipt_date,
       customer_name,
       receipt_amount,
       currency,
       payment_method,
       days_unapplied,
       CASE
         WHEN days_unapplied > 30 THEN "URGENT"
         WHEN days_unapplied > 7 THEN "WARNING"
         ELSE "RECENT"
       END AS priority
ORDER BY days_unapplied DESC
LIMIT 50;
```

---

### Query 6: Partial Payment Analysis (部分收款分析)

**Business Context**: Collections team reviews invoices with partial payments to understand customer payment patterns.

```ngql
-- Find invoices that have been partially paid
-- Shows payment progress and outstanding balance
MATCH (inv:ARInvoice)<-[:HAS_AR_INVOICE]-(so:SalesOrder)-[:SOLD_TO]->(c:Customer)
WHERE inv.ARInvoice.status == "COMPLETE"
  AND (inv)<-[:APPLIES_TO]-(:ARReceipt)
WITH c.Customer.customer_name AS customer_name,
     inv.ARInvoice.invoice_number AS invoice_number,
     inv.ARInvoice.invoice_date AS invoice_date,
     inv.ARInvoice.total_amount AS invoice_amount,
     inv.ARInvoice.currency AS currency,
     sum((:ARReceipt)-[:APPLIES_TO]->(inv) | 1) AS payment_count,  -- Count payments
     inv.Invoice.total_amount - sum() AS outstanding_amount,  -- Would use actual in production
     inv.ARInvoice.due_date AS due_date
WHERE payment_count > 1  -- Multiple payments = partial payment pattern
RETURN customer_name,
       invoice_number,
       invoice_date,
       invoice_amount,
       currency,
       payment_count,
       outstanding_amount
ORDER BY payment_count DESC, invoice_date DESC
LIMIT 50;
```

---

### Query 7: Sales Order Backlog Report (订单积压报表)

**Business Context**: Sales operations team monitors orders that are booked but not yet shipped to identify delays.

```ngql
-- Find BOOKED orders that have not yet shipped
-- Priority by how close to requested delivery date
MATCH (so:SalesOrder)-[:SOLD_TO]->(c:Customer),
      (so)-[:HAS_SO_LINE]->(sol:SalesOrderLine)
WHERE so.SalesOrder.status == "BOOKED"
  AND NOT (so)-[:HAS_SHIPMENT]->(:Shipment)
  AND so.SalesOrder.requested_date IS NOT NULL
WITH so.SalesOrder.so_number AS so_number,
     so.SalesOrder.order_date AS order_date,
     so.SalesOrder.requested_date AS requested_date,
     so.SalesOrder.total_amount AS order_amount,
     c.Customer.customer_name AS customer_name,
     sum(sol.SalesOrderLine.quantity) AS total_ordered_qty,
     -- Days until requested delivery
     datetime_diff(so.SalesOrder.requested_date, now()) / 86400 AS days_to_deliver
RETURN so_number,
       customer_name,
       order_date,
       requested_date,
       order_amount,
       total_ordered_qty,
       days_to_deliver,
       CASE
         WHEN days_to_deliver < 0 THEN "OVERDUE"
         WHEN days_to_deliver < 7 THEN "URGENT"
         WHEN days_to_deliver < 14 THEN "SOON"
         ELSE "ON_TRACK"
       END AS delivery_priority
ORDER BY days_to_deliver ASC  -- Most urgent first
LIMIT 50;
```

---

## 6. Summary Table — 汇总表

| Entity | VID Format | Description |
|--------|------------|-------------|
| SalesOrder | `SO:{so_number}` | Customer sales order |
| SalesOrderLine | `SOL:{so_number}:{line}` | Line item of SO |
| Shipment | `SHIP:{shipment_number}` | Shipment confirmation |
| ShipmentLine | `SHIPL:{shipment_number}:{line}` | Line item of shipment |
| ARInvoice | `ARI:{invoice_number}` | Invoice to customer |
| ARReceipt | `ARR:{receipt_number}` | Payment received from customer |

| Relationship | Direction | Description |
|--------------|-----------|-------------|
| SOLD_TO | SO → Customer | Order placed by customer |
| HAS_SO_LINE | SO → SOL | SO contains lines |
| SELLS_ITEM | SOL → Item | Line sells item |
| HAS_SHIPMENT | SO → Shipment | SO shipped |
| HAS_SHIPMENT_LINE | Shipment → ShipmentLine | Shipment contains lines |
| SHIPPED_FROM | Shipment → Warehouse | Shipped from warehouse |
| HAS_AR_INVOICE | SO → ARInvoice | Invoice created |
| RECEIVED_FROM | ARReceipt → Customer | Payment from customer |
| APPLIES_TO | ARReceipt → ARInvoice | Receipt applied to invoice |

---

## 7. OTC vs PTP Comparison (OTC与PTP对比)

| Aspect | PTP (Procure-to-Pay) | OTC (Order-to-Cash) |
|--------|---------------------|---------------------|
| Starting Document | PurchaseRequisition | SalesOrder |
| Key Transaction | PurchaseOrder → Receipt → Invoice → Payment | SalesOrder → Shipment → ARInvoice → ARReceipt |
| Incoming/Outgoing | Money going OUT (Payment) | Money coming IN (Receipt) |
| Counterparty | Supplier | Customer |
| Three-Way Match | PO ↔ Receipt ↔ Invoice | SO ↔ Shipment ↔ ARInvoice |
| Master Data | Supplier | Customer |
| Invoice | Invoice (from supplier) | ARInvoice (to customer) |
| Payment | Payment (to supplier) | ARReceipt (from customer) |
