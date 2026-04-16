# 本体模型 — PTP + OTC 全流程（增强版）

> 版本：v2.0
> 创建日期：2026-04-04
> 更新日期：2026-04-15
> 依赖：`01-nebula-schema.md`（物理 Schema）
> 参考：Oracle EBS R12.2.2 eTRM（PO/AP/AR/XLA/GL/INV 模块）

---

## 1. 本体模块化拆分

本体按业务域拆分为 **11 个模块**（v1.0 为 8 个），每次 LLM 查询时根据用户问题动态选择相关模块注入 Prompt。

| 模块 | 文件 | 核心实体 | Oracle EBS 源表参考 |
|------|------|---------|-------------------|
| 供应商域 | `ontology/supplier.md` | Supplier, SupplierSite, SupplierQualification | PO_VENDORS, AP_SUPPLIER_SITES_ALL |
| 采购域（PTP） | `ontology/procurement.md` | PR, PRLine, PO, POLine, POShipment, Receipt, ReceiptLine, ReceivingTransaction | PO_HEADERS_ALL, PO_LINES_ALL, PO_LINE_LOCATIONS_ALL, RCV_* |
| 应付域 | `ontology/payable.md` | Invoice, InvoiceLine, InvoiceDistribution, InvoiceHold, Payment, PaymentBatch, PaymentSchedule, ExpenseReport | AP_INVOICES_ALL, AP_INVOICE_DISTRIBUTIONS_ALL, AP_HOLDS_ALL, AP_CHECKS_ALL |
| 应收域（OTC） | `ontology/receivable.md` | SO, SOLine, Shipment, ShipmentLine, ARInvoice, ARInvoiceLine, ARReceipt | OE_ORDER_HEADERS_ALL, RA_CUSTOMER_TRX_ALL, AR_CASH_RECEIPTS_ALL |
| 客户域 | `ontology/customer.md` | Customer, CustomerSite | HZ_PARTIES, HZ_CUST_ACCOUNTS, HZ_CUST_ACCT_SITES_ALL |
| XLA 会计引擎 | `ontology/xla.md` | XLAEvent, XLAJournalEntry, XLAJournalLine, AccountingDistribution, XLADistributionLink | XLA_EVENTS, XLA_AE_HEADERS, XLA_AE_LINES, XLA_DISTRIBUTION_LINKS |
| 总账 | `ontology/gl.md` | Ledger, GLPeriod, GLCodeCombination, GLAccount, GLJournalBatch, GLJournalEntry, GLJournalLine, GLBalance, CurrencyRate | GL_LEDGERS, GL_PERIODS, GL_CODE_COMBINATIONS, GL_JE_*, GL_BALANCES, GL_DAILY_RATES |
| 库存域 | `ontology/inventory.md` | InventoryTransaction, ItemCategory | MTL_MATERIAL_TRANSACTIONS, MTL_CATEGORIES |
| 资金域 | `ontology/cash-mgmt.md` | BankAccount, BankStatement, BankStatementLine | CE_BANK_ACCOUNTS, CE_STATEMENT_HEADERS |
| 主数据 | `ontology/master-data.md` | Item, BOM, BOMComponent, Organization, Employee, Warehouse, Currency, UOM, Contract, ApprovalRecord | MTL_SYSTEM_ITEMS, BOM_*, HR_*, |
| 业务约束 | `ontology/constraints.md` | 三单匹配、时序规则、金额校验、循环交易检测 | — |

**v2.0 新增实体汇总**（共 17 个新增）：

| 新增实体 | 所属域 | Oracle EBS 源表 | 新增理由 |
|---------|--------|----------------|---------|
| SupplierSite | 供应商 | AP_SUPPLIER_SITES_ALL | 付款地址/银行账号按地点区分，反欺诈关键 |
| POShipment | 采购 | PO_LINE_LOCATIONS_ALL | 三单匹配的实际匹配单元 |
| ReceivingTransaction | 采购 | RCV_TRANSACTIONS | 收货事件详细记录（接收/检验/入库） |
| InvoiceDistribution | 应付 | AP_INVOICE_DISTRIBUTIONS_ALL | 发票→GL 科目的分配明细 |
| InvoiceHold | 应付 | AP_HOLDS_ALL | 三单匹配冻结记录 |
| PaymentSchedule | 应付 | AP_PAYMENT_SCHEDULES_ALL | 分期付款/到期日管理 |
| ExpenseReport | 应付 | AP_EXPENSE_REPORTS_ALL | 员工费用报销 |
| CustomerSite | 客户 | HZ_CUST_ACCT_SITES_ALL | 客户收货地址/开票地址 |
| ARInvoiceLine | 应收 | RA_CUSTOMER_TRX_LINES_ALL | 应收发票行明细 |
| XLAJournalEntry | XLA | XLA_AE_HEADERS | 子分类账凭证头 |
| XLAJournalLine | XLA | XLA_AE_LINES | 子分类账凭证行 |
| XLADistributionLink | XLA | XLA_DISTRIBUTION_LINKS | 源单据分配与会计行的链接 |
| Ledger | 总账 | GL_LEDGERS | 多账套管理 |
| GLPeriod | 总账 | GL_PERIOD_STATUSES | 会计期间状态 |
| GLCodeCombination | 总账 | GL_CODE_COMBINATIONS | 科目组合（CCID） |
| GLJournalBatch | 总账 | GL_JE_BATCHES | 日记账批次 |
| GLBalance | 总账 | GL_BALANCES | 科目期间余额 |
| CurrencyRate | 总账 | GL_DAILY_RATES | 汇率 |
| InventoryTransaction | 库存 | MTL_MATERIAL_TRANSACTIONS | 库存事务 |
| ItemCategory | 库存 | MTL_CATEGORIES_B | 物料分类层级 |
| BankAccount | 资金 | CE_BANK_ACCOUNTS | 企业银行账户 |
| BankStatement | 资金 | CE_STATEMENT_HEADERS | 银行对账单 |
| BankStatementLine | 资金 | CE_STATEMENT_LINES | 对账单行 |

---

## 2. 供应商域 (`ontology/supplier.md`)

### 2.1 实体

**Supplier（供应商）**
- Oracle EBS 源表：`PO_VENDORS` / `AP_SUPPLIERS`
- 核心属性：supplier_number（唯一标识）, supplier_name, supplier_type, status, country, payment_terms, credit_rating
- 业务含义：提供商品或服务的外部组织
- supplier_type 枚举：`MANUFACTURER` / `DISTRIBUTOR` / `SERVICE_PROVIDER` / `ONE_TIME`
- status 枚举：`ACTIVE` / `INACTIVE` / `BLOCKED` / `PENDING`

**SupplierSite（供应商地点）** 🆕
- Oracle EBS 源表：`AP_SUPPLIER_SITES_ALL` / `PO_VENDOR_SITES_ALL`
- 核心属性：site_code, site_name, address, city, country, phone, fax, pay_site_flag, purchasing_site_flag, rfq_site_flag, bank_account_name, bank_account_number, bank_name, payment_method, payment_terms, pay_group, org_id
- 业务含义：供应商的物理地点。一个供应商可有多个地点（总部、工厂、仓库），每个地点可独立配置：
  - **采购地点**（purchasing_site_flag=Y）：可向该地点下采购订单
  - **付款地点**（pay_site_flag=Y）：发票和付款关联到该地点
  - **RFQ 地点**（rfq_site_flag=Y）：可发送询价单
- 反欺诈价值：
  - 付款银行账号按地点维护，变更银行账号是常见欺诈手段
  - 同一供应商的不同地点可能有不同付款条件
  - 一次性供应商（ONE_TIME）的地点需重点审计

**SupplierQualification（供应商资质）**
- Oracle EBS 源表：自定义扩展（基于 PO_APPROVED_SUPPLIER_LIST 扩展）
- 核心属性：qualification_type, status, expiry_date, issuing_body, scope
- 业务含义：供应商持有的认证或资质（ISO9001, 环保认证等）

### 2.2 关系

| 关系 | 方向 | 说明 | 新增标记 |
|------|------|------|---------|
| `SUPPLIES_ITEM` | Supplier → Item | 供应商可供应的物料（ASL 认证供应商清单） | |
| `HAS_QUALIFICATION` | Supplier → SupplierQualification | 供应商持有的资质 | |
| `HAS_SUPPLIER_SITE` | Supplier → SupplierSite | 供应商拥有的地点 | 🆕 |
| `PLACED_WITH` | PurchaseOrder → Supplier | 向供应商下达采购订单 | |
| `INVOICED_BY` | Invoice → Supplier | 发票开具方 | |
| `PAID_TO` | Payment → Supplier | 付款收款方 | |
| `PAID_TO_SITE` | Payment → SupplierSite | 付款到供应商的具体地点 | 🆕 |
| `REMIT_TO_SITE` | Invoice → SupplierSite | 发票关联的付款地点 | 🆕 |
| `CONTRACT_WITH` | Contract → Supplier | 合同签约方 | |

### 2.3 隐含业务规则

1. **唯一供应商风险**：若某物料只有 1 个 ACTIVE 状态的供应商，存在断供风险
2. **资质到期预警**：qualification.expiry_date 临近时应告警
3. **供应商集中度**：同一供应商的 PO 金额占比过高（>30%）视为集中度风险
4. **黑名单供应商**：status=BLOCKED 的供应商不应有新的 PO
5. 🆕 **银行账号变更审计**：SupplierSite.bank_account_number 变更需审批记录，变更后首笔大额付款需人工复核
6. 🆕 **一次性供应商控制**：supplier_type=ONE_TIME 且累计 PO 金额 >50万 应升级为正式供应商
7. 🆕 **地点有效性**：PO 关联的 SupplierSite 必须 purchasing_site_flag=Y，Payment 关联的必须 pay_site_flag=Y
8. 🆕 **付款地点与发票地点一致性**：Payment.PAID_TO_SITE 应与 Invoice.REMIT_TO_SITE 一致

### 2.4 典型 nGQL 查询

```ngql
# 查找某物料的所有合格供应商
MATCH (s:Supplier)-[e:SUPPLIES_ITEM]->(i:Item)
WHERE i.Item.item_number == "ITEM-001"
  AND e.status == "ACTIVE"
  AND s.Supplier.status == "ACTIVE"
RETURN s.Supplier.supplier_number AS supplier,
       s.Supplier.supplier_name AS name,
       e.unit_price AS price,
       e.lead_time_days AS lead_time
ORDER BY e.priority ASC;

# 查找仅有单一供应商的物料（断供风险）
MATCH (s:Supplier)-[e:SUPPLIES_ITEM]->(i:Item)
WHERE e.status == "ACTIVE" AND s.Supplier.status == "ACTIVE"
WITH i, count(s) AS supplier_count
WHERE supplier_count == 1
RETURN i.Item.item_number, i.Item.item_name;

# 查找即将到期的供应商资质（30天内）
MATCH (s:Supplier)-[:HAS_QUALIFICATION]->(q:SupplierQualification)
WHERE q.SupplierQualification.expiry_date <= datetime_add(now(), INTERVAL 30 DAY)
  AND q.SupplierQualification.status == "VALID"
RETURN s.Supplier.supplier_name, q.SupplierQualification.qualification_type,
       q.SupplierQualification.expiry_date;

# 🆕 查找银行账号与常用不一致的供应商地点（可能的欺诈）
MATCH (s:Supplier)-[:HAS_SUPPLIER_SITE]->(site:SupplierSite)
WHERE site.SupplierSite.pay_site_flag == "Y"
WITH s, collect(site.SupplierSite.bank_account_number) AS bank_accounts
WHERE size(bank_accounts) > 1
RETURN s.Supplier.supplier_name, bank_accounts;

# 🆕 查找向 BLOCKED 供应商的地点付款的异常（关联黑名单检测）
MATCH (pay:Payment)-[:PAID_TO]->(s:Supplier)
WHERE s.Supplier.status == "BLOCKED"
RETURN s.Supplier.supplier_name, pay.Payment.payment_number,
       pay.Payment.amount, pay.Payment.payment_date;
```

