# 本体模型 — PTP + OTC 全流程

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：`01-nebula-schema.md`（物理 Schema）

---

## 1. 本体模块化拆分

本体按业务域拆分为 8 个模块，每次 LLM 查询时根据用户问题动态选择相关模块注入 Prompt。

| 模块 | 文件 | 核心实体 |
|------|------|---------|
| 供应商域 | `ontology/supplier.md` | Supplier, SupplierQualification |
| 采购域（PTP） | `ontology/procurement.md` | PR, PO, POLine, Receipt, ReceiptLine |
| 应付域 | `ontology/payable.md` | Invoice, InvoiceLine, Payment, PaymentBatch |
| 应收域（OTC） | `ontology/receivable.md` | SO, SOLine, Shipment, ARInvoice, ARReceipt |
| XLA 会计引擎 | `ontology/xla.md` | XLAEvent, AccountingDistribution |
| 总账 | `ontology/gl.md` | GLAccount, GLJournalEntry, GLJournalLine |
| 主数据 | `ontology/master-data.md` | Item, BOM, Organization, Employee, Warehouse, Currency, UOM |
| 业务约束 | `ontology/constraints.md` | 三单匹配、时序规则、金额校验 |

---

## 2. 供应商域 (`ontology/supplier.md`)

### 2.1 实体

**Supplier（供应商）**
- 核心属性：supplier_number（唯一标识）, supplier_name, supplier_type, status, country, payment_terms, credit_rating
- 业务含义：提供商品或服务的外部组织

**SupplierQualification（供应商资质）**
- 核心属性：qualification_type, status, expiry_date, issuing_body
- 业务含义：供应商持有的认证或资质（ISO9001, 环保认证等）

### 2.2 关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `SUPPLIES_ITEM` | Supplier → Item | 供应商可供应的物料（ASL 认证供应商清单） |
| `HAS_QUALIFICATION` | Supplier → SupplierQualification | 供应商持有的资质 |
| `PLACED_WITH` | PurchaseOrder → Supplier | 向供应商下达采购订单 |
| `INVOICED_BY` | Invoice → Supplier | 发票开具方 |
| `PAID_TO` | Payment → Supplier | 付款收款方 |
| `CONTRACT_WITH` | Contract → Supplier | 合同签约方 |

### 2.3 隐含业务规则

1. **唯一供应商风险**：若某物料只有 1 个 ACTIVE 状态的供应商，存在断供风险
2. **资质到期预警**：qualification.expiry_date 临近时应告警
3. **供应商集中度**：同一供应商的 PO 金额占比过高（>30%）视为集中度风险
4. **黑名单供应商**：status=BLOCKED 的供应商不应有新的 PO

### 2.4 典型 nGQL 查询

```ngql
-- 查找某物料的所有合格供应商
MATCH (s:Supplier)-[e:SUPPLIES_ITEM]->(i:Item)
WHERE i.Item.item_number == "ITEM-001"
  AND e.status == "ACTIVE"
  AND s.Supplier.status == "ACTIVE"
RETURN s.Supplier.supplier_number AS supplier,
       s.Supplier.supplier_name AS name,
       e.unit_price AS price,
       e.lead_time_days AS lead_time
ORDER BY e.priority ASC;

-- 查找仅有单一供应商的物料（断供风险）
MATCH (s:Supplier)-[e:SUPPLIES_ITEM]->(i:Item)
WHERE e.status == "ACTIVE" AND s.Supplier.status == "ACTIVE"
WITH i, count(s) AS supplier_count
WHERE supplier_count == 1
RETURN i.Item.item_number, i.Item.item_name;

-- 查找即将到期的供应商资质（30天内）
MATCH (s:Supplier)-[:HAS_QUALIFICATION]->(q:SupplierQualification)
WHERE q.SupplierQualification.expiry_date <= datetime_add(now(), INTERVAL 30 DAY)
  AND q.SupplierQualification.status == "VALID"
RETURN s.Supplier.supplier_name, q.SupplierQualification.qualification_type,
       q.SupplierQualification.expiry_date;
```

---

## 3. 采购域 (`ontology/procurement.md`)

### 3.1 实体

**PurchaseRequisition（采购申请）**
- 核心属性：pr_number, status, requester, request_date, need_by_date, total_amount
- 业务含义：内部需求方提出的采购需求

