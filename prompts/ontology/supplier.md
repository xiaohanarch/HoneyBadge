# Supplier Domain Ontology — 供应商域本体

> Version: v1.0
> Date: 2026-04-04
> Domain: Master Data / Supplier Management
> NebulaGraph Space: honeybadge

---

## 1. Entity Definitions — 实体定义

### 1.1 Supplier (供应商)

**Business Meaning (业务含义)**:
An external organization that provides goods or services to the company. Suppliers are a critical part of the Procure-to-Pay (PTP) cycle. Every Purchase Order (PO) must be placed with an approved, ACTIVE supplier from the Approved Supplier List (ASL).

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `supplier_number` | STRING NOT NULL | Unique identifier (e.g., "V001234"). Primary key for VID generation. Format: `SUP:{supplier_number}` |
| `supplier_name` | STRING NOT NULL | Legal or trade name |
| `supplier_type` | STRING | MANUFACTURER / DISTRIBUTOR / SERVICE_PROVIDER / TRADING_COMPANY |
| `status` | STRING | ACTIVE (正常) / INACTIVE (停用) / BLOCKED (冻结) / PENDING (待审核). BLOCKED suppliers cannot have new POs placed with them. |
| `country` | STRING | Country of registration |
| `city` | STRING | City of primary business location |
| `address` | STRING | Full address |
| `contact_person` | STRING | Primary contact name |
| `contact_phone` | STRING | Phone number |
| `contact_email` | STRING | Email address |
| `bank_account` | STRING | Bank account number for payments |
| `bank_name` | STRING | Bank name |
| `tax_id` | STRING | Tax registration number (纳税人识别号) |
| `currency` | STRING DEFAULT "CNY" | Default payment currency |
| `payment_terms` | STRING | NET30 / NET60 / NET90 / IMMEDIATE / PREPAY |
| `credit_rating` | STRING | A / B / C / D risk rating |
| `registration_date` | TIMESTAMP | Date supplier was first registered |
| `qualification_expiry` | TIMESTAMP | Aggregate expiry date for all qualifications (for quick filtering) |

**Status Lifecycle (状态生命周期)**:
```
PENDING → ACTIVE ↔ INACTIVE
              ↓
           BLOCKED
```
- PENDING: New supplier awaiting first approval
- ACTIVE: Approved for business transactions
- INACTIVE: Soft-deleted or temporarily disabled
- BLOCKED: Blacklisted/fraudulent supplier — no new POs allowed

**VID Format**: `SUP:{supplier_number}` (e.g., `SUP:V001234`)

---

### 1.2 SupplierQualification (供应商资质认证)

**Business Meaning (业务含义)**:
Certificates, licenses, and qualifications held by a supplier. These represent regulatory compliance (ISO9001, environmental certifications), safety certifications, or industry-specific accreditations. Expired or revoked qualifications are a compliance risk.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `qualification_id` | STRING NOT NULL | Unique identifier (e.g., "QUAL-2026-001") |
| `qualification_type` | STRING | ISO9001 / ISO14001 / SAFETY / ENVIRONMENTAL / BUSINESS_LICENSE / CUSTOM |
| `status` | STRING | VALID (有效) / EXPIRED (已过期) / REVOKED (已撤销) / SUSPENDED (暂停) |
| `issue_date` | TIMESTAMP | Date certification was issued |
| `expiry_date` | TIMESTAMP | Expiration date — critical for renewal alerts |
| `issuing_body` | STRING | Certification authority (e.g., " Bureau of Standards") |
| `scope` | STRING | Scope of certification (geographic, product category, etc.) |

**VID Format**: `SQ:{qualification_id}` (e.g., `SQ:QUAL-2026-001`)

---

## 2. Relationship Definitions — 关系定义

### 2.1 SUPPLIES_ITEM (供应商供应物料)

**Direction**: Supplier → Item
**Edge Properties**:
| Property | Type | Description |
|----------|------|-------------|
| `priority` | INT64 | Supplier priority for this item (1 = highest). Used in auto-PO suggestions. |
| `unit_price` | DOUBLE | Negotiated unit price for this item |
| `lead_time_days` | INT64 | Expected delivery lead time in days |
| `status` | STRING | ACTIVE / INACTIVE — enables disabling a supply relationship without deleting it |
| `effective_from` | TIMESTAMP | Start date of this supply relationship |
| `effective_to` | TIMESTAMP | End date (NULL = no expiry) |

