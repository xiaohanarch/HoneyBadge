# Business Constraints Ontology — 业务约束本体

> Version: v1.0
> Date: 2026-04-04
> Domain: Business Constraints and Validation Rules
> NebulaGraph Space: honeybadge

---

## 1. Three-Way Match Rules — 三单匹配规则

### 1.1 Overview

Three-Way Match is the cornerstone control in Procure-to-Pay (PTP). It ensures the company pays only for goods/services that were properly ordered, received, and invoiced.

```
Document Triad:
  PO (Purchase Order) ←→ Receipt (Goods Received) ←→ Invoice (Supplier Invoice)

Purpose:
  1. Prevent overpayment (paying for more than ordered/received)
  2. Prevent fraudulent invoices (invoice for goods never delivered)
  3. Ensure pricing accuracy (invoice matches negotiated PO price)
  4. Verify supplier identity (invoice from correct supplier)
```

### 1.2 Three-Way Match Validation Rules

#### Rule TWM-1: Quantity Match (数量匹配)

| Condition | Threshold | Alert Level |
|-----------|-----------|-------------|
| \|Receipt.quantity - PO.quantity\| / PO.quantity | ≤ 5% | MATCHED (Green) |
| Deviation > 5% and ≤ 10% | 5-10% | WARNING (Yellow) |
| Deviation > 10% | >10% | ALERT (Red) |

**Business Rationale**: Some quantity variance is normal due to:
- Rounding in supplier's packing/shipping
- Subtle differences in UOM calculations
- Minor quality issues leading to partial rejection

A 5% tolerance accommodates these normal variances. Deviations above 5% warrant investigation.

**nGQL Detection Pattern**:
```ngql
-- Quantity deviation check
MATCH (po:PurchaseOrder)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine),
      (po)-[:HAS_RECEIPT]->(r:Receipt)-[:HAS_RECEIPT_LINE]->(rl:ReceiptLine)
WHERE pol.PurchaseOrderLine.line_number == rl.ReceiptLine.line_number
WITH po.PurchaseOrder.po_number AS po,
     pol.PurchaseOrderLine.quantity AS po_qty,
     rl.ReceiptLine.received_quantity AS rcv_qty,
     abs(rl.ReceiptLine.received_quantity - pol.PurchaseOrderLine.quantity)
       / pol.PurchaseOrderLine.quantity AS deviation_pct
WHERE deviation_pct > 0.05
RETURN po, po_qty, rcv_qty, deviation_pct,
       CASE
         WHEN deviation_pct > 0.10 THEN "ALERT"
         ELSE "WARNING"
       END AS alert_level;
```

---

#### Rule TWM-2: Amount Match (金额匹配)

| Condition | Threshold | Alert Level |
|-----------|-----------|-------------|
| \|Invoice.amount - PO.amount\| / PO.amount | ≤ 10% | MATCHED (Green) |
| Deviation > 10% and ≤ 20% | 10-20% | WARNING (Yellow) |
| Deviation > 20% | >20% | ALERT (Red) |

**Business Rationale**: Amount deviations may indicate:
- Invoice pricing errors (wrong price on invoice)
- Unapproved PO changes (line additions after PO creation)
- Currency exchange rate differences (for foreign currency POs)
- Tax calculation differences

**nGQL Detection Pattern**:
```ngql
-- Amount deviation check
MATCH (po:PurchaseOrder)-[:HAS_INVOICE]->(inv:Invoice)
WHERE inv.Invoice.status IN ["VALIDATED", "APPROVED"]
WITH po.PurchaseOrder.po_number AS po,
     po.PurchaseOrder.total_amount AS po_amount,
     inv.Invoice.total_amount AS inv_amount,
     abs(inv.Invoice.total_amount - po.PurchaseOrder.total_amount)
       / po.PurchaseOrder.total_amount AS deviation_pct
WHERE deviation_pct > 0.10
RETURN po, po_amount, inv_amount, deviation_pct,
       CASE
         WHEN deviation_pct > 0.20 THEN "ALERT"
         ELSE "WARNING"
       END AS alert_level;
```