---

## 3. 采购域 (`ontology/procurement.md`)

### 3.1 实体

**PurchaseRequisition（采购申请）**
- Oracle EBS 源表：`PO_REQUISITION_HEADERS_ALL`
- 核心属性：pr_number, status, requester, request_date, need_by_date, total_amount
- 业务含义：内部需求方提出的采购需求
- status 枚举：`DRAFT` / `PENDING_APPROVAL` / `APPROVED` / `REJECTED` / `CLOSED`

**PurchaseRequisitionLine（采购申请行）**
- Oracle EBS 源表：`PO_REQUISITION_LINES_ALL`
- 核心属性：line_number, quantity, unit_price, amount, suggested_vendor

**PurchaseOrder（采购订单）**
- Oracle EBS 源表：`PO_HEADERS_ALL`
- 核心属性：po_number, po_type, status, buyer, order_date, total_amount, currency, payment_terms
- 业务含义：向供应商正式下达的采购指令
- po_type 枚举：`STANDARD`（标准）/ `BLANKET`（一揽子协议）/ `CONTRACT`（合同）/ `PLANNED`（计划）
- status 枚举：`DRAFT → APPROVED → OPEN → CLOSED`（或 `CANCELLED`）
- 🆕 Blanket PO 说明：`po_type=BLANKET` 时，PO 头定义价格协议，实际采购通过 `PO_RELEASES_ALL` 的 Release 下达。Release 的 release_number 标识具体释放单。

**PurchaseOrderLine（采购订单行）**
- Oracle EBS 源表：`PO_LINES_ALL`
- 核心属性：line_number, line_type, quantity, unit_price, amount, received_quantity, invoiced_quantity

**POShipment（采购订单发运计划）** 🆕
- Oracle EBS 源表：`PO_LINE_LOCATIONS_ALL`
- 核心属性：shipment_number, shipment_type, quantity, quantity_received, quantity_billed, quantity_cancelled, need_by_date, promised_date, ship_to_location, receiving_routing, match_option, price_override, amount, status, accrue_on_receipt_flag, inspection_required_flag
- 业务含义：**这是三单匹配的实际匹配单元**。每个 PO Line 可以有多个 Shipment（不同送货日期、不同送货地点、不同数量）。Oracle EBS 的三单匹配（2-Way / 3-Way / 4-Way）都在 Shipment 级别进行。
- match_option 枚举：`P`（PO 匹配）/ `R`（收货匹配）
  - P (Purchase Order): Invoice qty ≤ PO qty（二单匹配）
  - R (Receipt): Invoice qty ≤ Receipt qty（三/四单匹配）
- inspection_required_flag：`Y` 时为四单匹配（PO-Receipt-Inspection-Invoice）
- accrue_on_receipt_flag：`Y` 时收货即计提暂估应付（会计事件触发点）

**Receipt（收货单）**
- Oracle EBS 源表：`RCV_SHIPMENT_HEADERS`
- 核心属性：receipt_number, receipt_type, receipt_date, status, receiver, total_quantity, warehouse

**ReceiptLine（收货行）**
- Oracle EBS 源表：`RCV_SHIPMENT_LINES`
- 核心属性：line_number, received_quantity, accepted_quantity, rejected_quantity, inspection_status, lot_number
- 🆕 新增属性说明：每个 ReceiptLine 关联一个 POShipment（发运计划行），构成三单匹配链的中间环节

**ReceivingTransaction（收货事务）** 🆕
- Oracle EBS 源表：`RCV_TRANSACTIONS`
- 核心属性：transaction_id, transaction_type, transaction_date, quantity, uom, parent_transaction_id, source_doc_type
- 业务含义：记录收货过程中的每一步操作事务。一个 ReceiptLine 可能有多条 ReceivingTransaction，追踪完整的收货流程。
- transaction_type 枚举及流转：
  - `RECEIVE` — 收货入库暂存区
  - `INSPECT` — 质检（可选，四单匹配时必须）
  - `ACCEPT` — 质检合格
  - `REJECT` — 质检不合格
  - `DELIVER` — 交付到最终目的地（仓库/费用科目）
  - `RETURN TO VENDOR` — 退货给供应商
  - `CORRECT` — 数量更正
- parent_transaction_id：形成事务链（RECEIVE → INSPECT → ACCEPT → DELIVER）

### 3.2 关系

| 关系 | 方向 | 说明 | 新增标记 |
|------|------|------|---------|
| `HAS_PR_LINE` | PR → PRLine | 采购申请包含行 | |
| `CONVERTS_TO_PO` | PR → PO | 采购申请转采购订单 | |
| `PLACED_WITH` | PO → Supplier | 向供应商下达订单 | |
| `HAS_PO_LINE` | PO → POLine | 订单包含行 | |
| `HAS_PO_SHIPMENT` | POLine → POShipment | 订单行的发运计划 | 🆕 |
| `ORDERS_ITEM` | POLine → Item | 订购的物料 | |
| `ORDERED_BY` | PO → Employee | 采购员 | |
| `HAS_RECEIPT` | PO → Receipt | 对应收货单 | |
| `HAS_RECEIPT_LINE` | Receipt → ReceiptLine | 收货行 | |
| `RECEIVES_SHIPMENT` | ReceiptLine → POShipment | 收货行对应的 PO 发运计划 | 🆕 |
| `HAS_RCV_TRANSACTION` | ReceiptLine → ReceivingTransaction | 收货事务记录 | 🆕 |
| `RCV_PARENT` | ReceivingTransaction → ReceivingTransaction | 收货事务的父事务链 | 🆕 |
| `RECEIVED_AT` | Receipt → Warehouse | 入库仓库 | |
| `UNDER_CONTRACT` | PO → Contract | 基于合同 | |
| `SHIP_TO_SITE` | POShipment → Organization | 送货到目的组织 | 🆕 |

### 3.3 隐含业务规则

1. **PTP 时序约束**：PR.request_date ≤ PO.order_date ≤ Receipt.receipt_date ≤ Invoice.invoice_date ≤ Payment.payment_date
2. **数量匹配**：ReceiptLine.received_quantity 应 ≤ POShipment.quantity × 1.1（允许 10% 超收）
3. **状态依赖**：PO 必须 APPROVED 后才能有 Receipt；Receipt 必须 RECEIVED 后才能有 Invoice
4. **金额一致性**：POLine.amount = POLine.quantity × POLine.unit_price
5. **采购申请转化**：一个 PR 可转化为多个 PO（拆单），一个 PO 可来自多个 PR（合单）
6. 🆕 **三单匹配层级（Oracle EBS 标准）**：
   - **二单匹配（2-Way）**：Invoice qty/amount ≤ PO qty/amount（POShipment.match_option='P'，无需检查收货）
   - **三单匹配（3-Way）**：Invoice qty ≤ Receipt qty（POShipment.match_option='R'，需要收货确认）
   - **四单匹配（4-Way）**：Invoice qty ≤ Accepted qty（inspection_required_flag='Y'，需要质检通过）
7. 🆕 **收货事务完整性**：RECEIVE → (INSPECT →) ACCEPT/REJECT → DELIVER，每步数量守恒
8. 🆕 **暂估应付**：当 POShipment.accrue_on_receipt_flag='Y' 时，收货时自动计提暂估应付（产生 XLAEvent）
9. 🆕 **Blanket PO 释放控制**：Blanket PO 的累计释放金额不应超过协议总金额

### 3.4 典型 nGQL 查询

```ngql
# PO 完整生命周期追溯（PR → PO → POShipment → Receipt → Invoice → Payment）
MATCH (pr:PurchaseRequisition)-[:CONVERTS_TO_PO]->(po:PurchaseOrder)
WHERE po.PurchaseOrder.po_number == "PO-2026-0001"
OPTIONAL MATCH (po)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine)-[:HAS_PO_SHIPMENT]->(ps:POShipment)
OPTIONAL MATCH (rl:ReceiptLine)-[:RECEIVES_SHIPMENT]->(ps)
OPTIONAL MATCH (r:Receipt)-[:HAS_RECEIPT_LINE]->(rl)
OPTIONAL MATCH (po)-[:HAS_INVOICE]->(inv:Invoice)
OPTIONAL MATCH (pay:Payment)-[:PAYS_INVOICE]->(inv)
RETURN pr.PurchaseRequisition.pr_number AS pr,
       po.PurchaseOrder.po_number AS po,
       ps.POShipment.shipment_number AS shipment,
       r.Receipt.receipt_number AS receipt,
       inv.Invoice.invoice_number AS invoice,
       pay.Payment.payment_number AS payment;

# 🆕 三单匹配异常检测（在 Shipment 级别）
MATCH (pol:PurchaseOrderLine)-[:HAS_PO_SHIPMENT]->(ps:POShipment)
WHERE ps.POShipment.quantity_received > 0
  AND ps.POShipment.quantity_billed > ps.POShipment.quantity_received * 1.05
RETURN pol.PurchaseOrderLine.line_number,
       ps.POShipment.quantity AS ordered,
       ps.POShipment.quantity_received AS received,
       ps.POShipment.quantity_billed AS billed;

# 🆕 收货事务链追踪（检查是否有未完成的收货流程）
MATCH (rl:ReceiptLine)-[:HAS_RCV_TRANSACTION]->(rt:ReceivingTransaction)
WHERE rt.ReceivingTransaction.transaction_type == "RECEIVE"
  AND NOT (rt)<-[:RCV_PARENT]-(:ReceivingTransaction {transaction_type: "DELIVER"})
  AND NOT (rt)<-[:RCV_PARENT]-(:ReceivingTransaction {transaction_type: "RETURN TO VENDOR"})
RETURN rl.ReceiptLine.line_number, rt.ReceivingTransaction.transaction_date,
       rt.ReceivingTransaction.quantity AS stuck_quantity;

# 超收异常检测（基于 POShipment）
MATCH (pol:PurchaseOrderLine)-[:HAS_PO_SHIPMENT]->(ps:POShipment)
WHERE ps.POShipment.quantity_received > ps.POShipment.quantity * 1.1
MATCH (po:PurchaseOrder)-[:HAS_PO_LINE]->(pol)
RETURN po.PurchaseOrder.po_number,
       ps.POShipment.quantity AS ordered,
       ps.POShipment.quantity_received AS received;
```

---

## 4. 应付域 (`ontology/payable.md`)

### 4.1 实体

**Invoice（应付发票）**
- Oracle EBS 源表：`AP_INVOICES_ALL`
- 核心属性：invoice_number, invoice_type, invoice_date, due_date, status, total_amount, tax_amount, currency, payment_method, gl_date, source, pay_group
- 状态流转：`DRAFT → VALIDATED → APPROVED → PAID`（或 `CANCELLED` / `ON_HOLD`）
- 🆕 invoice_type 完整枚举：`STANDARD`（标准发票）/ `CREDIT`（贷项通知单/红字发票）/ `DEBIT`（借项通知单）/ `PREPAYMENT`（预付款发票）/ `MIXED`（混合）/ `EXPENSE REPORT`（费用报销）

