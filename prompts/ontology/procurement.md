# Procurement Domain Ontology (PTP) — 采购域本体（按单付款流程）

> Version: v1.0
> Date: 2026-04-04
> Domain: Procure-to-Pay (PTP) — 采购到付款
> NebulaGraph Space: honeybadge

---

## 1. Entity Definitions — 实体定义

### 1.1 PurchaseRequisition (采购申请单, PR)

**Business Meaning (业务含义)**:
An internal document initiated by a requester (employee) to request procurement of goods or services. The PR goes through an approval workflow before being converted to a Purchase Order. PRs can be standalone or grouped into blanket orders.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `pr_number` | STRING NOT NULL | Unique identifier (e.g., "PR-2026-00001") |
| `pr_type` | STRING | STANDARD (标准采购申请) / BLANKET (框架协议申请) / INTERNAL (内部调拨申请) |
| `description` | STRING | Purpose or justification for the request |
| `status` | STRING | DRAFT / PENDING_APPROVAL / APPROVED / REJECTED / CLOSED / CANCELLED |
| `requester` | STRING | Employee number of the person making the request |
| `request_date` | TIMESTAMP | Date the request was created |
| `need_by_date` | TIMESTAMP | Date the items/services are needed by |
| `total_amount` | DOUBLE | Sum of all PR line amounts |
| `currency` | STRING DEFAULT "CNY" | Currency code |
| `approval_date` | TIMESTAMP | Date of final approval |
| `approver` | STRING | Employee number of the approver |

**Status Lifecycle**:
```
DRAFT → PENDING_APPROVAL → APPROVED → CLOSED
              ↓                ↓
         REJECTED         CANCELLED
```

**VID Format**: `PR:{pr_number}` (e.g., `PR:PR-2026-00001`)

---

### 1.2 PurchaseRequisitionLine (采购申请行, PRLine)

**Business Meaning (业务含义)**:
Individual line items within a Purchase Requisition, specifying what to order (Item), how much (quantity), at what price (unit_price), and from whom (suggested_vendor).

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `line_number` | INT64 NOT NULL | Line sequence number (1, 2, 3...) |
| `quantity` | DOUBLE NOT NULL | Requested quantity |
| `unit_price` | DOUBLE | Budgetary or estimated unit price |
| `amount` | DOUBLE | line_amount = quantity × unit_price |
| `uom` | STRING | Unit of measure (EA/KG/M/L) |
| `need_by_date` | TIMESTAMP | Line-specific needed-by date |
| `suggested_vendor` | STRING | Supplier number of suggested supplier |
| `status` | STRING | OPEN / ORDERED / CLOSED / CANCELLED |

**VID Format**: `PRL:{pr_number}:{line_number}` (e.g., `PRL:PR-2026-00001:1`)

---

### 1.3 PurchaseOrder (采购订单, PO)

**Business Meaning (业务含义)**:
A formal legal document issued to a supplier to procure goods or services at agreed-upon terms. Once APPROVED, the PO is a binding contract. The PO is the central anchor of the PTP cycle — all subsequent documents (Receipt, Invoice, Payment) link back to the PO.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `po_number` | STRING NOT NULL | Unique identifier (e.g., "PO-20260101-001") |
| `po_type` | STRING | STANDARD (标准PO) / BLANKET (框架PO) / CONTRACT (合同PO) / PLANNED (计划PO) |
| `description` | STRING | Description of the order |
| `status` | STRING | DRAFT / APPROVED / OPEN / CLOSED / CANCELLED |
| `buyer` | STRING | Employee number of the buyer who created the PO |
| `order_date` | TIMESTAMP | Date the PO was issued |
| `approved_date` | TIMESTAMP | Date of PO approval |
| `total_amount` | DOUBLE NOT NULL | Total PO value (sum of all lines + taxes) |
| `currency` | STRING DEFAULT "CNY" | Currency |
| `exchange_rate` | DOUBLE DEFAULT 1.0 | Exchange rate for foreign currency POs |
| `payment_terms` | STRING | NET30 / NET60 / PREPAY etc. |
| `freight_terms` | STRING | FOB / CIF / DDP etc. |
| `ship_to_location` | STRING | Delivery destination |
| `bill_to_location` | STRING | Invoice billing address |
| `close_date` | TIMESTAMP | Date the PO was formally closed |
| `cancel_reason` | STRING | Reason for cancellation if cancelled |