---

#### Rule TWM-3: Unit Price Match (单价匹配)

| Condition | Threshold | Alert Level |
|-----------|-----------|-------------|
| Invoice.unit_price == PO.unit_price | EXACT MATCH | MATCHED |
| Any difference | Any deviation | ALERT (CRITICAL) |

**Business Rationale**: Unit price must match exactly because:
- Any price difference materially affects cost
- Price is a key negotiated term in the PO
- Price variance could indicate invoice fraud

**IMPORTANT**: Unlike quantity and amount which allow percentage tolerances, unit price must be an exact match (0 tolerance). This is because even a small unit price difference multiplied by large quantities creates significant overpayments.

**nGQL Detection Pattern**:
```ngql
-- Unit price exact match check
MATCH (po:PurchaseOrder)-[:HAS_INVOICE]->(inv:Invoice),
      (po)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine)
WHERE inv.Invoice.invoice_type == "STANDARD"
WITH po.PurchaseOrder.po_number AS po,
     pol.PurchaseOrderLine.line_number AS line,
     pol.PurchaseOrderLine.unit_price AS po_price,
     inv.Invoice.unit_price AS inv_price,
     (inv.Invoice.unit_price - pol.PurchaseOrderLine.unit_price) AS price_diff
WHERE price_diff != 0
RETURN po, line, po_price, inv_price, price_diff,
       "CRITICAL" AS alert_level;
```

---

#### Rule TWM-4: Supplier Consistency (供应商一致性)

| Condition | Threshold | Alert Level |
|-----------|-----------|-------------|
| PO.supplier == Invoice.supplier == Receipt.supplier | EXACT MATCH | REQUIRED |
| Any mismatch | Mismatch | CRITICAL |

**Business Rationale**: All three documents must be from/to the same supplier because:
- Diversion fraud (invoice from different, potentially fake, supplier)
- Purchase from unapproved supplier (bypassing procurement controls)
- Potential money laundering through fake suppliers

**nGQL Detection Pattern**:
```ngql
-- Supplier consistency check
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s_po:Supplier),
      (po)-[:HAS_INVOICE]->(inv:Invoice)-[:INVOICED_BY]->(s_inv:Supplier)
WHERE s_po.Supplier.supplier_number != s_inv.Supplier.supplier_number
RETURN po.PurchaseOrder.po_number AS po,
       s_po.Supplier.supplier_name AS po_supplier,
       inv.Invoice.invoice_number AS invoice,
       s_inv.Supplier.supplier_name AS invoice_supplier,
       "CRITICAL" AS alert_level,
       "SUPPLIER_MISMATCH" AS mismatch_type;
```

---

### 1.3 Three-Way Match Status Summary

| Alert Level | Trigger Condition | Action Required |
|-------------|-------------------|-----------------|
| GREEN (Matched) | All dimensions within tolerance | Auto-approve for payment |
| YELLOW (Warning) | Minor deviations (5-10% qty, 10-20% amount) | Manager review required |
| RED (Alert) | Significant deviations (>10% qty, >20% amount) | Senior approval + investigation |
| CRITICAL | Unit price mismatch OR supplier mismatch | Block payment, fraud investigation |

---

## 2. Temporal Sequence Constraints — 时序约束

### 2.1 PTP Temporal Sequence (按单付款流程时序)

**Mandatory Order**:
```
PR.request_date ≤ PO.order_date ≤ Receipt.receipt_date ≤ Invoice.invoice_date ≤ Payment.payment_date
|__________________|   |_________________|   |_________________|   |___________________|
      (earliest)           ↓                    ↓                      ↓
                      PO must be           Goods must be          Invoice must be
                      after PR              after PO              after Receipt
```

#### PTP Date Consistency Rules

| Rule ID | Constraint | Violation Detection |
|---------|------------|---------------------|
| PTC-1 | Receipt.receipt_date >= PO.order_date | Receipt placed before PO created |
| PTC-2 | Invoice.invoice_date >= Receipt.receipt_date | Invoice before goods received |
| PTC-3 | Payment.payment_date >= Invoice.invoice_date | Payment before invoice |
| PTC-4 | PR.request_date <= PO.order_date | PO created before request existed |

