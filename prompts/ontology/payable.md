# Payable Domain Ontology — 应付域本体

> Version: v1.0
> Date: 2026-04-04
> Domain: Payable / Accounts Payable (AP) — 应付账款
> NebulaGraph Space: honeybadge

---

## 1. Entity Definitions — 实体定义

### 1.1 Invoice (应付发票)

**Business Meaning (业务含义)**:
A supplier's invoice requesting payment for goods delivered or services rendered. The Invoice is the trigger for the accounts payable process. In the PTP cycle, Invoice follows Receipt and precedes Payment. The Invoice must pass three-way match validation before payment is approved.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `invoice_number` | STRING NOT NULL | Supplier's invoice number (e.g., "INV-SUP-2026-00001") |
| `invoice_type` | STRING | STANDARD (标准发票) / CREDIT_MEMO (贷项通知单) / DEBIT_MEMO (借项通知单) / PREPAYMENT (预付款发票) |
| `invoice_date` | TIMESTAMP NOT NULL | Date on the invoice (issue date) |
| `due_date` | TIMESTAMP | Payment due date (calculated from invoice_date + payment_terms) |
| `status` | STRING | DRAFT / VALIDATED / APPROVED / PAID / CANCELLED / ON_HOLD |
| `total_amount` | DOUBLE NOT NULL | Invoice total including tax |
| `tax_amount` | DOUBLE DEFAULT 0 | Tax portion |
| `currency` | STRING DEFAULT "CNY" | Invoice currency |
| `exchange_rate` | DOUBLE DEFAULT 1.0 | Exchange rate for foreign currency |
| `payment_method` | STRING | CHECK / ELECTRONIC / WIRE / CASH |
| `description` | STRING | Invoice description/comments |
| `gl_date` | TIMESTAMP | General ledger posting date (accounting date) |

**Status Lifecycle**:
```
DRAFT → VALIDATED → APPROVED → PAID
                    ↓             ↓
              ON_HOLD      CANCELLED
```

- DRAFT: Created but not yet validated against PO/Receipt
- VALIDATED: Three-way match passed or accepted deviation
- APPROVED: Validated and ready for payment processing
- PAID: Payment has been made
- ON_HOLD: Pending resolution of discrepancy
- CANCELLED: Invoice cancelled (may need credit memo)

**VID Format**: `INV:{invoice_number}` (e.g., `INV:INV-SUP-2026-00001`)

---

### 1.2 InvoiceLine (发票行)

**Business Meaning (业务含义)**:
Line items on an Invoice, detailing the items or services billed. Each InvoiceLine corresponds to a POLine in a three-way match comparison.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `line_number` | INT64 NOT NULL | Line sequence number |
| `line_type` | STRING | ITEM (物料行) / TAX (税行) / FREIGHT (运费行) / MISC (其他费用行) |
| `quantity` | DOUBLE | Invoice quantity (should match PO/Receipt within tolerance) |
| `unit_price` | DOUBLE | Invoice unit price |
| `amount` | DOUBLE NOT NULL | Line amount = quantity × unit_price |
| `tax_code` | STRING | Tax classification code |
| `tax_rate` | DOUBLE | Tax rate percentage |
| `description` | STRING | Line description |

**Business Rule**: `Invoice.total_amount = SUM(InvoiceLine.amount) + Invoice.tax_amount`

**VID Format**: `INVL:{invoice_number}:{line_number}` (e.g., `INVL:INV-SUP-2026-00001:1`)

---

### 1.3 Payment (付款)