**InvoiceLine（发票行）**
- Oracle EBS 源表：`AP_INVOICE_LINES_ALL`
- 核心属性：line_number, line_type, quantity, unit_price, amount, tax_code, tax_rate, description
- line_type 枚举：`ITEM`（物料行）/ `TAX`（税行）/ `FREIGHT`（运费行）/ `MISCELLANEOUS`（杂项）/ `PREPAY`（预付款扣减行）

**InvoiceDistribution（发票分配）** 🆕
- Oracle EBS 源表：`AP_INVOICE_DISTRIBUTIONS_ALL`
- 核心属性：distribution_id, distribution_line_number, line_type, amount, base_amount, accounting_date, accrual_posted_flag, posted_flag, match_status, reversal_flag, parent_reversal_id
- 业务含义：将每个发票行的金额分配到一个或多个 GL 科目组合。这是 AP 模块与 GL 模块的桥梁。
  - 一个 InvoiceLine 可以有多个 Distribution（按比例分摊到不同成本中心/科目）
  - match_status 标识三单匹配结果
  - accrual_posted_flag 标识暂估应付是否已冲销
- 反欺诈价值：
  - 分配到非常规科目（如高管费用科目分配到大额采购发票）
  - reversal_flag=Y 的冲销分配频繁出现

**InvoiceHold（发票冻结）** 🆕
- Oracle EBS 源表：`AP_HOLDS_ALL`
- 核心属性：hold_id, hold_type, hold_reason, hold_date, release_date, release_reason, held_by, released_by, status
- 业务含义：当三单匹配失败或其他校验不通过时，系统自动或人工对发票施加冻结（Hold），阻止付款。
- hold_type 枚举（Oracle EBS 标准）：
  - `PRICE` — 价格不匹配（Invoice 单价 ≠ PO 单价）
  - `QTY REC` — 数量超过收货量（Invoice qty > Receipt qty，三单匹配）
  - `QTY ORD` — 数量超过订购量（Invoice qty > PO qty，二单匹配）
  - `AMT ORD` — 金额超过订购金额
  - `AMT REC` — 金额超过收货金额
  - `VENDOR` — 供应商冻结
  - `TAX AMOUNT RANGE` — 税额超出范围
  - `DIST VARIANCE` — 分配差异
  - `NATURAL ACCOUNT TAX` — 科目税率冲突
  - `MANUAL` — 人工冻结
- 反欺诈价值：**极高**。频繁被冻结又快速释放的发票、大额发票的手动释放、同一审批人大量释放冻结等都是关键审计信号。

**Payment（付款）**
- Oracle EBS 源表：`AP_CHECKS_ALL`（支票/EFT）+ `AP_INVOICE_PAYMENTS_ALL`（发票付款关联）
- 核心属性：payment_number, payment_type, payment_date, amount, currency, status, bank_account, payment_method, check_number
- payment_type 枚举：`CHECK` / `ELECTRONIC` / `WIRE` / `CASH`
- status 枚举：`CREATED → CONFIRMED → CLEARED → RECONCILED`（或 `VOIDED`）

**PaymentBatch（付款批次）**
- Oracle EBS 源表：`AP_PAYMENT_SCHEDULES_ALL`（批次层面）
- 核心属性：batch_number, batch_date, total_amount, payment_count, status

**PaymentSchedule（付款计划）** 🆕
- Oracle EBS 源表：`AP_PAYMENT_SCHEDULES_ALL`
- 核心属性：schedule_id, installment_number, due_date, gross_amount, amount_remaining, payment_status, discount_date, discount_amount_available, second_discount_date, second_discount_amount, third_discount_date, third_discount_amount
- 业务含义：每张发票根据付款条件（NET30/2-10-NET30 等）生成一条或多条付款计划行。
  - 支持分期付款（多期 installment）
  - 支持提前付款折扣（如 2/10 NET30 = 10天内付款享2%折扣）
- 反欺诈价值：
  - 未享受折扣就提前付款 = 可能的资金挪用
  - 超过 due_date 很久才付款 = 供应商管理异常

**ExpenseReport（费用报销）** 🆕
- Oracle EBS 源表：`AP_EXPENSE_REPORTS_ALL`
- 核心属性：report_number, report_date, employee_id, total_amount, currency, status, purpose, submitted_date, approved_date, paid_date
- 业务含义：员工出差或日常费用的报销申请。审批后生成 Invoice（invoice_type='EXPENSE REPORT'）进入应付流程。
- 反欺诈价值：
  - 高频报销、大额报销、周末/节假日报销
  - 拆分报销（将大额拆分为多笔小额绕过审批限额）

### 4.2 关系

| 关系 | 方向 | 说明 | 新增标记 |
|------|------|------|---------|
| `HAS_INVOICE` | PO → Invoice | 三单匹配（PO-Receipt-Invoice） | |
| `HAS_INVOICE_LINE` | Invoice → InvoiceLine | 发票行 | |
| `HAS_INVOICE_DIST` | InvoiceLine → InvoiceDistribution | 发票行的会计分配 | 🆕 |
| `DIST_TO_ACCOUNT` | InvoiceDistribution → GLCodeCombination | 分配到科目组合 | 🆕 |
| `HAS_HOLD` | Invoice → InvoiceHold | 发票上的冻结 | 🆕 |
| `HOLD_RELEASED_BY` | InvoiceHold → Employee | 释放冻结的人 | 🆕 |
| `HAS_PAYMENT_SCHEDULE` | Invoice → PaymentSchedule | 付款计划 | 🆕 |
| `INVOICED_BY` | Invoice → Supplier | 开票供应商 | |
| `REMIT_TO_SITE` | Invoice → SupplierSite | 付款地点 | 🆕 |
| `PAYS_INVOICE` | Payment → Invoice | 付款对应发票 | |
| `PAID_TO` | Payment → Supplier | 收款方 | |
| `PAID_TO_SITE` | Payment → SupplierSite | 收款地点（银行账号） | 🆕 |
| `CONTAINS_PAYMENT` | PaymentBatch → Payment | 批次包含的付款 | |
| `MATCHES_SHIPMENT` | InvoiceLine → POShipment | 发票行匹配到的 PO 发运计划 | 🆕 |
| `EXPENSE_BY` | ExpenseReport → Employee | 报销人 | 🆕 |
| `EXPENSE_TO_INVOICE` | ExpenseReport → Invoice | 报销生成的发票 | 🆕 |

### 4.3 隐含业务规则

1. **三单匹配（Three-Way Match）**：在 POShipment 级别进行
   - 🆕 匹配层级取决于 POShipment.match_option + inspection_required_flag：
     - 2-Way: Invoice ≤ PO（match_option='P'）
     - 3-Way: Invoice ≤ Receipt（match_option='R', inspection='N'）
     - 4-Way: Invoice ≤ Accepted（match_option='R', inspection='Y'）
   - 偏差容忍度（Oracle EBS 标准）：数量 ≤5%, 金额 ≤10%, 价格严格匹配
2. **提前付款检测**：Payment.payment_date < Invoice.due_date 且差值>30天可能是异常
3. **重复发票检测**：同一供应商、相同金额、相近日期（±3天）的多张发票
4. **付款金额校验**：Payment.amount 应 ≤ Invoice.total_amount（不应超付）
5. 🆕 **冻结释放审计**：InvoiceHold.release_date - hold_date < 1天 且金额 >100万 需重点审查
6. 🆕 **分配科目合理性**：InvoiceDistribution 的科目应与 PO 分配科目一致，不一致需说明
7. 🆕 **费用报销拆分检测**：同一 Employee 在 ±3天内提交多张 ExpenseReport 且单张 < 审批限额 但合计 > 限额

### 4.4 典型 nGQL 查询

```ngql
# 三单匹配异常检测（PO vs Invoice 金额偏差 >10%）
MATCH (po:PurchaseOrder)-[e:HAS_INVOICE]->(inv:Invoice)
WHERE abs(po.PurchaseOrder.total_amount - inv.Invoice.total_amount)
      / po.PurchaseOrder.total_amount > 0.1
RETURN po.PurchaseOrder.po_number,
       po.PurchaseOrder.total_amount AS po_amount,
       inv.Invoice.total_amount AS inv_amount;

# 重复发票检测
MATCH (inv1:Invoice)-[:INVOICED_BY]->(s:Supplier)<-[:INVOICED_BY]-(inv2:Invoice)
WHERE id(inv1) < id(inv2)
  AND inv1.Invoice.total_amount == inv2.Invoice.total_amount
  AND abs(datetime_diff(inv1.Invoice.invoice_date, inv2.Invoice.invoice_date)) <= 3 * 86400
RETURN s.Supplier.supplier_name, inv1.Invoice.invoice_number, inv2.Invoice.invoice_number,
       inv1.Invoice.total_amount;

# 超期未付发票
MATCH (inv:Invoice)
WHERE inv.Invoice.status == "APPROVED"
  AND inv.Invoice.due_date < now()
  AND NOT (inv)<-[:PAYS_INVOICE]-(:Payment)
RETURN inv.Invoice.invoice_number, inv.Invoice.total_amount, inv.Invoice.due_date;

# 🆕 频繁冻结释放异常（同一审批人大量释放发票冻结）
MATCH (h:InvoiceHold)-[:HOLD_RELEASED_BY]->(e:Employee)
WHERE h.InvoiceHold.status == "RELEASED"
WITH e, count(h) AS release_count,
     sum(CASE WHEN datetime_diff(h.InvoiceHold.release_date, h.InvoiceHold.hold_date) < 86400 THEN 1 ELSE 0 END) AS quick_releases
WHERE release_count > 20
RETURN e.Employee.employee_name, release_count, quick_releases;

# 🆕 发票分配科目异常检测（分配到非常规科目）
MATCH (inv:Invoice)-[:HAS_INVOICE_LINE]->(il:InvoiceLine)-[:HAS_INVOICE_DIST]->(dist:InvoiceDistribution)-[:DIST_TO_ACCOUNT]->(cc:GLCodeCombination)
WHERE inv.Invoice.total_amount > 1000000
  AND cc.GLCodeCombination.segment3 IN ["6602", "6603"]
RETURN inv.Invoice.invoice_number, inv.Invoice.total_amount,
       cc.GLCodeCombination.concatenated_segments AS account;
```

---

## 5. 应收域 (`ontology/receivable.md`)

### 5.1 实体

**SalesOrder（销售订单）**
- Oracle EBS 源表：`OE_ORDER_HEADERS_ALL`
- 核心属性：so_number, order_type, order_date, status, total_amount, currency, salesperson
- 状态流转：`DRAFT → BOOKED → SHIPPED → INVOICED → CLOSED`

**SalesOrderLine（销售订单行）**
- Oracle EBS 源表：`OE_ORDER_LINES_ALL`
- 核心属性：line_number, quantity, unit_price, amount, shipped_quantity, invoiced_quantity

**Shipment（发货单）**
- Oracle EBS 源表：`WSH_DELIVERY_DETAILS`（发货明细）/ `WSH_NEW_DELIVERIES`（发货头）
- 核心属性：shipment_number, shipment_date, status, carrier, tracking_number