**PurchaseRequisitionLine（采购申请行）**
- 核心属性：line_number, quantity, unit_price, amount

**PurchaseOrder（采购订单）**
- 核心属性：po_number, po_type, status, buyer, order_date, total_amount, currency, payment_terms
- 业务含义：向供应商正式下达的采购指令
- 状态流转：`DRAFT → APPROVED → OPEN → CLOSED`（或 `CANCELLED`）

**PurchaseOrderLine（采购订单行）**
- 核心属性：line_number, quantity, unit_price, amount, received_quantity, invoiced_quantity

**Receipt（收货单）**
- 核心属性：receipt_number, receipt_date, status, receiver
- 业务含义：确认实际收到货物

**ReceiptLine（收货行）**
- 核心属性：received_quantity, accepted_quantity, rejected_quantity, inspection_status

### 3.2 关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `HAS_PR_LINE` | PR → PRLine | 采购申请包含行 |
| `CONVERTS_TO_PO` | PR → PO | 采购申请转采购订单 |
| `PLACED_WITH` | PO → Supplier | 向供应商下达订单 |
| `HAS_PO_LINE` | PO → POLine | 订单包含行 |
| `ORDERS_ITEM` | POLine → Item | 订购的物料 |
| `ORDERED_BY` | PO → Employee | 采购员 |
| `HAS_RECEIPT` | PO → Receipt | 对应收货单 |
| `HAS_RECEIPT_LINE` | Receipt → ReceiptLine | 收货行 |
| `RECEIVED_AT` | Receipt → Warehouse | 入库仓库 |
| `UNDER_CONTRACT` | PO → Contract | 基于合同 |

### 3.3 隐含业务规则

1. **PTP 时序约束**：PR.request_date ≤ PO.order_date ≤ Receipt.receipt_date ≤ Invoice.invoice_date ≤ Payment.payment_date
2. **数量匹配**：Receipt.received_quantity 应 ≤ POLine.quantity × 1.1（允许 10% 超收）
3. **状态依赖**：PO 必须 APPROVED 后才能有 Receipt；Receipt 必须 RECEIVED 后才能有 Invoice
4. **金额一致性**：POLine.amount = POLine.quantity × POLine.unit_price
5. **采购申请转化**：一个 PR 可转化为多个 PO（拆单），一个 PO 可来自多个 PR（合单）

### 3.4 典型 nGQL 查询

```ngql
-- 查找某供应商的所有采购订单
MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s:Supplier)
WHERE s.Supplier.supplier_number == "V001234"
RETURN po.PurchaseOrder.po_number, po.PurchaseOrder.order_date,
       po.PurchaseOrder.total_amount, po.PurchaseOrder.status
ORDER BY po.PurchaseOrder.order_date DESC;

-- PO 完整生命周期追溯（PR → PO → Receipt → Invoice → Payment）
MATCH (pr:PurchaseRequisition)-[:CONVERTS_TO_PO]->(po:PurchaseOrder)
WHERE po.PurchaseOrder.po_number == "PO-2026-0001"
OPTIONAL MATCH (po)-[:HAS_RECEIPT]->(r:Receipt)
OPTIONAL MATCH (po)-[:HAS_INVOICE]->(inv:Invoice)
OPTIONAL MATCH (pay:Payment)-[:PAYS_INVOICE]->(inv)
RETURN pr.PurchaseRequisition.pr_number AS pr,
       po.PurchaseOrder.po_number AS po,
       r.Receipt.receipt_number AS receipt,
       inv.Invoice.invoice_number AS invoice,
       pay.Payment.payment_number AS payment;

-- 超收异常检测
MATCH (po:PurchaseOrder)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine),
      (po)-[:HAS_RECEIPT]->(r:Receipt)-[:HAS_RECEIPT_LINE]->(rl:ReceiptLine)
WHERE rl.ReceiptLine.received_quantity > pol.PurchaseOrderLine.quantity * 1.1
RETURN po.PurchaseOrder.po_number,
       pol.PurchaseOrderLine.quantity AS ordered,
       rl.ReceiptLine.received_quantity AS received;
```

---

## 4. 应付域 (`ontology/payable.md`)