#### Violation Types and Business Implications

| Violation | Possible Cause | Risk Level |
|-----------|----------------|------------|
| Receipt.date < PO.date | Retroactive receipt, fictional transaction | HIGH |
| Invoice.date < Receipt.date | Pre-billing, goods not received | HIGH |
| Payment.date < Invoice.date | Advance payment, non-delivery risk | MEDIUM |
| PO.date < PR.date | Backdated PO, bypassing approval | CRITICAL |

**nGQL Detection Pattern**:
```ngql
-- PTP temporal sequence violation detection
MATCH (pr:PurchaseRequisition)-[:CONVERTS_TO_PO]->(po:PurchaseOrder)
WHERE po.PurchaseOrder.order_date < pr.PurchaseRequisition.request_date
WITH "PTC-4" AS rule_id,
     pr.PurchaseRequisition.pr_number AS pr,
     pr.PurchaseRequisition.request_date AS pr_date,
     po.PurchaseOrder.po_number AS po,
     po.PurchaseOrder.order_date AS po_date,
     "PO before PR" AS violation_type,
     "CRITICAL" AS risk_level
// Continue with other temporal checks...
RETURN rule_id, pr, pr_date, po, po_date, violation_type, risk_level

UNION

MATCH (po:PurchaseOrder)-[:HAS_RECEIPT]->(r:Receipt)
WHERE r.Receipt.receipt_date < po.PurchaseOrder.order_date
WITH "PTC-1" AS rule_id,
     po.PurchaseOrder.po_number AS po,
     po.PurchaseOrder.order_date AS po_date,
     r.Receipt.receipt_number AS receipt,
     r.Receipt.receipt_date AS receipt_date,
     "Receipt before PO" AS violation_type,
     "HIGH" AS risk_level
RETURN rule_id, po, po_date, receipt, receipt_date, violation_type, risk_level;
```

---

### 2.2 OTC Temporal Sequence (订单到收款流程时序)

**Mandatory Order**:
```
SO.order_date ≤ Shipment.shipment_date ≤ ARInvoice.invoice_date ≤ ARReceipt.receipt_date
|________________|   |_____________________|   |____________________|   |____________________|
     (earliest)             ↓                        ↓                        ↓
                     Shipment must            Invoice must be           Receipt must be
                     be after SO             after Shipment             after Invoice
```

#### OTC Date Consistency Rules

| Rule ID | Constraint | Violation Detection |
|---------|------------|---------------------|
| OTC-1 | Shipment.shipment_date >= SO.order_date | Shipment before order |
| OTC-2 | ARInvoice.invoice_date >= Shipment.shipment_date | Invoice before shipment |
| OTC-3 | ARReceipt.receipt_date >= ARInvoice.invoice_date | Receipt before invoice |

---

## 3. Amount Integrity Rules — 金额完整性规则

### 3.1 PO Amount Integrity

**Rule AM-1: PO Line Amount Calculation**
```
POLine.amount = POLine.quantity × POLine.unit_price
```
**Tolerance**: Exact (0 tolerance for calculation errors)

**Verification Query**:
```ngql
-- Find POLines where amount != quantity * unit_price
MATCH (po:PurchaseOrder)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine)
WHERE pol.PurchaseOrderLine.amount !=
      (pol.PurchaseOrderLine.quantity * pol.PurchaseOrderLine.unit_price)
RETURN po.PurchaseOrder.po_number AS po,
       pol.PurchaseOrderLine.line_number AS line,
       pol.PurchaseOrderLine.quantity AS qty,
       pol.PurchaseOrderLine.unit_price AS unit_price,
       pol.PurchaseOrderLine.amount AS line_amount,
       (pol.PurchaseOrderLine.quantity * pol.PurchaseOrderLine.unit_price) AS expected_amount,
       (pol.PurchaseOrderLine.amount -
        pol.PurchaseOrderLine.quantity * pol.PurchaseOrderLine.unit_price) AS amount_diff;
```