**ShipmentLine（发货行）**
- 核心属性：line_number, shipped_quantity, uom, lot_number, serial_number

**ARInvoice（应收发票）**
- Oracle EBS 源表：`RA_CUSTOMER_TRX_ALL`
- 核心属性：invoice_number, invoice_type, invoice_date, due_date, status, total_amount, tax_amount
- 🆕 invoice_type 枚举：`INV`（标准发票）/ `CM`（贷项通知单/退款）/ `DM`（借项通知单/加收）/ `DEP`（保证金）/ `GUAR`（质保金）

**ARInvoiceLine（应收发票行）** 🆕
- Oracle EBS 源表：`RA_CUSTOMER_TRX_LINES_ALL`
- 核心属性：line_number, line_type, quantity, unit_selling_price, amount, tax_code, tax_rate, description, revenue_amount
- line_type 枚举：`LINE`（标准行）/ `TAX`（税行）/ `FREIGHT`（运费行）
- 业务含义：应收发票的行级明细，之前 v1.0 缺失此实体导致无法做行级收入分析

**ARReceipt（应收收款）**
- Oracle EBS 源表：`AR_CASH_RECEIPTS_ALL`
- 核心属性：receipt_number, receipt_date, amount, status, payment_method

### 5.2 关系

| 关系 | 方向 | 说明 | 新增标记 |
|------|------|------|---------|
| `SOLD_TO` | SO → Customer | 客户 | |
| `HAS_SO_LINE` | SO → SOLine | 订单行 | |
| `SELLS_ITEM` | SOLine → Item | 销售物料 | |
| `HAS_SHIPMENT` | SO → Shipment | 发货 | |
| `HAS_SHIPMENT_LINE` | Shipment → ShipmentLine | 发货行 | |
| `SHIPPED_FROM` | Shipment → Warehouse | 出库仓库 | |
| `HAS_AR_INVOICE` | SO → ARInvoice | 应收发票 | |
| `HAS_AR_INVOICE_LINE` | ARInvoice → ARInvoiceLine | 应收发票行 | 🆕 |
| `AR_LINE_FOR_ITEM` | ARInvoiceLine → Item | 发票行对应的物料 | 🆕 |
| `BILL_TO_SITE` | SO → CustomerSite | 开票地点 | 🆕 |
| `SHIP_TO_SITE` | SO → CustomerSite | 送货地点 | 🆕 |
| `RECEIVED_FROM` | ARReceipt → Customer | 收款来源 | |
| `APPLIES_TO` | ARReceipt → ARInvoice | 收款核销发票 | |

### 5.3 隐含业务规则

1. **OTC 时序约束**：SO.order_date ≤ Shipment.shipment_date ≤ ARInvoice.invoice_date ≤ ARReceipt.receipt_date
2. **发货数量约束**：Shipment 累计发货量 ≤ SOLine.quantity
3. **信用额度**：Customer.credit_limit 应 ≥ 该客户所有未收款 ARInvoice 总额
4. **收款核销**：ARReceipt.amount 的 APPLIES_TO 总额应 = ARReceipt.amount
5. 🆕 **贷项通知单监控**：CM 类型的 ARInvoice 频繁出现在同一客户可能是欺诈退款
6. 🆕 **收入确认完整性**：ARInvoiceLine.revenue_amount 合计应与 ARInvoice.total_amount 一致
7. 🆕 **SHIP_TO 与 BILL_TO 不一致**：正常业务中偶尔发生，但频繁不一致需关注

### 5.4 典型 nGQL 查询

```ngql
# 客户应收账龄分析
MATCH (inv:ARInvoice)<-[:HAS_AR_INVOICE]-(so:SalesOrder)-[:SOLD_TO]->(c:Customer)
WHERE inv.ARInvoice.status IN ["COMPLETE"]
  AND NOT (inv)<-[:APPLIES_TO]-(:ARReceipt)
RETURN c.Customer.customer_name,
       inv.ARInvoice.invoice_number,
       inv.ARInvoice.total_amount,
       inv.ARInvoice.due_date,
       datetime_diff(now(), inv.ARInvoice.due_date) / 86400 AS overdue_days
ORDER BY overdue_days DESC;

# 🆕 贷项通知单异常检测（同客户高频退款）
MATCH (inv:ARInvoice)<-[:HAS_AR_INVOICE]-(so:SalesOrder)-[:SOLD_TO]->(c:Customer)
WHERE inv.ARInvoice.invoice_type == "CM"
WITH c, count(inv) AS cm_count, sum(inv.ARInvoice.total_amount) AS cm_total
WHERE cm_count > 5
RETURN c.Customer.customer_name, cm_count, cm_total
ORDER BY cm_total DESC;

# 🆕 应收发票行级分析
MATCH (inv:ARInvoice)-[:HAS_AR_INVOICE_LINE]->(line:ARInvoiceLine)-[:AR_LINE_FOR_ITEM]->(i:Item)
WHERE inv.ARInvoice.invoice_number == "ARINV-2026-0001"
RETURN line.ARInvoiceLine.line_number,
       i.Item.item_name,
       line.ARInvoiceLine.quantity,
       line.ARInvoiceLine.unit_selling_price,
       line.ARInvoiceLine.amount;
```

---

## 6. 客户域 (`ontology/customer.md`) 🆕

### 6.1 实体

**Customer（客户）**
- Oracle EBS 源表：`HZ_PARTIES` + `HZ_CUST_ACCOUNTS`（TCA 架构）
- 核心属性：customer_number, customer_name, customer_type, status, country, credit_limit, payment_terms, tax_id, sales_region
- 业务含义：Oracle EBS R12 使用 TCA（Trading Community Architecture）模型，Party → Account → Site 三层结构
- customer_type 枚举：`INTERNAL` / `EXTERNAL` / `GOVERNMENT`

**CustomerSite（客户地点）** 🆕
- Oracle EBS 源表：`HZ_CUST_ACCT_SITES_ALL` + `HZ_CUST_SITE_USES_ALL`
- 核心属性：site_number, site_name, address, city, country, site_use_code, primary_flag, status
- site_use_code 枚举：
  - `BILL_TO` — 开票地址（发票寄送地址）
  - `SHIP_TO` — 送货地址
  - `DELIVER_TO` — 最终交付地址
  - `PAYMENT` — 付款地址
- 业务含义：一个客户可有多个地点，每个地点有不同用途。销售订单的 ship_to 和 bill_to 可以是不同地点。

### 6.2 关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `HAS_CUSTOMER_SITE` | Customer → CustomerSite | 客户拥有的地点 |
| `SOLD_TO` | SalesOrder → Customer | 销售给客户 |
| `BILL_TO_SITE` | SalesOrder → CustomerSite | 开票地点 |
| `SHIP_TO_SITE` | SalesOrder → CustomerSite | 送货地点 |
| `RECEIVED_FROM` | ARReceipt → Customer | 收款来源 |

### 6.3 隐含业务规则

1. 🆕 **信用额度管理**：Customer.credit_limit ≥ 该客户所有未结 ARInvoice 合计金额
2. 🆕 **地点状态**：INACTIVE 地点不应有新的 SO 引用
3. 🆕 **Ship-to 地址变更审计**：大额订单的送货地址变更需审批

---

## 7. XLA 会计引擎 (`ontology/xla.md`)

### 7.1 实体

**XLAEvent（会计事件）**
- Oracle EBS 源表：`XLA_EVENTS`
- 核心属性：event_id, event_class, event_type, event_date, accounting_date, status, source_doc_type, source_doc_id
- 业务含义：将业务事件（采购/收货/开票等）转化为会计分录的触发器
- event_class 枚举：`PURCHASE_ORDER` / `RECEIVING` / `INVOICES` / `PAYMENTS` / `SALES_INVOICES` / `RECEIPTS` / `ADJUSTMENTS`
- event_type 枚举：`CREATE` / `REVERSE` / `ADJUSTMENT` / `CANCEL`

**XLAJournalEntry（子分类账凭证头）** 🆕
- Oracle EBS 源表：`XLA_AE_HEADERS`
- 核心属性：ae_header_id, accounting_entry_status, accounting_date, period_name, je_category, gl_transfer_status, description
- 业务含义：由 XLAEvent 触发生成的会计凭证头。一个 XLAEvent 生成一个 XLAJournalEntry。
- gl_transfer_status 枚举：`N`（未传输到GL）/ `Y`（已传输）/ `NT`（不传输）
- accounting_entry_status：`F`（Final）/ `D`（Draft）/ `I`（Incomplete）

**XLAJournalLine（子分类账凭证行）** 🆕
- Oracle EBS 源表：`XLA_AE_LINES`
- 核心属性：ae_line_num, accounting_class, entered_dr, entered_cr, accounted_dr, accounted_cr, currency_code, currency_conversion_rate, description
- 业务含义：凭证的借方/贷方行，每行关联一个 GL 科目组合
- accounting_class 枚举：
  - PO 应计：`ACCRUAL`（暂估应付）/ `CHARGE`（费用）
  - AP 付款：`LIABILITY`（应付负债）/ `CASH`（现金）/ `DISCOUNT`（折扣）
  - AR 收款：`RECEIVABLE`（应收）/ `REVENUE`（收入）/ `TAX`（税）

**AccountingDistribution（会计分配）**
- Oracle EBS 源表：自定义（基于 AP/PO 分配汇总）
- 核心属性：distribution_id, debit_amount, credit_amount, accounting_class, posted_flag

**XLADistributionLink（分配链接）** 🆕
- Oracle EBS 源表：`XLA_DISTRIBUTION_LINKS`
- 核心属性：link_id, source_distribution_type, source_distribution_id, applied_to_dist_id
- 业务含义：将 XLAJournalLine 回溯链接到源单据的分配行（如 InvoiceDistribution、PODistribution）。这是实现"从总账一路追溯到源单据"的关键桥梁。

### 7.2 关系

| 关系 | 方向 | 说明 | 新增标记 |
|------|------|------|---------|
| `ACCOUNTING_FOR` | XLAEvent → 源单据 | 会计事件对应源单据（PO/Receipt/Invoice/Payment/SO/ARInvoice） | |
| `GENERATES_ENTRY` | XLAEvent → XLAJournalEntry | 事件产生的凭证 | 🆕 |
| `HAS_XLA_LINE` | XLAJournalEntry → XLAJournalLine | 凭证行 | 🆕 |
| `XLA_LINE_TO_ACCOUNT` | XLAJournalLine → GLCodeCombination | 凭证行记入的科目组合 | 🆕 |
| `XLA_DIST_LINK` | XLAJournalLine → XLADistributionLink | 凭证行与源分配的链接 | 🆕 |
| `LINKS_TO_SOURCE_DIST` | XLADistributionLink → InvoiceDistribution | 链接到源单据分配 | 🆕 |
| `TRANSFERRED_TO_GL` | XLAJournalEntry → GLJournalEntry | 子分类账凭证传输到总账 | 🆕 |
| `DISTRIBUTED_TO` | AccountingDistribution → GLAccount | 分配到科目 | |

### 7.3 隐含业务规则