**Business Meaning (业务含义)**:
This is the Approved Supplier List (ASL) — the master record of which suppliers are approved to supply which items. A supplier with SUPPLIES_ITEM edge to an item means that supplier is pre-approved for that item. Multiple suppliers can supply the same item (with different priority rankings).

**Example Scenario**: Item "ITEM-001" (a raw material) has three suppliers in the ASL:
- Supplier "V001" with priority=1 (primary), unit_price=100 CNY, lead_time=7 days
- Supplier "V002" with priority=2 (secondary), unit_price=98 CNY, lead_time=14 days
- Supplier "V003" with priority=3 (backup), unit_price=95 CNY, lead_time=21 days

---

### 2.2 HAS_QUALIFICATION (供应商持有资质)

**Direction**: Supplier → SupplierQualification

**Business Meaning (业务含义)**:
Links a supplier to each qualification/certification it holds. A supplier can have multiple qualifications. This relationship enables:
1. Filtering suppliers by specific certification type
2. Alerting when qualifications are about to expire
3. Compliance checks during PO creation

---

### 2.3 PLACED_WITH (采购订单下达给供应商)

**Direction**: PurchaseOrder → Supplier
**Edge Properties**: `order_date TIMESTAMP`

**Business Meaning (业务含义)**:
Links a Purchase Order to the supplier it is placed with. This is a critical relationship for spend analysis, supplier concentration risk, and fraud detection. All financial transactions (Invoice, Payment) trace back to a PLACED_WITH edge.

**Note**: Only one PLACED_WITH edge per PO (one PO has one primary supplier).

---

### 2.4 INVOICED_BY (发票开具方)

**Direction**: Invoice → Supplier

**Business Meaning (业务含义)**:
Links an Invoice to the supplier who issued it. Must match the PLACED_WITH supplier of the corresponding PO (three-way match consistency check).

---

### 2.5 PAID_TO (付款收款方)

**Direction**: Payment → Supplier

**Business Meaning (业务含义)**:
Links a Payment to the supplier who receives it. Must match the INVOICED_BY supplier of the corresponding Invoice.

---

### 2.6 CONTRACT_WITH (合同签约方)

**Direction**: Contract → Supplier (or Contract → Customer)
**Edge Properties**: `party_type STRING` ("SUPPLIER" or "CUSTOMER")

**Business Meaning (业务含义)**:
Links a Contract to its counterparty. Enables contract-based procurement compliance checking.

---

## 3. Business Rules — 业务规则

### Rule 1: Single Supplier Risk (单一供应商风险)

**Rule Definition**: If a given Item has exactly ONE ACTIVE supplier in the SUPPLIES_ITEM relationship, that item is at risk of supply disruption.

**Business Impact**: If the single supplier experiences production issues, goes bankrupt, or is blocked, the company cannot procure that item. This is a supply chain vulnerability.

**Detection Logic**:
```ngql
-- An item has only 1 ACTIVE supplier (count suppliers where edge status == "ACTIVE" AND supplier status == "ACTIVE")
-- This item is a single-source item and should be flagged
```

**Risk Level**: MEDIUM (单一供应商本身是中风险，但如果该物料是关键原材料，则为 HIGH)

**Mitigation**: Identify alternative suppliers, maintain safety stock, establish backup supplier relationships

---

### Rule 2: Qualification Expiry Alert (资质到期预警)

**Rule Definition**: Any SupplierQualification with `expiry_date` within 30 days should trigger a renewal alert.

**Business Impact**: Operating with an expired qualification can result in:
1. Regulatory non-compliance (environmental, safety certifications)
2. Product quality issues (ISO9001 lapsed)
3. Contractual breaches with customers who require supplier certifications

**Detection Logic**:
```ngql
-- Find qualifications where:
--   status == "VALID" AND expiry_date <= now() + 30 days
-- These are pending expiry and need renewal action
```

**Risk Level**: HIGH (if expired during critical production) / MEDIUM (otherwise)

---

### Rule 3: Supplier Concentration Risk (供应商集中度风险)