---

**Rule AM-2: PO Header vs Line Amount**
```
PO.total_amount = SUM(POLine.amount) + freight + taxes
```
**Tolerance**: 0.01 (for rounding in tax calculations)

**Verification Query**:
```ngql
-- Find POs where header amount != sum of lines
MATCH (po:PurchaseOrder)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine)
WITH po.PurchaseOrder.po_number AS po_number,
     po.PurchaseOrder.total_amount AS header_amount,
     sum(pol.PurchaseOrderLine.amount) AS lines_total
WHERE abs(header_amount - lines_total) > 0.01
RETURN po_number,
       header_amount,
       lines_total,
       (header_amount - lines_total) AS discrepancy;
```

---

### 3.2 Invoice Amount Integrity

**Rule AM-3: Invoice Line Amount**
```
InvoiceLine.amount = InvoiceLine.quantity × InvoiceLine.unit_price
```
**Tolerance**: Exact

---

**Rule AM-4: Invoice Header vs Line Amount**
```
Invoice.total_amount = SUM(InvoiceLine.amount) + Invoice.tax_amount
```
**Tolerance**: 0.01

---

### 3.3 Payment Amount Rules

**Rule AM-5: Payment vs Invoice Amount**
```
SUM(Payments to an Invoice) <= Invoice.total_amount
```
**Purpose**: Prevent overpayment

**Violation**: If `SUM(Payment.amount) > Invoice.total_amount`, this is a CRITICAL overpayment

---

**Rule AM-6: Partial Payment Completeness**
```
When Invoice is marked CLOSED/PAID:
  SUM(Payment amounts for this Invoice) == Invoice.total_amount
```
**Tolerance**: 0.01 (for currency rounding)

---

## 4. Cyclical Transaction Detection Patterns — 循环交易检测模式

### 4.1 Overview

Cyclical transactions are a sophisticated fraud pattern where:
1. Company A buys from Company B
2. Company B buys from Company C
3. Company C buys from Company A

This creates a circular flow of money that can be used to:
- Generate false revenue/income for all parties
- Facilitate money laundering
- Create artificial tax benefits
- Generate kickbacks through inflated transactions

### 4.2 Circular Purchase Pattern Detection

**Pattern**: Find suppliers where:
- Supplier A is a customer of Supplier B
- Supplier B is a customer of Supplier C
- Supplier C is a customer of Supplier A

**Simplified Graph Pattern** (for Phase 1):
```ngql
-- Detect circular transactions through buyer links
-- This is a simplified version that looks for common buyers
MATCH (s1:Supplier)<-[:PLACED_WITH]-(po1:PurchaseOrder)-[:ORDERED_BY]->(e:Employee),
      (s2:Supplier)<-[:PLACED_WITH]-(po2:PurchaseOrder)-[:ORDERED_BY]->(e)
WHERE s1 != s2
WITH s1, s2, count(DISTINCT e) AS shared_buyers
WHERE shared_buyers >= 2  -- Multiple shared buyers may indicate coordination
RETURN s1.Supplier.supplier_name AS supplier_a,
       s2.Supplier.supplier_name AS supplier_b,
       shared_buyers
ORDER BY shared_buyers DESC
LIMIT 20;
```

**More Complex Circular Pattern** (for Phase 2):
```ngql
-- Find circular supplier relationships through customer links
-- Supplier A sells TO Supplier B? (would require CUSTOMER relationship)
MATCH (s1:Supplier)<-[:PLACED_WITH]-(po1:PurchaseOrder),
      (po1)-[:ORDERED_BY]->(emp1:Employee),
      (emp1)-[:WORKS_AT]->(org:Organization),
      (org)<-[:WORKS_AT]-(emp2:Employee),
      (po2:PurchaseOrder)-[:ORDERED_BY]->(emp2),
      (po2)-[:PLACED_WITH]->(s2:Supplier)
WHERE s1 != s2
  -- Look for potential circular patterns
  -- This requires actual customer-supplier relationships in the data
RETURN s1.Supplier.supplier_name AS supplier_a,
       s2.Supplier.supplier_name AS supplier_b,
       count(*) AS transaction_count;
```