1. **借贷平衡**：每笔 XLAJournalEntry 的 sum(entered_dr) = sum(entered_cr)
2. **事件完整性**：每笔 PO/Receipt/Invoice/Payment 都应有对应的 XLAEvent
3. **不可逆记账**：FINAL 状态的事件不可修改，只能通过 REVERSE 事件冲销
4. 🆕 **GL 传输完整性**：所有 gl_transfer_status='N' 的 XLAJournalEntry 应在期间关闭前传输
5. 🆕 **本外币一致性**：entered_dr × currency_conversion_rate = accounted_dr
6. 🆕 **追溯完整性**：每条 XLAJournalLine 都应有 XLADistributionLink 回溯到源单据

### 7.4 典型 nGQL 查询

```ngql
# 追踪某 PO 的完整会计处理链
MATCH (xe:XLAEvent)-[:ACCOUNTING_FOR]->(po:PurchaseOrder)
WHERE po.PurchaseOrder.po_number == "PO-2026-0001"
OPTIONAL MATCH (xe)-[:GENERATES_ENTRY]->(xje:XLAJournalEntry)-[:HAS_XLA_LINE]->(xjl:XLAJournalLine)
RETURN xe.XLAEvent.event_class, xe.XLAEvent.event_type,
       xjl.XLAJournalLine.accounting_class,
       xjl.XLAJournalLine.entered_dr, xjl.XLAJournalLine.entered_cr;

# 🆕 未传输到 GL 的子分类账凭证（期间关闭前必须清理）
MATCH (xje:XLAJournalEntry)
WHERE xje.XLAJournalEntry.gl_transfer_status == "N"
  AND xje.XLAJournalEntry.accounting_entry_status == "F"
RETURN xje.XLAJournalEntry.ae_header_id,
       xje.XLAJournalEntry.accounting_date,
       xje.XLAJournalEntry.je_category;

# 🆕 从 GL 科目一路追溯到源单据（全链审计）
MATCH (xjl:XLAJournalLine)-[:XLA_LINE_TO_ACCOUNT]->(cc:GLCodeCombination)
WHERE cc.GLCodeCombination.segment3 == "2201"
MATCH (xje:XLAJournalEntry)-[:HAS_XLA_LINE]->(xjl)
MATCH (xe:XLAEvent)-[:GENERATES_ENTRY]->(xje)
MATCH (xe)-[:ACCOUNTING_FOR]->(doc)
RETURN xjl.XLAJournalLine.entered_dr, xjl.XLAJournalLine.entered_cr,
       xe.XLAEvent.source_doc_type, xe.XLAEvent.source_doc_id;
```

---

## 8. 总账 (`ontology/gl.md`)

### 8.1 实体

**Ledger（账套）** 🆕
- Oracle EBS 源表：`GL_LEDGERS`
- 核心属性：ledger_id, ledger_name, short_name, chart_of_accounts_id, currency_code, period_set_name, period_type, description
- 业务含义：EBS R12 多账套架构（Multi-Org）。一个 Ledger 对应一套科目表 + 一种本位币 + 一个会计日历。

**GLPeriod（会计期间）** 🆕
- Oracle EBS 源表：`GL_PERIOD_STATUSES`
- 核心属性：period_name, period_year, period_num, start_date, end_date, closing_status
- closing_status 枚举：
  - `O`（Open）— 可录入凭证
  - `C`（Closed）— 已关闭，不可录入
  - `P`（Permanently Closed）— 永久关闭
  - `F`（Future Entry）— 可提前录入未来期间凭证
  - `N`（Never Opened）— 从未打开
- 业务含义：控制凭证录入的时间窗口，关闭期间后余额不可变更

**GLCodeCombination（科目组合/CCID）** 🆕
- Oracle EBS 源表：`GL_CODE_COMBINATIONS`
- 核心属性：code_combination_id, segment1, segment2, segment3, segment4, segment5, concatenated_segments, enabled_flag, summary_flag, account_type
- 业务含义：Oracle EBS 的"弹性域"会计科目结构，每个 CCID 是多个段（Segment）的组合：
  - `segment1` — 公司代码（如 01=总公司, 02=子公司A）
  - `segment2` — 成本中心（如 100=采购部, 200=销售部）
  - `segment3` — 自然科目（如 2201=应付账款, 6001=主营成本）
  - `segment4` — 子目（如 01=国内, 02=进口）
  - `segment5` — 产品线（如 A01=产品线A）
  - `concatenated_segments` — 拼接字符串（如 "01-100-2201-01-A01"）
- account_type 枚举：`A`（Asset）/ `L`（Liability）/ `O`（Owner's Equity）/ `R`（Revenue）/ `E`（Expense）
- 关联：取代之前简化的 GLAccount，提供完整的多维会计科目

**GLAccount（总账科目）**
- 继续保留为科目层级树（科目表/Chart of Accounts），表达自然科目的上下级关系
- 核心属性：account_code, account_name, account_type, parent_account, level, is_leaf

**GLJournalBatch（日记账批次）** 🆕
- Oracle EBS 源表：`GL_JE_BATCHES`
- 核心属性：batch_id, batch_name, status, default_period_name, posted_date, description
- 业务含义：一个批次包含多个日记账分录，通常按来源或期间组织
- status 枚举：`U`（Unposted）/ `P`（Posted）/ `S`（Selected for posting）

**GLJournalEntry（日记账分录）**
- Oracle EBS 源表：`GL_JE_HEADERS`
- 核心属性：journal_number, journal_name, journal_source, journal_category, period_name, gl_date, status, total_debit, total_credit
- 🆕 journal_source 标准值：`Payables`（AP 自动凭证）/ `Receivables`（AR 自动凭证）/ `Purchasing`（PO 暂估）/ `Manual`（手工凭证）/ `Assets`（固定资产）/ `Inventory`（库存）
- 🆕 journal_category 标准值：`Purchase Invoices` / `Payments` / `Sales Invoices` / `Receipts` / `Accrual` / `Adjustment`

**GLJournalLine（日记账行）**
- Oracle EBS 源表：`GL_JE_LINES`
- 核心属性：line_number, debit_amount, credit_amount, description, reference

**GLBalance（科目余额）** 🆕
- Oracle EBS 源表：`GL_BALANCES`
- 核心属性：period_name, currency_code, period_net_dr, period_net_cr, begin_balance_dr, begin_balance_cr, translated_flag
- 业务含义：每个 CCID + 期间 + 币种的汇总余额。用于报表、试算平衡、趋势分析。
- 关键字段说明：
  - period_net_dr/cr：本期借/贷方发生额
  - begin_balance_dr/cr：期初余额

**CurrencyRate（汇率）** 🆕
- Oracle EBS 源表：`GL_DAILY_RATES`
- 核心属性：from_currency, to_currency, conversion_date, conversion_type, conversion_rate
- 业务含义：每日汇率表。多币种环境中，所有外币交易需按汇率折算为本位币。
- conversion_type 枚举：`Spot`（即期）/ `Corporate`（集团统一）/ `User`（自定义）

### 8.2 关系

| 关系 | 方向 | 说明 | 新增标记 |
|------|------|------|---------|
| `IN_LEDGER` | GLJournalEntry → Ledger | 凭证所属账套 | 🆕 |
| `IN_PERIOD` | GLJournalEntry → GLPeriod | 凭证所属期间 | 🆕 |
| `IN_BATCH` | GLJournalEntry → GLJournalBatch | 凭证所属批次 | 🆕 |
| `HAS_JOURNAL_LINE` | GLJournalEntry → GLJournalLine | 日记账行 | |
| `POSTED_TO` | GLJournalLine → GLCodeCombination | 记入科目组合 | 升级：原指向 GLAccount，现指向 CCID |
| `BALANCE_FOR` | GLBalance → GLCodeCombination | 余额对应的科目组合 | 🆕 |
| `BALANCE_IN_PERIOD` | GLBalance → GLPeriod | 余额对应的期间 | 🆕 |
| `ACCOUNT_IN_COA` | GLCodeCombination → GLAccount | CCID 中的自然科目 | 🆕 |
| `PARENT_ACCOUNT` | GLAccount → GLAccount | 科目层级（替代原 parent_account 属性） | 🆕 |

### 8.3 隐含业务规则

1. **借贷平衡**：GLJournalEntry.total_debit = GLJournalEntry.total_credit
2. **期间关闭**：已关闭期间（closing_status='C'/'P'）不允许新增分录
3. **科目层级**：非叶子科目（is_leaf=false）不应直接有分录
4. 🆕 **试算平衡**：期末所有 GLBalance 的 (begin_balance_dr + period_net_dr) - (begin_balance_cr + period_net_cr) 汇总应为 0
5. 🆕 **来源追溯**：journal_source='Manual' 的手工凭证占比过高需审计关注
6. 🆕 **期间连续性**：GLBalance 的 begin_balance 应等于上期的 end_balance
7. 🆕 **汇率一致性**：同一天同一币种同一 conversion_type 的汇率应唯一

### 8.4 典型 nGQL 查询

```ngql
# 查看某期间某科目的借贷发生额
MATCH (jl:GLJournalLine)-[:POSTED_TO]->(cc:GLCodeCombination),
      (je:GLJournalEntry)-[:HAS_JOURNAL_LINE]->(jl)
WHERE cc.GLCodeCombination.segment3 == "6001"
  AND je.GLJournalEntry.period_name == "2026-03"
  AND je.GLJournalEntry.status == "POSTED"
RETURN sum(jl.GLJournalLine.debit_amount) AS total_debit,
       sum(jl.GLJournalLine.credit_amount) AS total_credit;

# 🆕 手工凭证占比分析（异常审计）
MATCH (je:GLJournalEntry)
WHERE je.GLJournalEntry.period_name == "2026-03"
  AND je.GLJournalEntry.status == "POSTED"
WITH count(je) AS total_count,
     sum(CASE WHEN je.GLJournalEntry.journal_source == "Manual" THEN 1 ELSE 0 END) AS manual_count
RETURN total_count, manual_count,
       manual_count * 100.0 / total_count AS manual_pct;

# 🆕 科目余额趋势（某科目近 6 个期间的余额变化）
MATCH (bal:GLBalance)-[:BALANCE_FOR]->(cc:GLCodeCombination)
WHERE cc.GLCodeCombination.concatenated_segments == "01-100-2201-00-000"
RETURN bal.GLBalance.period_name,
       bal.GLBalance.begin_balance_dr - bal.GLBalance.begin_balance_cr AS begin_bal,
       bal.GLBalance.period_net_dr - bal.GLBalance.period_net_cr AS period_change
ORDER BY bal.GLBalance.period_name;

# 🆕 从总账凭证追溯到源单据（via XLA）
MATCH (je:GLJournalEntry)-[:HAS_JOURNAL_LINE]->(jl:GLJournalLine)
WHERE je.GLJournalEntry.journal_number == "JE-2026-0001"
MATCH (xje:XLAJournalEntry)-[:TRANSFERRED_TO_GL]->(je)
MATCH (xe:XLAEvent)-[:GENERATES_ENTRY]->(xje)
MATCH (xe)-[:ACCOUNTING_FOR]->(doc)
RETURN jl.GLJournalLine.line_number,
       jl.GLJournalLine.debit_amount, jl.GLJournalLine.credit_amount,
       xe.XLAEvent.source_doc_type, xe.XLAEvent.source_doc_id;
```

---

## 9. 库存域 (`ontology/inventory.md`) 🆕

### 9.1 实体