**Status Lifecycle**:
```
DRAFT → APPROVED → OPEN → CLOSED
                       ↓
                  CANCELLED
```
- DRAFT: Created but not yet submitted for approval
- APPROVED: Approved and legally binding
- OPEN: Goods/services being fulfilled (partial or full)
- CLOSED: Fully received and invoiced, or formally closed
- CANCELLED: Terminated before completion

**VID Format**: `PO:{po_number}` (e.g., `PO:PO-20260101-001`)

---

### 1.4 PurchaseOrderLine (采购订单行, POLine)

**Business Meaning (业务含义)**:
Individual line items within a PO specifying the Item, quantity, unit price, and delivery requirements. Each POLine tracks how much has been received (received_quantity) and invoiced (invoiced_quantity) to support partial fulfillment.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `line_number` | INT64 NOT NULL | Line sequence number |
| `line_type` | STRING | GOODS (物料) / SERVICE (服务) |
| `quantity` | DOUBLE NOT NULL | Ordered quantity |
| `unit_price` | DOUBLE NOT NULL | Negotiated unit price |
| `amount` | DOUBLE NOT NULL | line_amount = quantity × unit_price |
| `uom` | STRING | Unit of measure |
| `need_by_date` | TIMESTAMP | Required delivery date |
| `promised_date` | TIMESTAMP | Supplier's promised delivery date |
| `received_quantity` | DOUBLE DEFAULT 0 | Total quantity received across all receipts |
| `invoiced_quantity` | DOUBLE DEFAULT 0 | Total quantity invoiced |
| `status` | STRING | OPEN / PARTIAL / FULLY_RECEIVED / CLOSED / CANCELLED |
| `tax_code` | STRING | Tax category code |
| `tax_rate` | DOUBLE DEFAULT 0 | Tax rate percentage |

**Business Rule**: `amount = quantity × unit_price` (should always be consistent)

**VID Format**: `POL:{po_number}:{line_number}` (e.g., `POL:PO-20260101-001:1`)

---

### 1.5 Receipt (收货单)

**Business Meaning (业务含义)**:
A document confirming physical receipt of goods at the receiving dock or warehouse. Receipt is the evidence that goods were delivered, triggering the supplier's right to invoice. Receipts can be partial (not all ordered quantity received at once).

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `receipt_number` | STRING NOT NULL | Unique identifier (e.g., "RCV-20260101-001") |
| `receipt_type` | STRING | STANDARD (标准收货) / RETURN (退货) |
| `receipt_date` | TIMESTAMP NOT NULL | Date goods were physically received |
| `status` | STRING | PENDING (待检验) / RECEIVED (已收货) / PARTIALLY_RECEIVED (部分收货) / RETURNED (已退货) |
| `receiver` | STRING | Employee number of the receiving clerk |
| `total_quantity` | DOUBLE | Sum of all received quantities |
| `warehouse` | STRING | Warehouse code where goods are received |
| `comments` | STRING | Notes about the receipt condition |

**VID Format**: `RCV:{receipt_number}` (e.g., `RCV:RCV-20260101-001`)

---

### 1.6 ReceiptLine (收货单行)

**Business Meaning (业务含义)**:
Individual line items within a Receipt, capturing the quantity received, accepted, and rejected during inspection. This is critical for quality control and for calculating PO line fulfillment.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `line_number` | INT64 NOT NULL | Line sequence number |
| `received_quantity` | DOUBLE NOT NULL | Quantity physically received |
| `accepted_quantity` | DOUBLE | Quantity that passed inspection |
| `rejected_quantity` | DOUBLE DEFAULT 0 | Quantity that failed inspection |
| `uom` | STRING | Unit of measure |
| `inspection_status` | STRING | PENDING / PASSED / FAILED |
| `lot_number` | STRING | Lot/batch number for traceability |
| `sublocation` | STRING | Specific location within warehouse |