**Business Meaning (业务含义)**:
A disbursement of funds to a supplier to settle an Invoice. Payment releases the company's cash and completes the PTP cycle. Payments can be made by various methods (check, wire transfer, electronic payment).

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `payment_number` | STRING NOT NULL | Unique payment identifier (e.g., "PAY-2026-00001") |
| `payment_type` | STRING | CHECK / ELECTRONIC / WIRE / CASH |
| `payment_date` | TIMESTAMP NOT NULL | Date payment was made |
| `amount` | DOUBLE NOT NULL | Payment amount |
| `currency` | STRING DEFAULT "CNY" | Payment currency |
| `exchange_rate` | DOUBLE DEFAULT 1.0 | Exchange rate for foreign currency |
| `status` | STRING | CREATED / CONFIRMED / CLEARED / VOIDED / RECONCILED |
| `bank_account` | STRING | Company bank account used |
| `payment_method` | STRING | Payment channel/method |
| `check_number` | STRING | Check number if payment by check |
| `cleared_date` | TIMESTAMP | Date payment cleared the bank |
| `void_date` | TIMESTAMP | Date payment was voided (if applicable) |

**Status Lifecycle**:
```
CREATED → CONFIRMED → CLEARED → RECONCILED
              ↓            ↓
          VOIDED       (reversal)
```

- CREATED: Payment record created but not yet sent to bank
- CONFIRMED: Payment instruction sent to bank
- CLEARED: Bank confirmed payment was received by supplier
- VOIDED: Payment cancelled before clearing
- RECONCILED: Payment matched to bank statement

**VID Format**: `PAY:{payment_number}` (e.g., `PAY:PAY-2026-00001`)

---

### 1.4 PaymentBatch (付款批次)

**Business Meaning (业务含义)**:
A batch of Payments grouped together for processing, typically in a daily payment run. Batch processing improves efficiency in accounts payable operations.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `batch_number` | STRING NOT NULL | Unique batch identifier (e.g., "BATCH-2026-04-05-001") |
| `batch_date` | TIMESTAMP | Date the batch was created/processed |
| `total_amount` | DOUBLE | Sum of all payments in the batch |
| `payment_count` | INT64 | Number of payments in the batch |
| `status` | STRING | DRAFT / CONFIRMED / COMPLETED |

**VID Format**: `PB:{batch_number}` (e.g., `PB:BATCH-2026-04-05-001`)

---

## 2. Relationship Definitions — 关系定义

### 2.1 HAS_INVOICE (采购订单对应发票)

**Direction**: PurchaseOrder → Invoice
**Edge Properties**:
| Property | Type | Description |
|----------|------|-------------|
| `match_status` | STRING | MATCHED / UNMATCHED / PARTIAL — result of three-way match |
| `match_date` | TIMESTAMP | When the match was performed |

**Business Meaning (业务含义)**:
Links a PO to the Invoice received from the supplier. This is the central relationship for three-way match. The match_status indicates whether PO quantity/price matches Invoice quantity/price within tolerance.

---

### 2.2 HAS_INVOICE_LINE (发票包含行)

**Direction**: Invoice → InvoiceLine

**Business Meaning**: The line items that make up the invoice total.

---

### 2.3 INVOICED_BY (发票开具方)

**Direction**: Invoice → Supplier

**Business Meaning (业务含义)**:
Links Invoice to the Supplier who issued it. For valid three-way match, this must equal the PLACED_WITH supplier of the corresponding PO.

**Business Rule**: `Invoice.INVOICED_BY.supplier == Invoice.HAS_INVOICE.PO.PLACED_WITH.supplier`

---

### 2.4 PAYS_INVOICE (付款对应发票)

**Direction**: Payment → Invoice
**Edge Properties**: `paid_amount DOUBLE` — portion of invoice paid by this payment

**Business Meaning (业务含义)**:
Links a Payment to the Invoice(s) it settles. One Invoice may be paid by multiple Payments (partial payments), or one Payment may pay multiple Invoices (combined payment).

**Business Rule**: `SUM(Payment.PAYS_INVOICE.paid_amount for all payments to an Invoice) <= Invoice.total_amount`

---

### 2.5 PAID_TO (付款支付给供应商)

**Direction**: Payment → Supplier

**Business Meaning (业务含义)**:
Links Payment to the Supplier who receives it. Must equal the INVOICED_BY supplier.

---

### 2.6 CONTAINS_PAYMENT (付款批次包含付款)