**InventoryTransaction（库存事务）**
- Oracle EBS 源表：`MTL_MATERIAL_TRANSACTIONS`
- 核心属性：transaction_id, transaction_type, transaction_date, quantity, uom, transaction_cost, source_type, source_id
- 业务含义：记录每一笔物料的进出和转移
- transaction_type 枚举：
  - `PO_RECEIPT` — 采购入库
  - `PO_RETURN` — 采购退货
  - `SALES_ISSUE` — 销售出库
  - `SALES_RETURN` — 销售退货
  - `SUBINVENTORY_TRANSFER` — 子库存转移
  - `INTER_ORG_TRANSFER` — 组织间转移
  - `CYCLE_COUNT_ADJ` — 盘点调整
  - `MISC_RECEIPT` / `MISC_ISSUE` — 杂收/杂发
- 反欺诈价值：频繁的 MISC_ISSUE（杂发）或异常的盘点调整是库存舞弊信号

**ItemCategory（物料分类）**
- Oracle EBS 源表：`MTL_CATEGORIES_B` + `MTL_CATEGORY_SETS`
- 核心属性：category_id, category_set_name, segment1, segment2, description
- 业务含义：多维分类体系（采购分类、库存分类、成本分类等）

### 9.2 关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `INV_TXN_FOR_ITEM` | InventoryTransaction → Item | 事务涉及的物料 |
| `INV_TXN_AT` | InventoryTransaction → Warehouse | 事务发生的仓库 |
| `INV_TXN_SOURCE` | InventoryTransaction → Receipt/Shipment | 事务来源单据 |
| `ITEM_IN_CATEGORY` | Item → ItemCategory | 物料所属分类 |
| `PARENT_CATEGORY` | ItemCategory → ItemCategory | 分类层级 |

### 9.3 隐含业务规则

1. **库存平衡**：入库事务合计 - 出库事务合计 = 当前库存量
2. **盘点差异**：CYCLE_COUNT_ADJ 频繁且金额大 = 库存管理或舞弊问题
3. **杂发监控**：MISC_ISSUE 无对应的审批记录需审计

---

## 10. 资金域 (`ontology/cash-mgmt.md`) 🆕

### 10.1 实体

**BankAccount（银行账户）**
- Oracle EBS 源表：`CE_BANK_ACCOUNTS`
- 核心属性：bank_account_id, bank_account_name, bank_account_number, bank_name, branch_name, currency_code, account_type, status
- 业务含义：企业自有银行账户，用于收付款和银行对账
- account_type 枚举：`INTERNAL`（企业账户）/ `SUPPLIER`（供应商账户）/ `CUSTOMER`（客户账户）

**BankStatement（银行对账单）**
- Oracle EBS 源表：`CE_STATEMENT_HEADERS`
- 核心属性：statement_id, statement_number, statement_date, bank_account_id, opening_balance, closing_balance, status

**BankStatementLine（对账单行）**
- Oracle EBS 源表：`CE_STATEMENT_LINES`
- 核心属性：line_number, trx_date, trx_type, amount, bank_trx_number, status, reconciled_flag
- trx_type 枚举：`CREDIT`（入账/收款）/ `DEBIT`（出账/付款）/ `SWEEP`（资金归集）

### 10.2 关系

| 关系 | 方向 | 说明 |
|------|------|------|
| `PAID_FROM_ACCOUNT` | Payment → BankAccount | 付款使用的银行账户 |
| `RECEIVED_TO_ACCOUNT` | ARReceipt → BankAccount | 收款入账的银行账户 |
| `STATEMENT_FOR_ACCOUNT` | BankStatement → BankAccount | 对账单对应的银行账户 |
| `HAS_STATEMENT_LINE` | BankStatement → BankStatementLine | 对账单行 |
| `RECONCILES_PAYMENT` | BankStatementLine → Payment | 银行流水对账到付款 |
| `RECONCILES_RECEIPT` | BankStatementLine → ARReceipt | 银行流水对账到收款 |

### 10.3 隐含业务规则

1. **银行对账**：BankStatement.closing_balance 应 = 所有已对账的 Payment/ARReceipt 的净额
2. **未对账项**：长期未对账的 BankStatementLine 需审计关注
3. **余额连续性**：上期 closing_balance = 本期 opening_balance

---

## 11. 主数据 (`ontology/master-data.md`)

### 11.1 实体

**Item（物料）**
- Oracle EBS 源表：`MTL_SYSTEM_ITEMS_B`
- 核心属性：item_number, item_name, item_type, category, uom, standard_cost, list_price, lead_time_days, safety_stock, abc_class
- 关键分类：RAW_MATERIAL / FINISHED_GOOD / SEMI_FINISHED / SERVICE / EXPENSE

**BOM（物料清单）+ BOMComponent**
- Oracle EBS 源表：`BOM_BILL_OF_MATERIALS` + `BOM_INVENTORY_COMPONENTS`
- BOM 表达父子物料关系：父物料 ← BOM_FOR ← BOM，BOM ← USES_COMPONENT → 子物料
- 多层 BOM 展开：通过递归遍历 USES_COMPONENT 边

**Organization（组织）**
- Oracle EBS 源表：`HR_ALL_ORGANIZATION_UNITS`
- 核心属性：org_code, org_name, org_type, parent_org_code, legal_entity, country, status
- 层级结构：COMPANY → BUSINESS_UNIT → DEPARTMENT → COST_CENTER
- 🆕 Oracle EBS Multi-Org 说明：
  - Operating Unit（OU）：AP/AR/PO 事务的基本组织单元
  - Inventory Organization：库存事务的基本组织单元
  - Legal Entity：法律主体（签合同、纳税的单位）
  - Set of Books / Ledger：会计核算主体

**Employee（员工）**
- Oracle EBS 源表：`PER_ALL_PEOPLE_F` + `PER_ALL_ASSIGNMENTS_F`
- 核心属性：employee_number, employee_name, position, department, email, manager_id, status

**ApprovalRecord（审批记录）**
- Oracle EBS 源表：`AME_TRANS_APPROVERS`（审批管理引擎）
- 核心属性：approval_id, doc_type, doc_number, approval_action, approver, approval_date, approval_level

**Contract（合同）**
- Oracle EBS 源表：`OKC_K_HEADERS_ALL_B`（合同管理）
- 核心属性：contract_number, contract_type, contract_name, status, start_date, end_date, total_amount

**Warehouse（仓库）**
- Oracle EBS 源表：`MTL_SECONDARY_INVENTORIES`（子库存）
- 类型：MAIN / SUB / TRANSIT / RETURN

**Currency（币种）+ UOM（计量单位）**
- 继续保留，无变更

### 11.2 典型 nGQL 查询

```ngql
# BOM 展开（2层）
MATCH (parent:Item)<-[:BOM_FOR]-(bom:BOM),
      (bc:BOMComponent)-[:USES_COMPONENT]->(child:Item)
WHERE parent.Item.item_number == "FG-001"
RETURN parent.Item.item_name AS parent_item,
       child.Item.item_number AS component,
       child.Item.item_name AS component_name,
       bc.BOMComponent.quantity_per AS qty_per;

# 断供影响链分析（某供应商断供影响哪些成品）
MATCH (s:Supplier)-[:SUPPLIES_ITEM]->(raw:Item)
WHERE s.Supplier.supplier_number == "V001234"
MATCH (raw)<-[:USES_COMPONENT]-(:BOMComponent)<--(bom:BOM)-[:BOM_FOR]->(fg:Item)
WHERE fg.Item.item_type == "FINISHED_GOOD"
RETURN DISTINCT fg.Item.item_number, fg.Item.item_name,
       raw.Item.item_number AS affected_material;
```

---

## 12. 业务约束 (`ontology/constraints.md`)

### 12.1 三单匹配规则（增强版）

```
三单匹配 (Three-Way Match) — Oracle EBS 标准:

匹配层级（取决于 POShipment.match_option + inspection_required_flag）:
  ┌─────────────────────────────────────────────────────┐
  │ 二单匹配 (2-Way):                                    │
  │   match_option='P', inspection='N'                   │
  │   检查: Invoice ≤ PO (仅 PO vs Invoice)              │
  │   适用: 低风险物料、服务类采购                         │
  ├─────────────────────────────────────────────────────┤
  │ 三单匹配 (3-Way):                                    │
  │   match_option='R', inspection='N'                   │
  │   检查: Invoice ≤ Receipt ≤ PO                       │
  │   适用: 一般物料采购（最常用）                         │
  ├─────────────────────────────────────────────────────┤
  │ 四单匹配 (4-Way):                                    │
  │   match_option='R', inspection='Y'                   │
  │   检查: Invoice ≤ Accepted ≤ Receipt ≤ PO            │
  │   适用: 高价值物料、关键零部件、进口物资               │
  └─────────────────────────────────────────────────────┘

匹配字段（在 POShipment 级别进行）:
  1. 数量匹配: |Invoice.qty - Shipment.qty_received| / Shipment.qty ≤ 容差%
  2. 金额匹配: |Invoice.amount - Shipment.amount| / Shipment.amount ≤ 容差%
  3. 价格匹配: Invoice.unit_price == PO.unit_price (通常严格匹配)
  4. 供应商一致: PO.supplier == Invoice.supplier

匹配失败自动产生 Hold:
  - PRICE hold → 价格不匹配
  - QTY REC hold → 数量超过收货量
  - QTY ORD hold → 数量超过订购量
  - AMT ORD hold → 金额超过订购金额

异常等级:
  - WARNING: 偏差 5-10%
  - ALERT: 偏差 10-20%
  - CRITICAL: 偏差 >20% 或供应商不一致 或被自动 Hold
```

### 12.2 时序约束

```
PTP 流程时序:
  PR.request_date ≤ PO.order_date ≤ Receipt.receipt_date
  ≤ Invoice.invoice_date ≤ Payment.payment_date

  🆕 细化:
  PO.order_date ≤ POShipment.need_by_date（承诺交货日）
  POShipment.need_by_date ≈ Receipt.receipt_date（±合理运输期）
  Receipt.receipt_date ≤ ReceivingTransaction(DELIVER).transaction_date
  Invoice.invoice_date ≤ Invoice.due_date（正常情况）
  Invoice.gl_date ∈ GLPeriod(status='O') 的期间范围

OTC 流程时序:
  SO.order_date ≤ Shipment.shipment_date
  ≤ ARInvoice.invoice_date ≤ ARReceipt.receipt_date

违规检测:
  - 收货日期早于下单日期 → 可能虚假交易
  - 发票日期早于收货日期 → 提前开票异常
  - 付款日期早于发票日期 → 提前付款异常
  - 🆕 收货日期远晚于 POShipment.need_by_date → 供应商交货延迟
  - 🆕 Invoice.gl_date 与 invoice_date 不在同一期间 → 跨期记账异常
  - 🆕 XLAEvent.accounting_date 与 event_date 不一致 → 会计处理延迟
```

### 12.3 金额约束

```
PO 金额完整性:
  PO.total_amount = SUM(POLine.amount)
  POLine.amount = POLine.quantity × POLine.unit_price
  🆕 POShipment.amount = POShipment.quantity × POLine.unit_price（或 price_override）

Invoice 金额完整性:
  Invoice.total_amount = SUM(InvoiceLine.amount) + Invoice.tax_amount
  🆕 SUM(InvoiceDistribution.amount) = InvoiceLine.amount（每行分配完整）

Payment 约束:
  Payment.amount ≤ Invoice.total_amount (不应超付)
  SUM(Payment for Invoice) = Invoice.total_amount (全额支付)
  🆕 Payment.amount ≤ PaymentSchedule.gross_amount（按期付款不超额）

🆕 GL 平衡约束:
  GLJournalEntry.total_debit = GLJournalEntry.total_credit
  GLBalance.begin_balance[period N+1] = GLBalance.end_balance[period N]
  SUM(all GLBalance.period_net_dr) = SUM(all GLBalance.period_net_cr)（全科目试算平衡）

🆕 XLA 平衡约束:
  SUM(XLAJournalLine.entered_dr) = SUM(XLAJournalLine.entered_cr) per XLAJournalEntry
  XLAJournalLine.accounted_dr = entered_dr × currency_conversion_rate
```