### 4.3 Suspicious Buyer Concentration Pattern

**Pattern**: One employee creates POs to multiple suppliers who also have the same address or bank account (potential shell company fraud).

```ngql
-- Detect multiple suppliers with same bank account (potential shell company)
MATCH (s1:Supplier)-[:HAS_BANK]->(b:BankAccount)<-[:HAS_BANK]-(s2:Supplier)
WHERE s1.Supplier.supplier_number < s2.Supplier.supplier_number
  AND s1.Supplier.status IN ["ACTIVE", "BLOCKED"]
  AND s2.Supplier.status IN ["ACTIVE", "BLOCKED"]
WITH b.BankAccount.account_number AS bank_account,
     collect(DISTINCT s1.Supplier.supplier_name + " & " + s2.Supplier.supplier_name) AS supplier_pairs,
     count(DISTINCT s1.Supplier.supplier_number) AS supplier_count
WHERE supplier_count >= 2
RETURN bank_account,
       supplier_pairs,
       supplier_count,
       CASE
         WHEN supplier_count >= 3 THEN "HIGH_RISK"
         ELSE "MEDIUM_RISK"
       END AS risk_level
ORDER BY supplier_count DESC;
```

### 4.4 Rapid Transaction Cycle Pattern

**Pattern**: Unusually short time between PO creation, receipt, and invoice (may indicate fictitious transactions).

```ngql
-- Find transactions completed in unusually short time
-- Fictitious transactions may have same-day or next-day completions
MATCH (po:PurchaseOrder)-[:HAS_RECEIPT]->(r:Receipt)
WHERE po.PurchaseOrder.order_date IS NOT NULL
  AND r.Receipt.receipt_date IS NOT NULL
  AND datetime_diff(r.Receipt.receipt_date, po.PurchaseOrder.order_date) < 86400  -- Less than 1 day
WITH po.PurchaseOrder.po_number AS po,
     po.PurchaseOrder.supplier AS supplier,
     po.PurchaseOrder.order_date AS po_date,
     r.Receipt.receipt_date AS receipt_date,
     datetime_diff(r.Receipt.receipt_date, po.PurchaseOrder.order_date) / 86400 AS days_elapsed
WHERE days_elapsed < 1  -- Same day
RETURN po, supplier, po_date, receipt_date, days_elapsed
ORDER BY po_date DESC
LIMIT 50;
```

---

## 5. Constraint Validation Summary Table — 约束验证汇总表

| Category | Rule ID | Rule Description | Threshold | Alert Level |
|----------|---------|-----------------|-----------|-------------|
| Three-Way Match | TWM-1 | Quantity Match | ≤5% matched | WARNING >5%, ALERT >10% |
| Three-Way Match | TWM-2 | Amount Match | ≤10% matched | WARNING >10%, ALERT >20% |
| Three-Way Match | TWM-3 | Unit Price Match | EXACT | CRITICAL any diff |
| Three-Way Match | TWM-4 | Supplier Match | EXACT | CRITICAL any diff |
| PTP Temporal | PTC-1 | Receipt >= PO | Date check | HIGH if violated |
| PTP Temporal | PTC-2 | Invoice >= Receipt | Date check | HIGH if violated |
| PTP Temporal | PTC-3 | Payment >= Invoice | Date check | MEDIUM if violated |
| PTP Temporal | PTC-4 | PO >= PR | Date check | CRITICAL if violated |
| Amount Integrity | AM-1 | Line Amount = Qty × Price | Exact | CRITICAL |
| Amount Integrity | AM-2 | Header = SUM(Lines) | ±0.01 | CRITICAL |
| Payment | AM-5 | SUM(Payments) ≤ Invoice | N/A | CRITICAL if over |
| Cyclical | CYCL-1 | Circular supplier pattern | N/A | HIGH |
| Cyclical | CYCL-2 | Rapid transaction cycle | <1 day | MEDIUM |