**Direction**: PaymentBatch → Payment

**Business Meaning (业务含义)**:
Groups individual Payments into a batch for processing.

---

## 3. Three-Way Match Rules — 三单匹配规则

### 3.1 Overview

Three-Way Match is the critical controls process in PTP:
```
PO (Purchase Order) ↔ Receipt (Goods Received) ↔ Invoice (Supplier Invoice)
```

The purpose is to ensure the company only pays for:
1. What was ORDERED (PO)
2. What was RECEIVED (Receipt)
3. What was INVOICED (Invoice)

### 3.2 Match Rules with Exact Thresholds

| Match Dimension | Rule | Tolerance | Alert Level |
|----------------|------|-----------|-------------|
| **Quantity Match** | \|Receipt.quantity - PO.quantity\| / PO.quantity | ≤ 5% = MATCHED | WARNING: 5-10%, ALERT: >10% |
| **Amount Match** | \|Invoice.amount - PO.amount\| / PO.amount | ≤ 10% = MATCHED | WARNING: 10-20%, ALERT: >20% |
| **Unit Price Match** | Invoice.unit_price == PO.unit_price | Must be EXACT (0 tolerance) | CRITICAL if different |
| **Supplier Match** | Invoice.supplier == PO.supplier == Receipt.supplier | Must be EXACT match | CRITICAL if mismatch |
| **Date Sequence** | Invoice.date >= Receipt.date >= PO.date | Must follow sequence | WARNING if reversed |

### 3.3 Match Status Definitions

| Status | Meaning |
|--------|---------|
| MATCHED | All dimensions within tolerance |
| PARTIAL | Some dimensions matched, others have minor deviations (within warning range) |
| UNMATCHED | Significant deviations requiring investigation |

### 3.4 Three-Way Match Query Pattern

```ngql
-- Three-way match validation pattern
-- Compares PO lines, Receipt lines, and Invoice lines
MATCH (po:PurchaseOrder)-[:HAS_INVOICE]->(inv:Invoice),
      (po)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine),
      (po)-[:HAS_RECEIPT]->(r:Receipt)-[:HAS_RECEIPT_LINE]->(rl:ReceiptLine)
WHERE po.PurchaseOrder.po_number == "PO-XXX"
  AND pol.PurchaseOrderLine.line_number == rl.ReceiptLine.line_number
WITH po, pol, rl, inv,
     -- Calculate quantity deviation
     abs(rl.ReceiptLine.received_quantity - pol.PurchaseOrderLine.quantity)
       / pol.PurchaseOrderLine.quantity AS qty_deviation_pct,
     -- Calculate amount deviation
     abs(inv.Invoice.total_amount - po.PurchaseOrder.total_amount)
       / po.PurchaseOrder.total_amount AS amt_deviation_pct,
     -- Check supplier consistency
     (inv)-[:INVOICED_BY]->(s:InvoiceSupplier)
     -- match logic...
```

---

## 4. Duplicate Invoice Detection — 重复发票检测

### 4.1 Business Context

Duplicate invoices represent a significant fraud risk where a supplier submits the same invoice multiple times, or an internal actor creates duplicate payments. Detection is based on:
1. Same supplier
2. Same invoice number OR same amount
3. Invoice dates within a narrow window (±3 days)

### 4.2 Detection Rules