### 4.1 实体

**Invoice（应付发票）**
- 核心属性：invoice_number, invoice_type, invoice_date, due_date, status, total_amount, tax_amount, currency
- 状态流转：`DRAFT → VALIDATED → APPROVED → PAID`

**InvoiceLine（发票行）**
- 核心属性：line_number, line_type, quantity, unit_price, amount, tax_code, tax_rate

**Payment（付款）**
- 核心属性：payment_number, payment_type, payment_date, amount, currency, status
- 状态流转：`CREATED → CONFIRMED → CLEARED → RECONCILED`

**PaymentBatch（付款批次）**
- 核心属性：batch_number, batch_date, total_amount, payment_count

### 4.2 关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `HAS_INVOICE` | PO → Invoice | 三单匹配（PO-Receipt-Invoice） |
| `HAS_INVOICE_LINE` | Invoice → InvoiceLine | 发票行 |
| `INVOICED_BY` | Invoice → Supplier | 开票供应商 |
| `PAYS_INVOICE` | Payment → Invoice | 付款对应发票 |
| `PAID_TO` | Payment → Supplier | 收款方 |
| `CONTAINS_PAYMENT` | PaymentBatch → Payment | 批次包含的付款 |

### 4.3 隐含业务规则

1. **三单匹配（Three-Way Match）**：PO 金额 ≈ Receipt 数量×单价 ≈ Invoice 金额，偏差>10% 视为异常
2. **提前付款检测**：Payment.payment_date < Invoice.due_date 且差值>30天可能是异常
3. **重复发票检测**：同一供应商、相同金额、相近日期（±3天）的多张发票
4. **付款金额校验**：Payment.amount 应 ≤ Invoice.total_amount（不应超付）

### 4.4 典型 nGQL 查询

```ngql
-- 三单匹配异常检测（PO vs Invoice 金额偏差 >10%）
MATCH (po:PurchaseOrder)-[e:HAS_INVOICE]->(inv:Invoice)
WHERE abs(po.PurchaseOrder.total_amount - inv.Invoice.total_amount)
      / po.PurchaseOrder.total_amount > 0.1
RETURN po.PurchaseOrder.po_number,
       po.PurchaseOrder.total_amount AS po_amount,
       inv.Invoice.total_amount AS inv_amount,
       abs(po.PurchaseOrder.total_amount - inv.Invoice.total_amount)
         / po.PurchaseOrder.total_amount AS deviation_rate;

-- 重复发票检测
MATCH (inv1:Invoice)-[:INVOICED_BY]->(s:Supplier)<-[:INVOICED_BY]-(inv2:Invoice)
WHERE id(inv1) < id(inv2)
  AND inv1.Invoice.total_amount == inv2.Invoice.total_amount
  AND abs(datetime_diff(inv1.Invoice.invoice_date, inv2.Invoice.invoice_date)) <= 3 * 86400
RETURN s.Supplier.supplier_name, inv1.Invoice.invoice_number, inv2.Invoice.invoice_number,
       inv1.Invoice.total_amount, inv1.Invoice.invoice_date, inv2.Invoice.invoice_date;

-- 超期未付发票
MATCH (inv:Invoice)
WHERE inv.Invoice.status == "APPROVED"
  AND inv.Invoice.due_date < now()
  AND NOT (inv)<-[:PAYS_INVOICE]-(:Payment)
RETURN inv.Invoice.invoice_number, inv.Invoice.total_amount,
       inv.Invoice.due_date;
```

---

## 5. 应收域 (`ontology/receivable.md`)

### 5.1 实体

**SalesOrder（销售订单）**
- 核心属性：so_number, order_type, order_date, status, total_amount, currency, salesperson
- 状态流转：`DRAFT → BOOKED → SHIPPED → INVOICED → CLOSED`

**SalesOrderLine（销售订单行）**
- 核心属性：line_number, quantity, unit_price, amount, shipped_quantity, invoiced_quantity

**Shipment（发货单）**
- 核心属性：shipment_number, shipment_date, status, carrier, tracking_number

**ARInvoice（应收发票）**
- 核心属性：invoice_number, invoice_type, invoice_date, due_date, status, total_amount

**ARReceipt（应收收款）**
- 核心属性：receipt_number, receipt_date, amount, status, payment_method