---

## 6. Constraint Priority Levels — 约束优先级

| Priority | Level | Description | Action When Violated |
|----------|-------|-------------|---------------------|
| P1 | CRITICAL | Immediate fraud risk or regulatory violation | Block transaction, escalate to audit |
| P2 | HIGH | Significant control weakness | Investigate before payment |
| P3 | MEDIUM | Minor control deviation | Document and monitor |
| P4 | LOW | Informational | Log only |

---

## 7. Example Constraint Query Patterns — 约束查询模式示例

### Query 1: Run All Three-Way Match Validations

```ngql
-- Comprehensive three-way match validation
-- Returns all violations across all dimensions
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s:Supplier),
      (po)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine),
      (po)-[:HAS_RECEIPT]->(r:Receipt)-[:HAS_RECEIPT_LINE]->(rl:ReceiptLine),
      (po)-[:HAS_INVOICE]->(inv:Invoice)
WHERE pol.PurchaseOrderLine.line_number == rl.ReceiptLine.line_number
  AND inv.Invoice.status IN ["VALIDATED", "APPROVED"]
WITH po, pol, rl, inv, s,
     -- Quantity deviation
     CASE WHEN pol.PurchaseOrderLine.quantity > 0
          THEN abs(rl.ReceiptLine.received_quantity - pol.PurchaseOrderLine.quantity)
               / pol.PurchaseOrderLine.quantity
          ELSE 0 END AS qty_deviation,
     -- Amount deviation
     CASE WHEN po.PurchaseOrder.total_amount > 0
          THEN abs(inv.Invoice.total_amount - po.PurchaseOrder.total_amount)
               / po.PurchaseOrder.total_amount
          ELSE 0 END AS amt_deviation,
     -- Unit price check
     CASE WHEN pol.PurchaseOrderLine.unit_price == inv.Invoice.unit_price
          THEN "MATCHED" ELSE "MISMATCH" END AS price_status
WITH po.PurchaseOrder.po_number AS po_number,
     s.Supplier.supplier_name AS supplier,
     qty_deviation,
     amt_deviation,
     price_status,
     CASE
       WHEN price_status == "MISMATCH" THEN "CRITICAL"
       WHEN qty_deviation > 0.10 OR amt_deviation > 0.20 THEN "ALERT"
       WHEN qty_deviation > 0.05 OR amt_deviation > 0.10 THEN "WARNING"
       ELSE "GREEN"
     END AS overall_status
WHERE overall_status != "GREEN"
RETURN po_number, supplier, qty_deviation, amt_deviation, price_status, overall_status
ORDER BY
  CASE overall_status
    WHEN "CRITICAL" THEN 1
    WHEN "ALERT" THEN 2
    WHEN "WARNING" THEN 3
  END;
```

---

### Query 2: Temporal Constraint Dashboard

```ngql
-- PTP Temporal Constraint Violations Dashboard
// Count violations by type
MATCH (pr:PurchaseRequisition)-[:CONVERTS_TO_PO]->(po:PurchaseOrder)
OPTIONAL MATCH (po)-[:HAS_RECEIPT]->(r:Receipt)
OPTIONAL MATCH (po)-[:HAS_INVOICE]->(inv:Invoice)
OPTIONAL MATCH (inv)<-[:PAYS_INVOICE]-(pay:Payment)
WITH collect({
  type: "PO_vs_PR",
  violated: po.PurchaseOrder.order_date < pr.PurchaseRequisition.request_date,
  date1: pr.PurchaseRequisition.request_date,
  date2: po.PurchaseOrder.order_date
}) AS checks
UNWIND checks AS check
WITH check.type AS constraint_type,
     check.violated AS is_violated
WITH constraint_type,
     count(*) AS total_checks,
     sum(CASE WHEN is_violated THEN 1 ELSE 0 END) AS violations
RETURN constraint_type,
       violations,
       total_checks,
       (violations * 100.0 / total_checks) AS violation_pct;
```