### 12.4 循环交易检测模式

```ngql
# 循环交易模式: A → B → C → A（循环资金流向）
MATCH (s1:Supplier)<-[:PLACED_WITH]-(po1:PurchaseOrder),
      (po1)-[:ORDERED_BY]->(:Employee)<-[:ORDERED_BY]-(po2:PurchaseOrder),
      (s2:Supplier)<-[:PLACED_WITH]-(po2),
      (po2)-[:ORDERED_BY]->(:Employee)<-[:ORDERED_BY]-(po3:PurchaseOrder),
      (s3:Supplier)<-[:PLACED_WITH]-(po3)
WHERE s1 != s2 AND s2 != s3 AND s1 != s3
  AND s1.Supplier.supplier_number IN [s3.Supplier.supplier_number]
RETURN s1.Supplier.supplier_name, s2.Supplier.supplier_name, s3.Supplier.supplier_name
LIMIT 100;
```

### 12.5 🆕 新增反欺诈检测模式

```
1. 供应商银行账号突变:
   SupplierSite.bank_account_number 变更 → 变更后首笔大额付款 → 重点审计
   检测: Payment.payment_date 在 SupplierSite.updated_at 后 30天内

2. 发票冻结快速释放:
   InvoiceHold 被创建后 <24小时即释放 + 发票金额 >100万 → 审计信号
   高频模式: 同一 Employee 释放大量 Hold

3. 费用报销拆分:
   同一 Employee 在 ±3天内多笔 ExpenseReport，单笔 < 审批限额，合计 > 限额

4. 收货不入库:
   ReceivingTransaction 有 RECEIVE 但无 DELIVER，且 Receipt 已 >30天
   可能: 物资被截留或虚假收货

5. 期末异常凭证:
   GLJournalEntry.journal_source='Manual' + gl_date 在期间最后 3天 + 金额 >50万
   可能: 期末利润调节

6. 未对账银行流水:
   BankStatementLine.reconciled_flag='N' + trx_date >90天
   可能: 异常资金流未被发现

7. 暂估长期未冲销:
   InvoiceDistribution.accrual_posted_flag='N' + Receipt.receipt_date >90天
   可能: 收货后供应商长期不开票，或暂估漏记
```

---

## 13. 本体 Prompt 注入策略

### 13.1 Phase 1 方案：全量注入

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

估算 token 消耗（v2.0 更新）：
- Schema 信息：~3500 tokens（v1.0 为 ~2000，新增实体增加 ~1500）
- 本体信息（全量）：~5000 tokens（v1.0 为 ~3000，新增域和规则增加 ~2000）
- 约束+语法：~1500 tokens（v1.0 为 ~1000，新增欺诈规则增加 ~500）
- 总计 Prompt 模板：~10000 tokens

### 13.2 Phase 2 过渡方案：动态选择

Phase 2 引入 Milvus 向量检索实现动态本体选择：

```
1. 将每个本体模块片段向量化存储到 Milvus
2. 用户提问时，先通过向量相似度找到最相关的 2-3 个本体模块
3. 仅注入相关模块到 Prompt，节省 token

预期收益:
  - Prompt token 从 ~10000 降至 ~4000-5000
  - 减少无关信息对 LLM 的干扰
  - 支持本体规模持续增长
```

---

## 14. 完整实体/关系汇总

### 14.1 Tag 汇总（共 57 个）

| # | Tag 名称 | 域 | Oracle EBS 源表 | v2.0 新增 |
|---|---------|-----|----------------|-----------|
| 1 | Supplier | 供应商 | PO_VENDORS / AP_SUPPLIERS | |
| 2 | SupplierSite | 供应商 | AP_SUPPLIER_SITES_ALL | 🆕 |
| 3 | SupplierQualification | 供应商 | 自定义 | |
| 4 | Customer | 客户 | HZ_PARTIES + HZ_CUST_ACCOUNTS | |
| 5 | CustomerSite | 客户 | HZ_CUST_ACCT_SITES_ALL | 🆕 |
| 6 | Item | 主数据 | MTL_SYSTEM_ITEMS_B | |
| 7 | Organization | 主数据 | HR_ALL_ORGANIZATION_UNITS | |
| 8 | Employee | 主数据 | PER_ALL_PEOPLE_F | |
| 9 | Warehouse | 主数据 | MTL_SECONDARY_INVENTORIES | |
| 10 | BOM | 主数据 | BOM_BILL_OF_MATERIALS | |
| 11 | BOMComponent | 主数据 | BOM_INVENTORY_COMPONENTS | |
| 12 | Currency | 主数据 | FND_CURRENCIES | |
| 13 | UOM | 主数据 | MTL_UNITS_OF_MEASURE | |
| 14 | PurchaseRequisition | 采购 | PO_REQUISITION_HEADERS_ALL | |
| 15 | PurchaseRequisitionLine | 采购 | PO_REQUISITION_LINES_ALL | |
| 16 | PurchaseOrder | 采购 | PO_HEADERS_ALL | |
| 17 | PurchaseOrderLine | 采购 | PO_LINES_ALL | |
| 18 | POShipment | 采购 | PO_LINE_LOCATIONS_ALL | 🆕 |
| 19 | Receipt | 采购 | RCV_SHIPMENT_HEADERS | |
| 20 | ReceiptLine | 采购 | RCV_SHIPMENT_LINES | |
| 21 | ReceivingTransaction | 采购 | RCV_TRANSACTIONS | 🆕 |
| 22 | Invoice | 应付 | AP_INVOICES_ALL | |
| 23 | InvoiceLine | 应付 | AP_INVOICE_LINES_ALL | |
| 24 | InvoiceDistribution | 应付 | AP_INVOICE_DISTRIBUTIONS_ALL | 🆕 |
| 25 | InvoiceHold | 应付 | AP_HOLDS_ALL | 🆕 |
| 26 | Payment | 应付 | AP_CHECKS_ALL | |
| 27 | PaymentBatch | 应付 | (批次层面) | |
| 28 | PaymentSchedule | 应付 | AP_PAYMENT_SCHEDULES_ALL | 🆕 |
| 29 | ExpenseReport | 应付 | AP_EXPENSE_REPORTS_ALL | 🆕 |
| 30 | SalesOrder | 应收 | OE_ORDER_HEADERS_ALL | |
| 31 | SalesOrderLine | 应收 | OE_ORDER_LINES_ALL | |
| 32 | Shipment | 应收 | WSH_NEW_DELIVERIES | |
| 33 | ShipmentLine | 应收 | WSH_DELIVERY_DETAILS | |
| 34 | ARInvoice | 应收 | RA_CUSTOMER_TRX_ALL | |
| 35 | ARInvoiceLine | 应收 | RA_CUSTOMER_TRX_LINES_ALL | 🆕 |
| 36 | ARReceipt | 应收 | AR_CASH_RECEIPTS_ALL | |
| 37 | Ledger | 总账 | GL_LEDGERS | 🆕 |
| 38 | GLPeriod | 总账 | GL_PERIOD_STATUSES | 🆕 |
| 39 | GLCodeCombination | 总账 | GL_CODE_COMBINATIONS | 🆕 |
| 40 | GLAccount | 总账 | (科目层级树) | |
| 41 | GLJournalBatch | 总账 | GL_JE_BATCHES | 🆕 |
| 42 | GLJournalEntry | 总账 | GL_JE_HEADERS | |
| 43 | GLJournalLine | 总账 | GL_JE_LINES | |
| 44 | GLBalance | 总账 | GL_BALANCES | 🆕 |
| 45 | CurrencyRate | 总账 | GL_DAILY_RATES | 🆕 |
| 46 | XLAEvent | XLA | XLA_EVENTS | |
| 47 | XLAJournalEntry | XLA | XLA_AE_HEADERS | 🆕 |
| 48 | XLAJournalLine | XLA | XLA_AE_LINES | 🆕 |
| 49 | AccountingDistribution | XLA | (汇总) | |
| 50 | XLADistributionLink | XLA | XLA_DISTRIBUTION_LINKS | 🆕 |
| 51 | InventoryTransaction | 库存 | MTL_MATERIAL_TRANSACTIONS | 🆕 |
| 52 | ItemCategory | 库存 | MTL_CATEGORIES_B | 🆕 |
| 53 | BankAccount | 资金 | CE_BANK_ACCOUNTS | 🆕 |
| 54 | BankStatement | 资金 | CE_STATEMENT_HEADERS | 🆕 |
| 55 | BankStatementLine | 资金 | CE_STATEMENT_LINES | 🆕 |
| 56 | ApprovalRecord | 审批 | AME_TRANS_APPROVERS | |
| 57 | Contract | 合同 | OKC_K_HEADERS_ALL_B | |

### 14.2 Edge Type 汇总（共 62 个）