**Rule Definition**: If total PO amount from a single supplier exceeds 30% of total company PO spend in a given period, this indicates concentration risk.

**Business Impact**: Over-reliance on one supplier creates:
1. Negotiation power imbalance (supplier can raise prices)
2. Supply chain fragility
3. Fraud risk (kickback schemes easier with single dominant supplier)

**Detection Logic**:
```ngql
-- Calculate supplier's PO spend as percentage of total PO spend
-- If any supplier's share > 30%, flag as concentration risk
```

**Risk Level**: HIGH if >50%, MEDIUM if >30%

---

### Rule 4: Blocked Supplier Restriction (冻结供应商限制)

**Rule Definition**: BLOCKED suppliers must not have any new Purchase Orders placed with them.

**Business Impact**: BLOCKED status indicates:
1. Fraud or financial misconduct discovered
2. Severe quality failures
3. Contract breach
4. Legal dispute

Continuing to transact with BLOCKED suppliers exposes the company to legal and financial risk.

**Detection Logic**:
```ngql
-- Find any PO placed with a BLOCKED supplier
-- PO.placed_with.supplier.status == "BLOCKED"
-- This is a compliance violation
```

**Risk Level**: CRITICAL

---

### Rule 5: Supplier-Item Supply Relationship Validity (供应关系有效性)

**Rule Definition**: A SUPPLIES_ITEM relationship is only valid when:
1. The edge property `status == "ACTIVE"`
2. The Supplier vertex `status == "ACTIVE"`
3. Current date is between `effective_from` and `effective_to` (if effective_to is set)

**Detection Logic**:
```ngql
-- Check: edge.status == "ACTIVE"
-- Check: supplier.Supplier.status == "ACTIVE"
-- Check: current_date >= edge.effective_from AND (edge.effective_to IS NULL OR current_date <= edge.effective_to)
```

---

## 4. Example nGQL Queries — nGQL 查询示例

### Query 1: Find All Approved Suppliers for an Item (查找某物料的所有合格供应商)

**Business Context**: A procurement team member wants to know which suppliers can supply Item "ITEM-001", sorted by priority. This is the first step in creating a new PO.

```ngql
-- Match suppliers who have an ACTIVE supply relationship with the item
-- Filter by both edge status and supplier status being ACTIVE
-- Order by priority (1 = highest)
MATCH (s:Supplier)-[e:SUPPLIES_ITEM]->(i:Item)
WHERE i.Item.item_number == "ITEM-001"
  AND e.SUPPLIES_ITEM.status == "ACTIVE"
  AND s.Supplier.status == "ACTIVE"
  -- Only include relationships currently within effective date range
  AND (e.SUPPLIES_ITEM.effective_from IS NULL OR e.SUPPLIES_ITEM.effective_from <= now())
  AND (e.SUPPLIES_ITEM.effective_to IS NULL OR e.SUPPLIES_ITEM.effective_to >= now())
RETURN s.Supplier.supplier_number AS supplier_number,
       s.Supplier.supplier_name AS supplier_name,
       e.SUPPLIES_ITEM.priority AS priority,
       e.SUPPLIES_ITEM.unit_price AS unit_price,
       e.SUPPLIES_ITEM.lead_time_days AS lead_time_days,
       s.Supplier.payment_terms AS payment_terms
ORDER BY e.SUPPLIES_ITEM.priority ASC
LIMIT 20;
```

---

### Query 2: Find Single-Source Items (Supply Disruption Risk) (查找单一供应商物料)

**Business Context**: The supply chain risk team needs to identify items that depend on only one supplier, which poses supply disruption risk.

```ngql
-- Find items that have exactly one ACTIVE supplier
-- This indicates single-source dependency and supply risk
MATCH (s:Supplier)-[e:SUPPLIES_ITEM]->(i:Item)
WHERE e.SUPPLIES_ITEM.status == "ACTIVE"
  AND s.Supplier.status == "ACTIVE"
WITH i.Item.item_number AS item_number,
     i.Item.item_name AS item_name,
     count(s) AS active_supplier_count
WHERE active_supplier_count == 1
RETURN item_number,
       item_name,
       active_supplier_count AS risk_indicator  -- 1 = HIGH risk (single source)
ORDER BY item_number
LIMIT 50;
```