**Business Rule**: `received_quantity = accepted_quantity + rejected_quantity` (should always balance)

**VID Format**: `RCVL:{receipt_number}:{line_number}` (e.g., `RCVL:RCV-20260101-001:1`)

---

## 2. Relationship Definitions — 关系定义

### 2.1 HAS_PR_LINE (采购申请包含行)

**Direction**: PurchaseRequisition → PurchaseRequisitionLine

**Business Meaning**: A PR consists of one or more line items. A PRLine cannot exist without its parent PR.

---

### 2.2 CONVERTS_TO_PO (采购申请转采购订单)

**Direction**: PurchaseRequisition → PurchaseOrder
**Edge Properties**: `conversion_date TIMESTAMP`

**Business Meaning**: Links a PR to the PO(s) created from it. One PR can convert to:
1. One PO (1:1 conversion)
2. Multiple POs (1:N — split conversion when one supplier can't fulfill everything)
3. Or multiple PRs can combine into one PO (N:1 — blanket PO)

---

### 2.3 PLACED_WITH (采购订单下达给供应商)

**Direction**: PurchaseOrder → Supplier

**Business Meaning**: The supplier who will fulfill this PO. All POs must be placed with an ACTIVE, non-BLOCKED supplier.

---

### 2.4 HAS_PO_LINE (采购订单包含行)

**Direction**: PurchaseOrder → PurchaseOrderLine

**Business Meaning**: The line items that make up the PO. PO.total_amount should equal the sum of all POLine amounts.

---

### 2.5 ORDERS_ITEM (PO行订购物料)

**Direction**: PurchaseOrderLine → Item

**Business Meaning**: The specific Item being ordered. This links the PO line to the Item master for catalog management and spend analysis.

---

### 2.6 ORDERED_BY (采购订单由采购员创建)

**Direction**: PurchaseOrder → Employee

**Business Meaning**: The employee (buyer) who created and is responsible for this PO.

---

### 2.7 HAS_RECEIPT (采购订单对应收货)

**Direction**: PurchaseOrder → Receipt

**Business Meaning**: Links a PO to the Receipt(s) created against it. Multiple receipts can be created against one PO (for partial shipments).

---

### 2.8 HAS_RECEIPT_LINE (收货单包含行)

**Direction**: Receipt → ReceiptLine

**Business Meaning**: The line items of a receipt, each corresponding to a POLine.

---

### 2.9 RECEIVED_AT (收货入库到仓库)

**Direction**: Receipt → Warehouse

**Business Meaning**: The warehouse where the goods were physically received and stored.

---

### 2.10 UNDER_CONTRACT (采购订单基于合同)

**Direction**: PurchaseOrder → Contract

**Business Meaning**: If the PO is created under a contract/blanket agreement, this relationship links them. Used for contract compliance checking (e.g., PO amount should not exceed contract ceiling).

---

### 2.11 HAS_INVOICE (采购订单对应发票)

**Direction**: PurchaseOrder → Invoice
**Edge Properties**: `match_status STRING`, `match_date TIMESTAMP`

**Business Meaning**: Links a PO to the Invoice received from the supplier. The match_status indicates three-way match results: MATCHED / UNMATCHED / PARTIAL.

---

## 3. Temporal Constraints — 时序约束

**CRITICAL BUSINESS RULE — PTP Temporal Sequence (按单付款时序)**:

The PTP process has strict temporal ordering. Each document's date must follow the previous stage:

```
PR.request_date ≤ PO.order_date ≤ Receipt.receipt_date ≤ Invoice.invoice_date ≤ Payment.payment_date
```

| Stage | Document | Date Field | Constraint |
|-------|----------|------------|------------|
| 1 | PurchaseRequisition | request_date | Must be earliest |
| 2 | PurchaseOrder | order_date | Must be after PR.request_date |
| 3 | Receipt | receipt_date | Must be after PO.order_date |
| 4 | Invoice | invoice_date | Must be after Receipt.receipt_date |
| 5 | Payment | payment_date | Must be after Invoice.invoice_date |

**Violations and Their Business Implications**:
| Violation Type | Implication |
|---------------|-------------|
| Receipt.date < PO.order_date | Retroactive receipt — possible fictional transaction |
| Invoice.date < Receipt.date | Pre-invoice (billing before delivery) — unusual, potential fraud |
| Payment.date < Invoice.date | Advance payment without goods received — risk of non-delivery |
| Payment.date > Invoice.due_date + 30 | Excessive overdue — potential cash flow issue or dispute |

---

## 4. Quantity Matching Rules — 数量匹配规则

### Rule 1: Receipt vs PO Quantity (超收允许范围)

**Rule Definition**: `received_quantity` should not exceed `PO_line.quantity × 1.1` (110% of ordered quantity). Excess of up to 10% is allowed to accommodate shipping variances, but anything above that is suspicious.

**Business Rationale**: Suppliers sometimes ship slightly more than ordered (bulk rounding, packing efficiency). A 10% tolerance is industry standard. However, over-shipment beyond 10% may indicate:
1. Pricing fraud (invoicing for more than shipped)
2. Quality issues (rejected quantities not tracked properly)
3. Vendor manipulation

**Detection Query**: Find receipts where `received_quantity > poline.quantity * 1.1`

---

### Rule 2: Invoice vs PO Quantity (三单匹配)

**Rule Definition**: Invoice quantity should match PO quantity within tolerance:
- Exact match: `|Invoice.qty - PO.qty| / PO.qty ≤ 5%` = MATCHED
- Deviation 5-10%: WARNING
- Deviation > 10%: ALERT

---

### Rule 3: Accumulated Receipt vs PO Quantity

**Rule Definition**: Total accumulated `received_quantity` across all Receipts for a given POLine should not exceed `POLine.quantity × 1.1`.

---

## 5. Status Dependency Rules — 状态依赖规则

| Current Status | Can Transition To | Required Condition |
|---------------|-------------------|---------------------|
| PO DRAFT | APPROVED | Approval workflow completed |
| PO APPROVED | OPEN | PO sent to supplier (acknowledged) |
| PO OPEN | CLOSED | All lines fully received + invoiced |
| PO OPEN | CANCELLED | Cancellation reason provided |
| Receipt PENDING | RECEIVED | Inspection completed |
| Receipt RECEIVED | (triggers invoice) | Invoice can now be created |

---

## 6. Example nGQL Queries — nGQL 查询示例

### Query 1: Find All Purchase Orders for a Supplier (查找某供应商的所有采购订单)

**Business Context**: Supplier account manager needs to see all active POs with a specific vendor for relationship management.

```ngql
-- Find all POs placed with a specific supplier
-- Show PO details sorted by order date descending
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s:Supplier)
WHERE s.Supplier.supplier_number == "V001234"
  AND po.PurchaseOrder.status IN ["APPROVED", "OPEN"]  -- Only active POs
RETURN po.PurchaseOrder.po_number AS po_number,
       po.PurchaseOrder.po_type AS po_type,
       po.PurchaseOrder.order_date AS order_date,
       po.PurchaseOrder.total_amount AS total_amount,
       po.PurchaseOrder.currency AS currency,
       po.PurchaseOrder.payment_terms AS payment_terms,
       po.PurchaseOrder.status AS status
ORDER BY po.PurchaseOrder.order_date DESC
LIMIT 50;
```

---

### Query 2: PO Complete Lifecycle Trace (PO完整生命周期追溯)

**Business Context**: Auditor wants to trace the complete lifecycle of a PO from PR origin through to payment.

```ngql
-- Trace the complete PTP lifecycle: PR → PO → Receipt → Invoice → Payment
-- This query uses OPTIONAL MATCH to handle cases where some documents don't exist
MATCH (pr:PurchaseRequisition)-[:CONVERTS_TO_PO]->(po:PurchaseOrder)
WHERE po.PurchaseOrder.po_number == "PO-2026-0001"
OPTIONAL MATCH (po)-[:PLACED_WITH]->(s:Supplier)
OPTIONAL MATCH (po)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine)
OPTIONAL MATCH (po)-[:HAS_RECEIPT]->(r:Receipt)-[:HAS_RECEIPT_LINE]->(rl:ReceiptLine)
OPTIONAL MATCH (po)-[:HAS_INVOICE]->(inv:Invoice)
OPTIONAL MATCH (inv)<-[:PAYS_INVOICE]-(pay:Payment)
RETURN
  -- PR Information
  pr.PurchaseRequisition.pr_number AS pr_number,
  pr.PurchaseRequisition.request_date AS pr_date,
  pr.PurchaseRequisition.requester AS requester,
  -- PO Information
  po.PurchaseOrder.po_number AS po_number,
  po.PurchaseOrder.order_date AS po_date,
  po.PurchaseOrder.total_amount AS po_amount,
  po.PurchaseOrder.status AS po_status,
  -- Supplier
  s.Supplier.supplier_name AS supplier_name,
  -- PO Line Summary
  count(DISTINCT pol.PurchaseOrderLine.line_number) AS po_line_count,
  sum(pol.PurchaseOrderLine.quantity) AS total_ordered_qty,
  -- Receipt Information
  collect(DISTINCT r.Receipt.receipt_number) AS receipt_numbers,
  sum(rl.ReceiptLine.received_quantity) AS total_received_qty,
  -- Invoice Information
  collect(DISTINCT inv.Invoice.invoice_number) AS invoice_numbers,
  inv.Invoice.total_amount AS invoice_amount,
  inv.Invoice.invoice_date AS invoice_date,
  -- Payment Information
  collect(DISTINCT pay.Payment.payment_number) AS payment_numbers,
  pay.Payment.amount AS payment_amount,
  pay.Payment.payment_date AS payment_date;
```

---

### Query 3: Over-Receipt Anomaly Detection (超量收货异常检测)

**Business Context**: Internal audit needs to detect receipts that exceed PO quantities by more than 10%, which may indicate over-shipment fraud.

```ngql
-- Find receipts where received quantity exceeds PO line quantity by more than 10%
-- This may indicate over-shipment, pricing fraud, or data entry errors
MATCH (po:PurchaseOrder)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine),
      (po)-[:HAS_RECEIPT]->(r:Receipt)-[:HAS_RECEIPT_LINE]->(rl:ReceiptLine),
      (po)-[:PLACED_WITH]->(s:Supplier)
WHERE rl.ReceiptLine.line_number == pol.PurchaseOrderLine.line_number
  AND rl.ReceiptLine.received_quantity > pol.PurchaseOrderLine.quantity * 1.1
  AND po.PurchaseOrder.status IN ["APPROVED", "OPEN", "CLOSED"]
RETURN po.PurchaseOrder.po_number AS po_number,
       pol.PurchaseOrderLine.line_number AS po_line,
       s.Supplier.supplier_name AS supplier_name,
       pol.PurchaseOrderLine.quantity AS ordered_qty,
       rl.ReceiptLine.received_quantity AS received_qty,
       (rl.ReceiptLine.received_quantity - pol.PurchaseOrderLine.quantity) AS over_ship_qty,
       (rl.ReceiptLine.received_quantity / pol.PurchaseOrderLine.quantity - 1) * 100 AS over_ship_pct,
       r.Receipt.receipt_date AS receipt_date,
       rl.ReceiptLine.inspection_status AS inspection_status
ORDER BY over_ship_pct DESC
LIMIT 50;
```

---

### Query 4: PR to PO Conversion Analysis (采购申请转单率分析)

**Business Context**: Procurement efficiency team tracks how many approved PRs get converted to POs, and how many get cancelled or expire.

```ngql
-- Analyze PR to PO conversion rates by requester
-- This measures procurement efficiency and request quality
MATCH (pr:PurchaseRequisition)-[e:CONVERTS_TO_PO]->(po:PurchaseOrder)
WHERE pr.PurchaseRequisition.status IN ["APPROVED", "CLOSED", "CANCELLED"]
  AND pr.PurchaseRequisition.request_date >= datetime_add(now(), INTERVAL -90 DAY)
WITH pr.PurchaseRequisition.pr_number AS pr_number,
     pr.PurchaseRequisition.requester AS requester,
     pr.PurchaseRequisition.total_amount AS pr_amount,
     e.CONVERTS_TO_PO.conversion_date AS conversion_date,
     CASE
       WHEN po.PurchaseOrder.status IN ["APPROVED", "OPEN", "CLOSED"] THEN "CONVERTED"
       WHEN po.PurchaseOrder.status == "CANCELLED" THEN "CANCELLED"
       ELSE "OTHER"
     END AS conversion_result
WITH requester,
     count(*) AS total_prs,
     sum(CASE WHEN conversion_result == "CONVERTED" THEN 1 ELSE 0 END) AS converted_prs,
     sum(CASE WHEN conversion_result == "CANCELLED" THEN 1 ELSE 0 END) AS cancelled_prs,
     sum(pr_amount) AS total_pr_amount
RETURN requester,
       total_prs,
       converted_prs,
       cancelled_prs,
       (converted_prs * 100.0 / total_prs) AS conversion_rate_pct,
       total_pr_amount
ORDER BY conversion_rate_pct ASC  -- Lowest conversion rate first (needs review)
LIMIT 20;
```

---

### Query 5: Purchase Order Spend by Category (采购订单金额分布分析)

**Business Context**: Finance team needs to understand spend distribution by item category to optimize procurement strategy.

```ngql
-- Analyze PO spend by item category
-- Shows where procurement budget is being spent
MATCH (po:PurchaseOrder)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine),
      (pol)-[:ORDERS_ITEM]->(i:Item),
      (po)-[:PLACED_WITH]->(s:Supplier)
WHERE po.PurchaseOrder.status IN ["APPROVED", "OPEN", "CLOSED"]
  AND po.PurchaseOrder.order_date >= datetime_add(now(), INTERVAL -365 DAY)
  AND po.PurchaseOrder.currency == "CNY"
RETURN i.Item.category AS item_category,
       i.Item.item_type AS item_type,
       count(DISTINCT po.PurchaseOrder.po_number) AS po_count,
       count(DISTINCT s.Supplier.supplier_number) AS supplier_count,
       sum(pol.PurchaseOrderLine.amount) AS total_spend,
       sum(pol.PurchaseOrderLine.quantity) AS total_quantity,
       avg(pol.PurchaseOrderLine.unit_price) AS avg_unit_price
ORDER BY total_spend DESC
LIMIT 30;
```

---

### Query 6: Delivery Performance Analysis by Supplier (供应商交货绩效分析)

**Business Context**: Procurement manager evaluates supplier performance based on on-time and in-full delivery metrics.

```ngql
-- Analyze delivery performance: promised date vs actual receipt date
-- Calculate on-time delivery rate for each supplier
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s:Supplier),
      (po)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine),
      (po)-[:HAS_RECEIPT]->(r:Receipt)-[:HAS_RECEIPT_LINE]->(rl:ReceiptLine)
WHERE po.PurchaseOrder.status == "CLOSED"
  AND pol.PurchaseOrderLine.line_type == "GOODS"
  AND pol.PurchaseOrderLine.need_by_date IS NOT NULL
  AND r.Receipt.receipt_date IS NOT NULL
WITH s.Supplier.supplier_number AS supplier_number,
     s.Supplier.supplier_name AS supplier_name,
     po.PurchaseOrder.po_number AS po_number,
     pol.PurchaseOrderLine.need_by_date AS promised_date,
     r.Receipt.receipt_date AS actual_date,
     pol.PurchaseOrderLine.quantity AS ordered_qty,
     rl.ReceiptLine.received_quantity AS received_qty,
     -- Calculate delay in days (positive = late, negative = early)
     (datetime_diff(r.Receipt.receipt_date, pol.PurchaseOrderLine.need_by_date) / 86400) AS delay_days,
     -- Calculate in-full rate
     CASE
       WHEN rl.ReceiptLine.received_quantity >= pol.PurchaseOrderLine.quantity THEN 1.0
       ELSE rl.ReceiptLine.received_quantity / pol.PurchaseOrderLine.quantity
     END AS in_full_rate,
     -- On-time if receipt date <= promised date
     CASE
       WHEN r.Receipt.receipt_date <= pol.PurchaseOrderLine.need_by_date THEN "ON_TIME"
       ELSE "LATE"
     END AS delivery_status
WITH supplier_number,
     supplier_name,
     count(*) AS total_lines,
     sum(CASE WHEN delivery_status == "ON_TIME" THEN 1 ELSE 0 END) AS on_time_count,
     sum(CASE WHEN delivery_status == "LATE" THEN 1 ELSE 0 END) AS late_count,
     avg(delay_days) AS avg_delay_days,
     min(delay_days) AS max_early_days,
     max(delay_days) AS max_late_days,
     avg(in_full_rate) AS avg_in_full_rate
RETURN supplier_number,
       supplier_name,
       total_lines,
       on_time_count,
       late_count,
       (on_time_count * 100.0 / total_lines) AS on_time_rate_pct,
       avg_delay_days,
       max_late_days,
       avg_in_full_rate
ORDER BY on_time_rate_pct ASC  -- Worst performers first
LIMIT 20;
```

---

### Query 7: Find POs Without Receipt (未收货的采购订单)

**Business Context**: Procurement team tracks open POs to ensure suppliers are delivering on schedule.

```ngql
-- Find POs that are APPROVED or OPEN but have no receipts
-- These may indicate delivery delays or supplier non-performance
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s:Supplier)
WHERE po.PurchaseOrder.status IN ["APPROVED", "OPEN"]
  AND po.PurchaseOrder.order_date >= datetime_add(now(), INTERVAL -180 DAY)
  AND NOT (po)-[:HAS_RECEIPT]->(:Receipt)
RETURN po.PurchaseOrder.po_number AS po_number,
       po.PurchaseOrder.order_date AS order_date,
       po.PurchaseOrder.total_amount AS po_amount,
       s.Supplier.supplier_name AS supplier_name,
       po.PurchaseOrder.need_by_date AS need_by_date,
       datetime_diff(po.PurchaseOrder.need_by_date, now()) / 86400 AS days_until_due,
       po.PurchaseOrder.buyer AS buyer
ORDER BY days_until_due ASC  -- Most overdue first
LIMIT 50;
```

---

## 7. Summary Table — 汇总表

| Entity | VID Format | Description |
|--------|------------|-------------|
| PurchaseRequisition | `PR:{pr_number}` | Internal procurement request |
| PurchaseRequisitionLine | `PRL:{pr_number}:{line}` | Line item of PR |
| PurchaseOrder | `PO:{po_number}` | Legal PO to supplier |
| PurchaseOrderLine | `POL:{po_number}:{line}` | Line item of PO |
| Receipt | `RCV:{receipt_number}` | Goods receipt confirmation |
| ReceiptLine | `RCVL:{receipt_number}:{line}` | Line item of receipt |

| Relationship | Direction | Description |
|--------------|-----------|-------------|
| HAS_PR_LINE | PR → PRL | PR contains lines |
| CONVERTS_TO_PO | PR → PO | PR converts to PO |
| PLACED_WITH | PO → Supplier | PO is with supplier |
| HAS_PO_LINE | PO → POL | PO contains lines |
| ORDERS_ITEM | POL → Item | PO line orders item |
| ORDERED_BY | PO → Employee | PO created by buyer |
| HAS_RECEIPT | PO → Receipt | PO has receipts |
| HAS_RECEIPT_LINE | Receipt → ReceiptLine | Receipt has lines |
| RECEIVED_AT | Receipt → Warehouse | Received at warehouse |
| HAS_INVOICE | PO → Invoice | PO matched to invoice |
| UNDER_CONTRACT | PO → Contract | PO under contract |

---

## 8. Temporal Sequence Summary

```
PR.request_date → PO.order_date → Receipt.receipt_date → Invoice.invoice_date → Payment.payment_date
     (earliest)          ↓               ↓                    ↓                (latest)
                   APPROVED date    status=RECEIVED      status=VALIDATED     status=CLEARED
```

**Key Date Fields for Temporal Validation**:
- PR: `request_date`
- PO: `order_date`, `approved_date`
- Receipt: `receipt_date`
- Invoice: `invoice_date`, `due_date`
- Payment: `payment_date`, `cleared_date`