### 5.2 关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `SOLD_TO` | SO → Customer | 客户 |
| `HAS_SO_LINE` | SO → SOLine | 订单行 |
| `SELLS_ITEM` | SOLine → Item | 销售物料 |
| `HAS_SHIPMENT` | SO → Shipment | 发货 |
| `HAS_SHIPMENT_LINE` | Shipment → ShipmentLine | 发货行 |
| `SHIPPED_FROM` | Shipment → Warehouse | 出库仓库 |
| `HAS_AR_INVOICE` | SO → ARInvoice | 应收发票 |
| `RECEIVED_FROM` | ARReceipt → Customer | 收款来源 |
| `APPLIES_TO` | ARReceipt → ARInvoice | 收款核销发票 |

### 5.3 隐含业务规则

1. **OTC 时序约束**：SO.order_date ≤ Shipment.shipment_date ≤ ARInvoice.invoice_date ≤ ARReceipt.receipt_date
2. **发货数量约束**：Shipment 累计发货量 ≤ SOLine.quantity
3. **信用额度**：Customer.credit_limit 应 ≥ 该客户所有未收款 ARInvoice 总额
4. **收款核销**：ARReceipt.amount 的 APPLIES_TO 总额应 = ARReceipt.amount

### 5.4 典型 nGQL 查询

```ngql
-- 客户订单及发货状态
MATCH (so:SalesOrder)-[:SOLD_TO]->(c:Customer)
WHERE c.Customer.customer_number == "C001"
OPTIONAL MATCH (so)-[:HAS_SHIPMENT]->(ship:Shipment)
RETURN so.SalesOrder.so_number, so.SalesOrder.status,
       so.SalesOrder.total_amount,
       ship.Shipment.shipment_number, ship.Shipment.status;

-- 客户应收账龄分析
MATCH (inv:ARInvoice)<-[:HAS_AR_INVOICE]-(so:SalesOrder)-[:SOLD_TO]->(c:Customer)
WHERE inv.ARInvoice.status IN ["COMPLETE"]
  AND NOT (inv)<-[:APPLIES_TO]-(:ARReceipt)
RETURN c.Customer.customer_name,
       inv.ARInvoice.invoice_number,
       inv.ARInvoice.total_amount,
       inv.ARInvoice.due_date,
       datetime_diff(now(), inv.ARInvoice.due_date) / 86400 AS overdue_days
ORDER BY overdue_days DESC;
```

---

## 6. XLA 会计引擎 (`ontology/xla.md`)

### 6.1 实体

**XLAEvent（会计事件）**
- 核心属性：event_id, event_class, event_type, event_date, accounting_date, status, source_doc_type, source_doc_id
- 业务含义：将业务事件（采购/收货/开票等）转化为会计分录的桥梁

**AccountingDistribution（会计分配）**
- 核心属性：distribution_id, debit_amount, credit_amount, accounting_class, posted_flag

### 6.2 关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `ACCOUNTING_FOR` | XLAEvent → Source Doc | 会计事件对应源单据 |
| `DISTRIBUTED_TO` | AccountingDistribution → GLAccount | 分配到科目 |

### 6.3 隐含业务规则

1. **借贷平衡**：每笔 XLAEvent 的 distribution.debit_amount 总和 = credit_amount 总和
2. **事件完整性**：每笔 PO/Receipt/Invoice/Payment 都应有对应的 XLAEvent
3. **不可逆记账**：FINAL 状态的 XLAEvent 不可修改，只能通过反向 REVERSE 事件冲销

### 6.4 典型 nGQL 查询

```ngql
-- 追踪某 PO 的完整会计处理链
MATCH (xe:XLAEvent)-[:ACCOUNTING_FOR]->(po:PurchaseOrder)
WHERE po.PurchaseOrder.po_number == "PO-2026-0001"
RETURN xe.XLAEvent.event_class, xe.XLAEvent.event_type,
       xe.XLAEvent.event_date, xe.XLAEvent.status;
```

---

## 7. 总账 (`ontology/gl.md`)

### 7.1 实体

**GLAccount（总账科目）**
- 核心属性：account_code, account_name, account_type, parent_account, level, is_leaf