A pair of invoices is flagged as potential duplicates when ALL of the following are true:
1. Same INVOICED_BY supplier
2. Same total_amount
3. Invoice dates differ by ≤ 3 days
4. Invoice numbers are different (if same number, it's definitely a duplicate)

### 4.3 Query Pattern

```ngql
-- Find potential duplicate invoices
-- Two invoices from same supplier with same amount and similar dates
MATCH (inv1:Invoice)-[:INVOICED_BY]->(s:Supplier)<-[:INVOICED_BY]-(inv2:Invoice)
WHERE id(inv1) < id(inv2)  -- Avoid self-join and duplicates
  AND inv1.Invoice.total_amount == inv2.Invoice.total_amount
  AND inv1.Invoice.currency == inv2.Invoice.currency
  AND abs(datetime_diff(inv1.Invoice.invoice_date, inv2.Invoice.invoice_date)) <= 3 * 86400
  AND inv1.Invoice.status IN ["VALIDATED", "APPROVED", "PAID"]
  AND inv2.Invoice.status IN ["VALIDATED", "APPROVED", "PAID"]
RETURN s.Supplier.supplier_name AS supplier,
       inv1.Invoice.invoice_number AS invoice_1,
       inv2.Invoice.invoice_number AS invoice_2,
       inv1.Invoice.invoice_date AS date_1,
       inv2.Invoice.invoice_date AS date_2,
       inv1.Invoice.total_amount AS amount,
       inv1.Invoice.status AS status_1,
       inv2.Invoice.status AS status_2
ORDER BY s.Supplier.supplier_name, inv1.Invoice.invoice_date
LIMIT 100;
```

---

## 5. Payment Business Rules — 付款业务规则

### Rule 1: Payment Amount Integrity (付款金额完整性)

**Rule Definition**: `Payment.amount <= Invoice.total_amount - SUM(previous payments to this invoice)`

**Business Meaning**: A payment should never exceed the outstanding amount on an invoice. Overpayment may indicate:
1. Fraud (payment to wrong supplier)
2. Data entry error
3. Misapplied payment

**Risk Level**: CRITICAL if overpayment detected

---

### Rule 2: Early Payment Detection (提前付款检测)

**Rule Definition**: Payment.payment_date should not be more than 30 days before Invoice.due_date without justification.

**Business Meaning**: Paying too early may indicate:
1. Collusion between buyer and supplier
2. Unnecessary loss of cash float
3. Error in payment processing

**Threshold**: Alert if payment_date < due_date - 30 days

---

### Rule 3: Overdue Invoice Detection (超期未付发票)

**Rule Definition**: Invoice.due_date < current_date AND Invoice.status != "PAID" AND no active Payment exists.

**Business Meaning**: Overdue invoices indicate:
1. Cash flow issues
2. Disputed invoices
3. Process delays in AP

**Risk Level**: HIGH if significantly overdue

---

### Rule 4: Payment Batch Completeness (付款批次完整性)

**Rule Definition**: All payments in a PaymentBatch should have the same batch_date and status transitions should be sequential.

---

## 6. Example nGQL Queries — nGQL 查询示例

### Query 1: Three-Way Match Deviation Detection (三单匹配偏差检测)

**Business Context**: AP manager reviews invoices with significant deviations from PO amounts to identify exceptions requiring approval.

```ngql
-- Find invoices where amount deviates from PO amount by more than 10%
-- These invoices require special approval
MATCH (po:PurchaseOrder)-[e:HAS_INVOICE]->(inv:Invoice),
      (po)-[:PLACED_WITH]->(s:Supplier)
WHERE e.HAS_INVOICE.match_status IN ["UNMATCHED", "PARTIAL"]
  AND inv.Invoice.status IN ["VALIDATED", "APPROVED"]
  -- Calculate deviation percentage
  AND abs(inv.Invoice.total_amount - po.PurchaseOrder.total_amount)
        / po.PurchaseOrder.total_amount > 0.1
RETURN po.PurchaseOrder.po_number AS po_number,
       po.PurchaseOrder.total_amount AS po_amount,
       inv.Invoice.invoice_number AS invoice_number,
       inv.Invoice.total_amount AS invoice_amount,
       inv.Invoice.invoice_date AS invoice_date,
       (inv.Invoice.total_amount - po.PurchaseOrder.total_amount) AS amount_difference,
       abs(inv.Invoice.total_amount - po.PurchaseOrder.total_amount)
         / po.PurchaseOrder.total_amount * 100 AS deviation_pct,
       s.Supplier.supplier_name AS supplier_name,
       e.HAS_INVOICE.match_status AS match_status
ORDER BY deviation_pct DESC
LIMIT 50;
```

---

### Query 2: Overdue Invoice Report (超期未付发票报表)

**Business Context**: Treasury team needs visibility into overdue invoices for cash flow management.

```ngql
-- Find all approved invoices past their due date without full payment
-- Calculate days overdue and outstanding amount
MATCH (inv:Invoice)-[:INVOICED_BY]->(s:Supplier)
WHERE inv.Invoice.status == "APPROVED"
  AND inv.Invoice.due_date < now()
  -- Calculate total paid amount via PAYS_INVOICE edges
  OPTIONAL MATCH (pay:Payment)-[:PAYS_INVOICE]->(inv)
WITH inv.Invoice.invoice_number AS invoice_number,
     inv.Invoice.invoice_date AS invoice_date,
     inv.Invoice.due_date AS due_date,
     inv.Invoice.total_amount AS invoice_amount,
     inv.Invoice.currency AS currency,
     s.Supplier.supplier_name AS supplier_name,
     -- Calculate days overdue
     datetime_diff(now(), inv.Invoice.due_date) / 86400 AS days_overdue,
     -- Calculate outstanding amount
     inv.Invoice.total_amount - coalesce(sum(pay.Payment.amount), 0) AS outstanding_amount
WHERE outstanding_amount > 0
RETURN supplier_name,
       invoice_number,
       invoice_date,
       due_date,
       invoice_amount,
       outstanding_amount,
       days_overdue,
       CASE
         WHEN days_overdue > 90 THEN "CRITICAL"
         WHEN days_overdue > 60 THEN "HIGH"
         WHEN days_overdue > 30 THEN "MEDIUM"
         ELSE "LOW"
       END AS risk_level
ORDER BY days_overdue DESC
LIMIT 100;
```

---

### Query 3: Duplicate Invoice Detection (重复发票检测)

**Business Context**: Internal audit runs this query daily to catch potential duplicate payments before they occur.

```ngql
-- Detect potential duplicate invoices from same supplier
-- Based on: same amount, similar date, different invoice number
MATCH (inv1:Invoice)-[:INVOICED_BY]->(s:Supplier)<-[:INVOICED_BY]-(inv2:Invoice)
WHERE id(inv1) < id(inv2)  -- Avoid comparing same pair twice
  AND inv1.Invoice.total_amount == inv2.Invoice.total_amount
  AND inv1.Invoice.currency == inv2.Invoice.currency
  AND inv1.Invoice.invoice_number != inv2.Invoice.invoice_number  -- Different invoice numbers
  AND abs(datetime_diff(inv1.Invoice.invoice_date, inv2.Invoice.invoice_date)) <= 3 * 86400
  AND inv1.Invoice.status NOT IN ["CANCELLED", "DRAFT"]
  AND inv2.Invoice.status NOT IN ["CANCELLED", "DRAFT"]
WITH s.Supplier.supplier_name AS supplier,
     inv1.Invoice.invoice_number AS invoice_1,
     inv2.Invoice.invoice_number AS invoice_2,
     inv1.Invoice.invoice_date AS date_1,
     inv2.Invoice.invoice_date AS date_2,
     inv1.Invoice.total_amount AS amount,
     inv1.Invoice.currency AS currency,
     abs(datetime_diff(inv1.Invoice.invoice_date, inv2.Invoice.invoice_date)) / 86400 AS days_apart
RETURN supplier,
       invoice_1,
       invoice_2,
       date_1,
       date_2,
       amount,
       currency,
       days_apart,
       CASE
         WHEN days_apart == 0 THEN "SAME_DAY"
         ELSE "WITHIN_3_DAYS"
       END AS duplicate_type
ORDER BY supplier, date_1
LIMIT 100;
```

---

### Query 4: Early Payment Anomaly (提前付款异常)

**Business Context**: CFO reviews payments made significantly before due date to check for unusual cash outflows or potential fraud.

```ngql
-- Find payments made more than 30 days before invoice due date
-- These may indicate prepayment fraud or cash management issues
MATCH (pay:Payment)-[:PAYS_INVOICE]->(inv:Invoice),
      (pay)-[:PAID_TO]->(s:Supplier)
WHERE pay.Payment.status IN ["CONFIRMED", "CLEARED"]
  AND pay.Payment.payment_date < datetime_add(inv.Invoice.due_date, INTERVAL -30 DAY)
WITH pay.Payment.payment_number AS payment_number,
     pay.Payment.payment_date AS payment_date,
     inv.Invoice.invoice_number AS invoice_number,
     inv.Invoice.invoice_date AS invoice_date,
     inv.Invoice.due_date AS due_date,
     pay.Payment.amount AS payment_amount,
     s.Supplier.supplier_name AS supplier_name,
     -- Calculate how many days early
     datetime_diff(inv.Invoice.due_date, pay.Payment.payment_date) / 86400 AS days_early
RETURN payment_number,
       payment_date,
       supplier_name,
       invoice_number,
       invoice_date,
       due_date,
       payment_amount,
       days_early
ORDER BY days_early DESC
LIMIT 50;
```

---

### Query 5: Invoice Aging Analysis (发票账龄分析)

**Business Context**: AP manager analyzes invoice aging buckets to prioritize payment and manage cash flow.

```ngql
-- Categorize approved (unpaid) invoices by aging bucket
-- Shows distribution of payables across time buckets
MATCH (inv:Invoice)-[:INVOICED_BY]->(s:Supplier)
WHERE inv.Invoice.status IN ["VALIDATED", "APPROVED"]
WITH inv.Invoice.invoice_number AS invoice_number,
     inv.Invoice.invoice_date AS invoice_date,
     inv.Invoice.due_date AS due_date,
     inv.Invoice.total_amount AS invoice_amount,
     inv.Invoice.currency AS currency,
     s.Supplier.supplier_name AS supplier_name,
     -- Calculate days until due (negative = overdue)
     datetime_diff(inv.Invoice.due_date, now()) / 86400 AS days_to_due
WITH invoice_number,
     invoice_date,
     due_date,
     invoice_amount,
     currency,
     supplier_name,
     days_to_due,
     CASE
       WHEN days_to_due < -90 THEN "OVERDUE_90+"
       WHEN days_to_due < -60 THEN "OVERDUE_60-90"
       WHEN days_to_due < -30 THEN "OVERDUE_30-60"
       WHEN days_to_due < 0 THEN "OVERDUE_0-30"
       WHEN days_to_due < 30 THEN "DUE_0-30"
       WHEN days_to_due < 60 THEN "DUE_30-60"
       ELSE "DUE_60+"
     END AS aging_bucket
RETURN aging_bucket,
       count(*) AS invoice_count,
       sum(invoice_amount) AS total_amount,
       avg(days_to_due) AS avg_days_to_due
ORDER BY
  CASE aging_bucket
    WHEN "OVERDUE_90+" THEN 1
    WHEN "OVERDUE_60-90" THEN 2
    WHEN "OVERDUE_30-60" THEN 3
    WHEN "OVERDUE_0-30" THEN 4
    WHEN "DUE_0-30" THEN 5
    WHEN "DUE_30-60" THEN 6
    WHEN "DUE_60+" THEN 7
  END;
```

---

### Query 6: Payment Batch Summary (付款批次汇总)

**Business Context**: AP supervisor reviews daily payment batch processing for audit trail.

```ngql
-- Summarize payment batch by batch number
-- Shows total amounts and payment counts per batch
MATCH (pb:PaymentBatch)-[:CONTAINS_PAYMENT]->(pay:Payment),
      (pay)-[:PAID_TO]->(s:Supplier)
WHERE pb.PaymentBatch.batch_date >= datetime_add(now(), INTERVAL -7 DAY)
WITH pb.PaymentBatch.batch_number AS batch_number,
     pb.PaymentBatch.batch_date AS batch_date,
     pb.PaymentBatch.status AS batch_status,
     count(DISTINCT pay.Payment.payment_number) AS payment_count,
     sum(pay.Payment.amount) AS total_batch_amount,
     pay.Payment.currency AS currency,
     collect(DISTINCT s.Supplier.supplier_name)[0..5] AS sample_suppliers  -- First 5 suppliers
RETURN batch_number,
       batch_date,
       batch_status,
       payment_count,
       total_batch_amount,
       currency,
       sample_suppliers
ORDER BY batch_date DESC
LIMIT 20;
```

---

### Query 7: Supplier Payment Terms Analysis (供应商付款条款分析)

**Business Context**: Finance team analyzes actual payment timing vs agreed payment terms to identify optimization opportunities.

```ngql
-- Compare actual payment timing to agreed payment terms
-- Identify suppliers where payments consistently deviate from terms
MATCH (inv:Invoice)-[:INVOICED_BY]->(s:Supplier),
      (inv)<-[:PAYS_INVOICE]-(pay:Payment)
WHERE inv.Invoice.status == "PAID"
  AND inv.Invoice.payment_terms IS NOT NULL
  AND pay.Payment.payment_date IS NOT NULL
  AND inv.Invoice.due_date IS NOT NULL
WITH s.Supplier.supplier_name AS supplier_name,
     inv.Invoice.payment_terms AS agreed_terms,
     count(*) AS payment_count,
     -- Calculate actual days from invoice to payment
     avg(datetime_diff(pay.Payment.payment_date, inv.Invoice.invoice_date) / 86400) AS avg_days_to_pay,
     -- Calculate deviation from terms
     avg((pay.Payment.payment_date - inv.Invoice.due_date) / 86400) AS avg_days_deviation_from_due
WITH supplier_name,
     agreed_terms,
     payment_count,
     avg_days_to_pay,
     avg_days_deviation_from_due,
     CASE
       WHEN avg_days_deviation_from_due > 30 THEN "CONSISTENTLY_LATE"
       WHEN avg_days_deviation_from_due < -30 THEN "CONSISTENTLY_EARLY"
       ELSE "ON_TERMS"
     END AS payment_behavior
RETURN supplier_name,
       agreed_terms,
       payment_count,
       round(avg_days_to_pay, 1) AS avg_days_to_pay,
       round(avg_days_deviation_from_due, 1) AS avg_days_deviation,
       payment_behavior
ORDER BY avg_days_deviation_from_due DESC  -- Most late first
LIMIT 50;
```

---

## 7. Summary Table — 汇总表

| Entity | VID Format | Description |
|--------|------------|-------------|
| Invoice | `INV:{invoice_number}` | Supplier invoice requesting payment |
| InvoiceLine | `INVL:{invoice_number}:{line}` | Line item of invoice |
| Payment | `PAY:{payment_number}` | Disbursement to supplier |
| PaymentBatch | `PB:{batch_number}` | Grouped payment processing |

| Relationship | Direction | Description |
|--------------|-----------|-------------|
| HAS_INVOICE | PO → Invoice | PO matched to invoice (three-way match) |
| HAS_INVOICE_LINE | Invoice → InvoiceLine | Invoice contains lines |
| INVOICED_BY | Invoice → Supplier | Invoice from supplier |
| PAYS_INVOICE | Payment → Invoice | Payment settles invoice |
| PAID_TO | Payment → Supplier | Payment to supplier |
| CONTAINS_PAYMENT | PaymentBatch → Payment | Batch contains payments |

---

## 8. Three-Way Match Summary

```
PO.quantity × PO.unit_price     ← Expected cost
        ↓
Receipt.received_quantity     ← What was received
        ↓
Invoice.quantity × Invoice.unit_price ← What was billed

Match Rules:
- Quantity: |Receipt - PO| / PO ≤ 5% → MATCHED
- Amount: |Invoice - PO| / PO ≤ 10% → MATCHED
- Price: Invoice.unit_price == PO.unit_price → EXACT match required
- Supplier: All three must match → EXACT match required
```