---

### Query 3: Find Expiring Qualifications (30-day Alert) (查找30天内到期的资质)

**Business Context**: The compliance team needs to proactively renew supplier qualifications before they expire, avoiding operational disruptions.

```ngql
-- Find supplier qualifications expiring within 30 days
-- These need immediate renewal action
MATCH (s:Supplier)-[:HAS_QUALIFICATION]->(q:SupplierQualification)
WHERE q.SupplierQualification.status == "VALID"
  AND q.SupplierQualification.expiry_date >= now()
  AND q.SupplierQualification.expiry_date <= datetime_add(now(), INTERVAL 30 DAY)
RETURN s.Supplier.supplier_number AS supplier_number,
       s.Supplier.supplier_name AS supplier_name,
       q.SupplierQualification.qualification_type AS qualification_type,
       q.SupplierQualification.qualification_id AS qualification_id,
       q.SupplierQualification.expiry_date AS expiry_date,
       q.SupplierQualification.issuing_body AS issuing_body,
       -- Calculate days until expiry for prioritization
       datetime_diff(q.SupplierQualification.expiry_date, now()) / 86400 AS days_until_expiry
ORDER BY days_until_expiry ASC  -- Most urgent first
LIMIT 100;
```

---

### Query 4: Supplier Concentration Analysis (供应商集中度分析)

**Business Context**: Finance and procurement leadership need to understand spend distribution across suppliers to assess concentration risk.

```ngql
-- Calculate each supplier's share of total PO spend
-- Flag suppliers exceeding 30% concentration threshold
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s:Supplier)
WHERE po.PurchaseOrder.status IN ["APPROVED", "OPEN", "CLOSED"]
  AND s.Supplier.status == "ACTIVE"
  AND po.PurchaseOrder.order_date >= datetime_add(now(), INTERVAL -365 DAY)
WITH s.Supplier.supplier_number AS supplier_number,
     s.Supplier.supplier_name AS supplier_name,
     sum(po.PurchaseOrder.total_amount) AS total_po_amount
WITH collect({supplier_number: supplier_number, supplier_name: supplier_name, total_amount: total_po_amount}) AS all_suppliers,
     sum(total_po_amount) AS grand_total
UNWIND all_suppliers AS sp
WITH sp.supplier_number AS supplier_number,
     sp.supplier_name AS supplier_name,
     sp.total_amount AS total_amount,
     grand_total,
     (sp.total_amount / grand_total * 100) AS concentration_pct
WHERE concentration_pct > 30  -- Concentration risk threshold
RETURN supplier_number,
       supplier_name,
       total_amount,
       concentration_pct,
       CASE
         WHEN concentration_pct > 50 THEN "CRITICAL"
         WHEN concentration_pct > 30 THEN "HIGH"
       END AS risk_level
ORDER BY concentration_pct DESC;
```

---

### Query 5: Blocked Supplier PO Detection (冻结供应商订单检测)

**Business Context**: Internal audit needs to detect any POs placed with BLOCKED suppliers, which is a compliance violation.

```ngql
-- Find any POs that were placed with BLOCKED suppliers
-- This is a CRITICAL compliance violation
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s:Supplier)
WHERE s.Supplier.status == "BLOCKED"
  AND po.PurchaseOrder.status IN ["DRAFT", "APPROVED", "OPEN"]
RETURN po.PurchaseOrder.po_number AS po_number,
       po.PurchaseOrder.order_date AS order_date,
       po.PurchaseOrder.total_amount AS po_amount,
       s.Supplier.supplier_number AS blocked_supplier_number,
       s.Supplier.supplier_name AS blocked_supplier_name,
       po.PurchaseOrder.buyer AS buyer
ORDER BY po.PurchaseOrder.order_date DESC
LIMIT 50;
```

---

### Query 6: Supplier Performance Analysis (供应商绩效分析)

**Business Context**: Procurement manager wants to evaluate supplier on-time delivery performance by comparing PO promised dates vs Receipt actual dates.