**GLJournalEntry（日记账分录）**
- 核心属性：journal_number, journal_source, period_name, gl_date, status, total_debit, total_credit

**GLJournalLine（日记账行）**
- 核心属性：line_number, debit_amount, credit_amount, description, reference

### 7.2 关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `HAS_JOURNAL_LINE` | GLJournalEntry → GLJournalLine | 日记账行 |
| `POSTED_TO` | GLJournalLine → GLAccount | 记入科目 |

### 7.3 隐含业务规则

1. **借贷平衡**：GLJournalEntry.total_debit = GLJournalEntry.total_credit
2. **期间关闭**：已关闭期间（CLOSED period）不允许新增分录
3. **科目层级**：非叶子科目（is_leaf=false）不应直接有分录

### 7.4 典型 nGQL 查询

```ngql
-- 查看某期间某科目的借贷发生额
MATCH (jl:GLJournalLine)-[:POSTED_TO]->(acct:GLAccount),
      (je:GLJournalEntry)-[:HAS_JOURNAL_LINE]->(jl)
WHERE acct.GLAccount.account_code == "6001"
  AND je.GLJournalEntry.period_name == "2026-03"
  AND je.GLJournalEntry.status == "POSTED"
RETURN sum(jl.GLJournalLine.debit_amount) AS total_debit,
       sum(jl.GLJournalLine.credit_amount) AS total_credit;

-- 从会计分录追溯到源单据
MATCH (jl:GLJournalLine)-[:POSTED_TO]->(acct:GLAccount)
WHERE acct.GLAccount.account_code == "2201"
  AND jl.GLJournalLine.reference IS NOT NULL
RETURN jl.GLJournalLine.reference AS source_doc,
       jl.GLJournalLine.debit_amount,
       jl.GLJournalLine.credit_amount;
```

---

## 8. 主数据 (`ontology/master-data.md`)

### 8.1 实体

**Item（物料）**
- 核心属性：item_number, item_name, item_type, category, uom, standard_cost, list_price, lead_time_days, safety_stock, abc_class
- 关键分类：RAW_MATERIAL / FINISHED_GOOD / SEMI_FINISHED / SERVICE / EXPENSE

**BOM（物料清单）+ BOMComponent**
- BOM 表达父子物料关系：父物料 ← BOM_FOR ← BOM，BOM ← USES_COMPONENT → 子物料
- 多层 BOM 展开：通过递归遍历 USES_COMPONENT 边

**Organization（组织）**
- 核心属性：org_code, org_name, org_type, parent_org_code, legal_entity, country, status
- 层级结构：COMPANY → BUSINESS_UNIT → DEPARTMENT → COST_CENTER
- 通过 PARENT_ORG 边表达层级
- 业务规则：所有交易数据必须归属到某个 Organization（通过 org_id 字段）

**Employee（员工）**
- 核心属性：employee_number, employee_name, position, department, email, manager_id, status
- 关联：BELONGS_TO_ORG → Organization, ORDERED_BY ← PurchaseOrder, APPROVED_BY ← ApprovalRecord
- 业务规则：采购员只能在其所属组织范围内创建 PO

**ApprovalRecord（审批记录）**
- 核心属性：approval_id, doc_type, doc_number, approval_action, approver, approval_date, approval_level
- 关联：APPROVAL_FOR → 源单据（PR/PO/Invoice/Payment/SO），APPROVED_BY → Employee
- 业务规则：审批链必须完整（每级审批都有记录），高金额 PO 需要多级审批
- 审批状态：SUBMIT → APPROVE / REJECT / RETURN

**Contract（合同）**
- 核心属性：contract_number, contract_type, contract_name, status, start_date, end_date, total_amount
- 关联：CONTRACT_WITH → Supplier/Customer，UNDER_CONTRACT ← PurchaseOrder
- 业务规则：合同到期（end_date < now()）后不应有新的 PO 引用该合同

**Warehouse（仓库）**
- 类型：MAIN / SUB / TRANSIT / RETURN

### 8.2 典型 nGQL 查询