| # | Edge Type | 方向 | 说明 | v2.0 新增 |
|---|-----------|------|------|-----------|
| 1 | PLACED_WITH | PO → Supplier | 下达采购 | |
| 2 | HAS_PO_LINE | PO → POLine | 订单行 | |
| 3 | HAS_PO_SHIPMENT | POLine → POShipment | 发运计划 | 🆕 |
| 4 | ORDERS_ITEM | POLine → Item | 订购物料 | |
| 5 | CONVERTS_TO_PO | PR → PO | 申请转订单 | |
| 6 | HAS_PR_LINE | PR → PRLine | 申请行 | |
| 7 | HAS_RECEIPT | PO → Receipt | 收货 | |
| 8 | HAS_RECEIPT_LINE | Receipt → ReceiptLine | 收货行 | |
| 9 | RECEIVES_SHIPMENT | ReceiptLine → POShipment | 收货行对应发运 | 🆕 |
| 10 | HAS_RCV_TRANSACTION | ReceiptLine → ReceivingTxn | 收货事务 | 🆕 |
| 11 | RCV_PARENT | ReceivingTxn → ReceivingTxn | 事务链 | 🆕 |
| 12 | SHIP_TO_SITE (PO) | POShipment → Organization | PO 送货目的地 | 🆕 |
| 13 | HAS_INVOICE | PO → Invoice | 三单匹配 | |
| 14 | HAS_INVOICE_LINE | Invoice → InvLine | 发票行 | |
| 15 | HAS_INVOICE_DIST | InvLine → InvDist | 会计分配 | 🆕 |
| 16 | DIST_TO_ACCOUNT | InvDist → GLCodeCombination | 分配到科目 | 🆕 |
| 17 | HAS_HOLD | Invoice → InvoiceHold | 冻结 | 🆕 |
| 18 | HOLD_RELEASED_BY | InvoiceHold → Employee | 释放人 | 🆕 |
| 19 | HAS_PAYMENT_SCHEDULE | Invoice → PaymentSchedule | 付款计划 | 🆕 |
| 20 | MATCHES_SHIPMENT | InvLine → POShipment | 匹配发运 | 🆕 |
| 21 | INVOICED_BY | Invoice → Supplier | 发票供应商 | |
| 22 | REMIT_TO_SITE | Invoice → SupplierSite | 付款地点 | 🆕 |
| 23 | PAYS_INVOICE | Payment → Invoice | 付款 | |
| 24 | PAID_TO | Payment → Supplier | 付款对象 | |
| 25 | PAID_TO_SITE | Payment → SupplierSite | 付款到地点 | 🆕 |
| 26 | PAID_FROM_ACCOUNT | Payment → BankAccount | 付款银行 | 🆕 |
| 27 | CONTAINS_PAYMENT | PayBatch → Payment | 批次 | |
| 28 | EXPENSE_BY | ExpenseReport → Employee | 报销人 | 🆕 |
| 29 | EXPENSE_TO_INVOICE | ExpenseReport → Invoice | 报销转发票 | 🆕 |
| 30 | SOLD_TO | SO → Customer | 销售 | |
| 31 | HAS_SO_LINE | SO → SOLine | 订单行 | |
| 32 | SELLS_ITEM | SOLine → Item | 销售物料 | |
| 33 | HAS_SHIPMENT | SO → Shipment | 发货 | |
| 34 | HAS_SHIPMENT_LINE | Shipment → ShipLine | 发货行 | |
| 35 | HAS_AR_INVOICE | SO → ARInvoice | 应收发票 | |
| 36 | HAS_AR_INVOICE_LINE | ARInvoice → ARInvLine | 应收发票行 | 🆕 |
| 37 | AR_LINE_FOR_ITEM | ARInvLine → Item | 发票行物料 | 🆕 |
| 38 | BILL_TO_SITE | SO → CustomerSite | 开票地点 | 🆕 |
| 39 | SHIP_TO_SITE (OTC) | SO → CustomerSite | 送货地点 | 🆕 |
| 40 | RECEIVED_FROM | ARReceipt → Customer | 收款来源 | |
| 41 | RECEIVED_TO_ACCOUNT | ARReceipt → BankAccount | 收款银行 | 🆕 |
| 42 | APPLIES_TO | ARReceipt → ARInvoice | 收款核销 | |
| 43 | SHIPPED_FROM | Shipment → Warehouse | 出库 | |
| 44 | HAS_SUPPLIER_SITE | Supplier → SupplierSite | 供应商地点 | 🆕 |
| 45 | HAS_CUSTOMER_SITE | Customer → CustomerSite | 客户地点 | 🆕 |
| 46 | SUPPLIES_ITEM | Supplier → Item | ASL | |
| 47 | HAS_QUALIFICATION | Supplier → SQ | 资质 | |
| 48 | ORDERED_BY | PO → Employee | 采购员 | |
| 49 | BOM_FOR | BOM → Item | BOM父物料 | |
| 50 | USES_COMPONENT | BOMComp → Item | BOM子物料 | |
| 51 | PARENT_ORG | Org → Org | 组织层级 | |
| 52 | BELONGS_TO_ORG | Employee → Org | 员工归属 | |
| 53 | RECEIVED_AT | Receipt → Warehouse | 入库 | |
| 54 | ACCOUNTING_FOR | XLAEvent → 源单据 | 会计事件 | |
| 55 | GENERATES_ENTRY | XLAEvent → XLAJournalEntry | 产生凭证 | 🆕 |
| 56 | HAS_XLA_LINE | XLAJournalEntry → XLAJournalLine | 凭证行 | 🆕 |
| 57 | XLA_LINE_TO_ACCOUNT | XLAJournalLine → GLCodeCombination | 科目 | 🆕 |
| 58 | XLA_DIST_LINK | XLAJournalLine → XLADistLink | 分配链接 | 🆕 |
| 59 | LINKS_TO_SOURCE_DIST | XLADistLink → InvDist | 回溯源 | 🆕 |
| 60 | TRANSFERRED_TO_GL | XLAJournalEntry → GLJournalEntry | 传输GL | 🆕 |
| 61 | POSTED_TO | JournalLine → GLCodeCombination | 记账 | 升级 |
| 62 | HAS_JOURNAL_LINE | Journal → JournalLine | 分录行 | |
| 63 | IN_BATCH | GLJournalEntry → GLJournalBatch | 批次 | 🆕 |
| 64 | IN_LEDGER | GLJournalEntry → Ledger | 账套 | 🆕 |
| 65 | IN_PERIOD | GLJournalEntry → GLPeriod | 期间 | 🆕 |
| 66 | BALANCE_FOR | GLBalance → GLCodeCombination | 余额科目 | 🆕 |
| 67 | BALANCE_IN_PERIOD | GLBalance → GLPeriod | 余额期间 | 🆕 |
| 68 | ACCOUNT_IN_COA | GLCodeCombination → GLAccount | 自然科目 | 🆕 |
| 69 | PARENT_ACCOUNT | GLAccount → GLAccount | 科目层级 | 🆕 |
| 70 | DISTRIBUTED_TO | AcctDist → GLAccount | 会计分配 | |
| 71 | INV_TXN_FOR_ITEM | InvTxn → Item | 库存物料 | 🆕 |
| 72 | INV_TXN_AT | InvTxn → Warehouse | 库存仓库 | 🆕 |
| 73 | INV_TXN_SOURCE | InvTxn → Receipt/Shipment | 库存来源 | 🆕 |
| 74 | ITEM_IN_CATEGORY | Item → ItemCategory | 物料分类 | 🆕 |
| 75 | PARENT_CATEGORY | ItemCategory → ItemCategory | 分类层级 | 🆕 |
| 76 | STATEMENT_FOR_ACCOUNT | BankStmt → BankAccount | 对账单 | 🆕 |
| 77 | HAS_STATEMENT_LINE | BankStmt → BankStmtLine | 对账单行 | 🆕 |
| 78 | RECONCILES_PAYMENT | BankStmtLine → Payment | 对账付款 | 🆕 |
| 79 | RECONCILES_RECEIPT | BankStmtLine → ARReceipt | 对账收款 | 🆕 |
| 80 | APPROVED_BY | Approval → Employee | 审批人 | |
| 81 | APPROVAL_FOR | Approval → Doc | 审批单据 | |
| 82 | CONTRACT_WITH | Contract → Party | 合同方 | |
| 83 | UNDER_CONTRACT | PO → Contract | 基于合同 | |

---

## 15. 全链路审计追踪路径

### 15.1 PTP 全链路（从需求到付款到总账）

```
PurchaseRequisition
  ─[CONVERTS_TO_PO]→ PurchaseOrder
    ─[HAS_PO_LINE]→ PurchaseOrderLine
      ─[HAS_PO_SHIPMENT]→ POShipment          ← 三单匹配核心
        ←[RECEIVES_SHIPMENT]─ ReceiptLine
          ─[HAS_RCV_TRANSACTION]→ ReceivingTransaction
        ←[MATCHES_SHIPMENT]─ InvoiceLine
    ─[PLACED_WITH]→ Supplier
      ─[HAS_SUPPLIER_SITE]→ SupplierSite
    ─[HAS_INVOICE]→ Invoice
      ─[HAS_INVOICE_LINE]→ InvoiceLine
        ─[HAS_INVOICE_DIST]→ InvoiceDistribution
          ─[DIST_TO_ACCOUNT]→ GLCodeCombination
      ─[HAS_HOLD]→ InvoiceHold
      ─[HAS_PAYMENT_SCHEDULE]→ PaymentSchedule
      ←[PAYS_INVOICE]─ Payment
        ─[PAID_TO_SITE]→ SupplierSite
        ─[PAID_FROM_ACCOUNT]→ BankAccount
    ←[ACCOUNTING_FOR]─ XLAEvent
      ─[GENERATES_ENTRY]→ XLAJournalEntry
        ─[TRANSFERRED_TO_GL]→ GLJournalEntry
          ─[HAS_JOURNAL_LINE]→ GLJournalLine
            ─[POSTED_TO]→ GLCodeCombination
```

### 15.2 OTC 全链路（从订单到收款到总账）

```
SalesOrder
  ─[SOLD_TO]→ Customer ─[HAS_CUSTOMER_SITE]→ CustomerSite
  ─[BILL_TO_SITE]→ CustomerSite
  ─[HAS_SO_LINE]→ SalesOrderLine ─[SELLS_ITEM]→ Item
  ─[HAS_SHIPMENT]→ Shipment ─[SHIPPED_FROM]→ Warehouse
  ─[HAS_AR_INVOICE]→ ARInvoice
    ─[HAS_AR_INVOICE_LINE]→ ARInvoiceLine
    ←[APPLIES_TO]─ ARReceipt
      ─[RECEIVED_FROM]→ Customer
      ─[RECEIVED_TO_ACCOUNT]→ BankAccount
  ←[ACCOUNTING_FOR]─ XLAEvent
    ─[GENERATES_ENTRY]→ XLAJournalEntry
      ─[TRANSFERRED_TO_GL]→ GLJournalEntry
```

---

## 附录 A. Neo4j Cypher → NebulaGraph nGQL 迁移指南

### A.1 属性访问（最关键）

```
Neo4j:   n.name
nGQL:    n.Person.name  (必须加 Tag 前缀)

Neo4j:   WHERE n.status = 'ACTIVE'
nGQL:    WHERE n.Supplier.status == "ACTIVE"  (双等号, 双引号)
```

### A.2 节点创建

```
Neo4j:   CREATE (n:Supplier {name: 'ABC'})
nGQL:    INSERT VERTEX Supplier(supplier_name) VALUES "SUP:V001":("ABC")
```

### A.3 关系创建

```
Neo4j:   MATCH (a:PO {id:'PO-001'}), (b:Supplier {id:'V001'})
         CREATE (a)-[:PLACED_WITH]->(b)

nGQL:    INSERT EDGE PLACED_WITH(order_date)
         VALUES "PO:PO-001"->"SUP:V001":(datetime("2026-04-01"))
```

### A.4 MERGE 替代

```
Neo4j:   MERGE (n:Supplier {id: 'V001'}) SET n.name = 'ABC'
nGQL:    UPSERT VERTEX ON Supplier "SUP:V001"
         SET supplier_name = "ABC"
         WHEN supplier_number == "V001"
```

### A.5 分页

```
Neo4j:   SKIP 10 LIMIT 20
nGQL:    LIMIT 20 OFFSET 10
```

### A.6 路径查询

```
Neo4j:   MATCH p = shortestPath((a)-[*..5]-(b))
nGQL:    FIND SHORTEST PATH FROM "id_a" TO "id_b" OVER * BIDIRECT UPTO 5 STEPS
```

### A.7 常见陷阱清单

| 陷阱 | 说明 | 解决方案 |
|------|------|---------|
| 忘记 Tag 前缀 | `n.name` → 报错 | 始终用 `n.TagName.property` |
| 单等号 | `==` 才是比较 | `=` 在 nGQL 中是赋值 |
| 字符串引号 | nGQL 推荐双引号 | 统一使用双引号 |
| VID 类型 | FIXED_STRING 需引号包裹 | VID 值始终加引号 `"SUP:V001"` |
| NULL 比较 | `IS NULL` / `IS NOT NULL` | 与 Neo4j 一致，但需加 Tag 前缀 |
| LIMIT 位置 | 必须在最后 | 不能放在 WITH 子句中间 |
| 无 MERGE | 不支持 MERGE | 用 UPSERT 替代 |