```ngql
-- Analyze delivery performance for a specific supplier
-- Calculate average delay and on-time delivery rate
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s:Supplier),
      (po)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine),
      (po)-[:HAS_RECEIPT]->(r:Receipt)-[:HAS_RECEIPT_LINE]->(rl:ReceiptLine)
WHERE s.Supplier.supplier_number == "V001234"
  AND po.PurchaseOrder.status IN ["CLOSED"]
  AND pol.PurchaseOrderLine.line_type == "GOODS"
WITH po.PurchaseOrder.po_number AS po_number,
     po.PurchaseOrder.order_date AS order_date,
     pol.PurchaseOrderLine.need_by_date AS promised_date,
     r.Receipt.receipt_date AS actual_receipt_date,
     rl.ReceiptLine.received_quantity AS received_qty,
     pol.PurchaseOrderLine.quantity AS ordered_qty,
     -- Calculate if delivery was on time (actual <= promised)
     CASE
       WHEN r.Receipt.receipt_date <= pol.PurchaseOrderLine.need_by_date THEN "ON_TIME"
       ELSE "LATE"
     END AS delivery_status,
     -- Calculate delay in days (positive = late, negative = early)
     datetime_diff(r.Receipt.receipt_date, pol.PurchaseOrderLine.need_by_date) / 86400 AS delay_days
RETURN delivery_status,
       count(*) AS order_count,
       avg(delay_days) AS avg_delay_days,
       sum(received_qty) AS total_received_qty
ORDER BY delivery_status;
```

---

### Query 7: Supplier Qualification Compliance Check (供应商资质合规检查)

**Business Context**: Before creating a PO for a regulated item (e.g., food, pharmaceuticals), verify that the supplier has required certifications.

```ngql
-- Check if a supplier has all required qualifications for a specific item category
-- Example: Item category "RAW_MATERIAL_FOOD" requires SAFETY + ENVIRONMENTAL certifications
MATCH (s:Supplier)-[:HAS_QUALIFICATION]->(q:SupplierQualification)
WHERE s.Supplier.supplier_number == "V001234"
  AND q.SupplierQualification.status == "VALID"
  AND q.SupplierQualification.expiry_date >= now()
WITH s.Supplier.supplier_name AS supplier_name,
     collect(DISTINCT q.SupplierQualification.qualification_type) AS held_qualifications
-- Define required qualifications for regulated procurement
WITH supplier_name,
     held_qualifications,
     ["SAFETY", "ENVIRONMENTAL", "ISO9001"] AS required_qualifications
-- Check if all required qualifications are held
WITH supplier_name,
     held_qualifications,
     required_qualifications,
     [rq IN required_qualifications WHERE rq NOT IN held_qualifications] AS missing_qualifications
RETURN supplier_name,
       held_qualifications,
       CASE
         WHEN size(missing_qualifications) == 0 THEN "COMPLIANT"
         ELSE "NON_COMPLIANT"
       END AS compliance_status,
       missing_qualifications;
```

---

## 5. Summary Table — 关系汇总表

| Relationship | Direction | Description |
|--------------|-----------|-------------|
| SUPPLIES_ITEM | Supplier → Item | Approved Supplier List (ASL) — supplier is approved to supply this item |
| HAS_QUALIFICATION | Supplier → SupplierQualification | Supplier holds this certification/accreditation |
| PLACED_WITH | PurchaseOrder → Supplier | PO is with this supplier |
| INVOICED_BY | Invoice → Supplier | Invoice came from this supplier |
| PAID_TO | Payment → Supplier | Payment went to this supplier |
| CONTRACT_WITH | Contract → Supplier | Contract is with this supplier |

---

## 6. Common Filter Patterns — 常用过滤模式

```ngql
-- Filter for only ACTIVE suppliers
s.Supplier.status == "ACTIVE"

-- Filter for only ACTIVE supply relationships
e.SUPPLIES_ITEM.status == "ACTIVE"

-- Filter for valid (non-expired) qualifications
q.SupplierQualification.status == "VALID"
AND q.SupplierQualification.expiry_date >= now()

-- Filter for effective date range
(e.SUPPLIES_ITEM.effective_from IS NULL OR e.SUPPLIES_ITEM.effective_from <= now())
AND (e.SUPPLIES_ITEM.effective_to IS NULL OR e.SUPPLIES_ITEM.effective_to >= now())

-- Priority ordering
ORDER BY e.SUPPLIES_ITEM.priority ASC
```