```ngql
-- BOM 展开（2层）
MATCH (parent:Item)<-[:BOM_FOR]-(bom:BOM),
      (bc:BOMComponent)-[:USES_COMPONENT]->(child:Item)
WHERE parent.Item.item_number == "FG-001"
RETURN parent.Item.item_name AS parent_item,
       child.Item.item_number AS component,
       child.Item.item_name AS component_name,
       bc.BOMComponent.quantity_per AS qty_per;

-- 断供影响链分析（某供应商断供影响哪些成品）
MATCH (s:Supplier)-[:SUPPLIES_ITEM]->(raw:Item)
WHERE s.Supplier.supplier_number == "V001234"
MATCH (raw)<-[:USES_COMPONENT]-(:BOMComponent)<--(bom:BOM)-[:BOM_FOR]->(fg:Item)
WHERE fg.Item.item_type == "FINISHED_GOOD"
RETURN DISTINCT fg.Item.item_number, fg.Item.item_name,
       raw.Item.item_number AS affected_material;
```

---

## 9. 业务约束 (`ontology/constraints.md`)

### 9.1 三单匹配规则

```
三单匹配 (Three-Way Match):
  PO (采购订单) ↔ Receipt (收货单) ↔ Invoice (发票)

匹配规则:
  1. 数量匹配: |Receipt.quantity - PO.quantity| / PO.quantity ≤ 5%
  2. 金额匹配: |Invoice.amount - PO.amount| / PO.amount ≤ 10%
  3. 价格匹配: Invoice.unit_price == PO.unit_price (严格)
  4. 供应商一致: PO.supplier == Invoice.supplier == Receipt 对应的 PO.supplier

异常等级:
  - WARNING: 偏差 5-10%
  - ALERT: 偏差 10-20%
  - CRITICAL: 偏差 >20% 或供应商不一致
```

### 9.2 时序约束

```
PTP 流程时序:
  PR.request_date ≤ PO.order_date ≤ Receipt.receipt_date
  ≤ Invoice.invoice_date ≤ Payment.payment_date

OTC 流程时序:
  SO.order_date ≤ Shipment.shipment_date
  ≤ ARInvoice.invoice_date ≤ ARReceipt.receipt_date

违规检测:
  - 收货日期早于下单日期 → 可能虚假交易
  - 发票日期早于收货日期 → 提前开票异常
  - 付款日期早于发票日期 → 提前付款异常
```

### 9.3 金额约束

```
PO 金额完整性:
  PO.total_amount = SUM(POLine.amount)
  POLine.amount = POLine.quantity × POLine.unit_price

Invoice 金额完整性:
  Invoice.total_amount = SUM(InvoiceLine.amount) + Invoice.tax_amount

Payment 约束:
  Payment.amount ≤ Invoice.total_amount (不应超付)
  SUM(Payment for Invoice) = Invoice.total_amount (全额支付)
```

### 9.4 循环交易检测模式

```ngql
-- 循环交易模式: 供应商A的PO → 供应商B的PO → 供应商C的PO → 回到供应商A
-- 即: A 向 B 采购, B 向 C 采购, C 向 A 采购（循环资金流向）
MATCH (s1:Supplier)<-[:PLACED_WITH]-(po1:PurchaseOrder),
      (po1)-[:ORDERED_BY]->(:Employee)<-[:ORDERED_BY]-(po2:PurchaseOrder),
      (s2:Supplier)<-[:PLACED_WITH]-(po2),
      (po2)-[:ORDERED_BY]->(:Employee)<-[:ORDERED_BY]-(po3:PurchaseOrder),
      (s3:Supplier)<-[:PLACED_WITH]-(po3)
WHERE s1 != s2 AND s2 != s3 AND s1 != s3
  AND s1.Supplier.supplier_number IN [s3.Supplier.supplier_number]
RETURN s1.Supplier.supplier_name AS supplier_a,
       s2.Supplier.supplier_name AS supplier_b,
       s3.Supplier.supplier_name AS supplier_c,
       po1.PurchaseOrder.po_number AS po_a_to_b,
       po2.PurchaseOrder.po_number AS po_b_to_c,
       po3.PurchaseOrder.po_number AS po_c_to_a
LIMIT 100;

-- 简化版: 查找与同一供应商有双向交易的情况（既买又卖）
-- 注意: 完整的循环交易检测需要结合 PAID_TO/INVOICED_BY 等资金流向边
-- 此处为示意，Phase 2 虚假交易检测将实现更精确的图模式匹配
```

---

## 10. 本体 Prompt 注入策略

### 10.1 Phase 1 方案：全量注入

Phase 1 采用全量注入策略（与 Phase 0 一致）：

```
System Prompt 结构:
  1. [角色指令] — 你是 ERP 知识图谱查询助手，只生成 nGQL 查询
  2. [Schema 信息] — NebulaGraph 的 Tag / Edge Type 列表及属性
  3. [本体信息] — 业务实体定义、关系、隐含规则
  4. [约束信息] — 三单匹配规则、时序约束
  5. [nGQL 语法指南] — 关键语法差异提醒（属性访问需加 Tag 前缀等）
  6. [用户问题] — 用户的自然语言查询
```

估算 token 消耗：
- Schema 信息：~2000 tokens
- 本体信息（全量）：~3000 tokens
- 约束+语法：~1000 tokens
- 总计 Prompt 模板：~6000 tokens

### 10.2 Phase 2 过渡方案：动态选择

Phase 2 引入 Milvus 向量检索实现动态本体选择：

```
1. 将每个本体模块片段向量化存储到 Milvus
2. 用户提问时，先通过向量相似度找到最相关的 2-3 个本体模块
3. 仅注入相关模块到 Prompt，节省 token

预期收益:
  - Prompt token 从 ~6000 降至 ~3000
  - 减少无关信息对 LLM 的干扰
  - 支持本体规模持续增长
```

---

## 11. Neo4j Cypher → NebulaGraph nGQL 迁移指南

### 11.1 属性访问（最关键）

```
Neo4j:   n.name
nGQL:    n.Person.name  (必须加 Tag 前缀)

Neo4j:   WHERE n.status = 'ACTIVE'
nGQL:    WHERE n.Supplier.status == "ACTIVE"  (双等号, 双引号)
```

### 11.2 节点创建

```
Neo4j:   CREATE (n:Supplier {name: 'ABC'})
nGQL:    INSERT VERTEX Supplier(supplier_name) VALUES "SUP:V001":("ABC")
         -- 必须指定 VID
```

### 11.3 关系创建

```
Neo4j:   MATCH (a:PO {id:'PO-001'}), (b:Supplier {id:'V001'})
         CREATE (a)-[:PLACED_WITH]->(b)

nGQL:    INSERT EDGE PLACED_WITH(order_date)
         VALUES "PO:PO-001"->"SUP:V001":(datetime("2026-04-01"))
```

### 11.4 MERGE 替代

```
Neo4j:   MERGE (n:Supplier {id: 'V001'}) SET n.name = 'ABC'

nGQL:    UPSERT VERTEX ON Supplier "SUP:V001"
         SET supplier_name = "ABC"
         WHEN supplier_number == "V001"
```

### 11.5 分页

```
Neo4j:   SKIP 10 LIMIT 20
nGQL:    LIMIT 20 OFFSET 10  (SKIP 改为 OFFSET)
```

### 11.6 聚合函数

```
-- 基本兼容: count(), sum(), avg(), min(), max(), collect()
-- 注意: NebulaGraph 的 collect() 返回 LIST 类型
```

### 11.7 路径查询

```
Neo4j:   MATCH p = shortestPath((a)-[*..5]-(b))
nGQL:    FIND SHORTEST PATH FROM "id_a" TO "id_b" OVER * BIDIRECT UPTO 5 STEPS
         -- 语法完全不同
```

### 11.8 常见陷阱清单

| 陷阱 | 说明 | 解决方案 |
|------|------|---------|
| 忘记 Tag 前缀 | `n.name` → 报错 | 始终用 `n.TagName.property` |
| 单等号 | `==` 才是比较 | `=` 在 nGQL 中是赋值 |
| 字符串引号 | nGQL 推荐双引号 | 统一使用双引号 |
| VID 类型 | FIXED_STRING 需引号包裹 | VID 值始终加引号 `"SUP:V001"` |
| NULL 比较 | `IS NULL` / `IS NOT NULL` | 与 Neo4j 一致，但需加 Tag 前缀 |
| LIMIT 位置 | 必须在最后 | 不能放在 WITH 子句中间 |
| 无 MERGE | 不支持 MERGE | 用 UPSERT 替代 |
