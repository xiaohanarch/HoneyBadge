# NebulaGraph Schema 完整定义

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：`10-ontology.md`（业务语义）、`starter.md`（架构约束）

---

## 1. Space 定义

```ngql
CREATE SPACE IF NOT EXISTS honeybadge (
  partition_num = 100,
  replica_factor = 1,        -- 开发环境单副本；生产环境设为 2
  vid_type = FIXED_STRING(64) -- 使用业务键（如 PO-20260101-001）作为 VID
)
COMMENT = 'HoneyBadge ERP Knowledge Graph - Phase 1';

USE honeybadge;
```

**VID 设计说明**：

| 规则 | 说明 |
|------|------|
| 格式 | `{EntityPrefix}:{BusinessKey}` |
| 示例 | `SUP:V001234`, `PO:PO-20260101-001`, `INV:INV-2026-0001` |
| 类型 | FIXED_STRING(64)，兼顾可读性和性能 |
| 唯一性 | 由 ETL 层保证（基于源系统主键） |

---

## 2. 通用字段约定

所有 Tag 均包含以下标准字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `org_id` | `INT64` | 权限预留 — 组织ID |
| `dept_id` | `INT64` | 权限预留 — 部门ID |
| `data_scope` | `STRING` | 权限预留 — 数据范围标识（如 "全公司"/"本部门"/"本人"） |
| `created_at` | `TIMESTAMP` | 审计 — 数据创建时间 |
| `updated_at` | `TIMESTAMP` | 审计 — 数据最后更新时间 |
| `etl_batch_id` | `STRING` | 审计 — ETL 批次号（如 `ETL-20260404-001`） |
| `source_system` | `STRING` | 来源系统标识（如 `EBS`, `CUSTOM_ERP`） |
| `is_active` | `BOOL` | 逻辑删除标志 |

> 以下 Tag 定义中，通用字段不再重复列出，仅列业务属性。

---

## 3. Tag 定义（31+ 个）

### 3.1 主数据域（Master Data）

#### 3.1.1 Supplier（供应商）

```ngql
CREATE TAG IF NOT EXISTS Supplier (
  supplier_number     STRING NOT NULL,
  supplier_name       STRING NOT NULL,
  supplier_type       STRING,          -- MANUFACTURER / DISTRIBUTOR / SERVICE_PROVIDER
  status              STRING,          -- ACTIVE / INACTIVE / BLOCKED / PENDING
  country             STRING,
  city                STRING,
  address             STRING,
  contact_person      STRING,
  contact_phone       STRING,
  contact_email       STRING,
  bank_account        STRING,
  bank_name           STRING,
  tax_id              STRING,          -- 纳税人识别号
  currency            STRING DEFAULT "CNY",
  payment_terms       STRING,          -- NET30 / NET60 / IMMEDIATE
  credit_rating       STRING,          -- A / B / C / D
  registration_date   TIMESTAMP,
  qualification_expiry TIMESTAMP,      -- 资质到期日
  -- 权限预留字段
  org_id              INT64,
  dept_id             INT64,
  data_scope          STRING,
  -- 审计字段
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP,
  etl_batch_id        STRING,
  source_system       STRING,
  is_active           BOOL DEFAULT true
) COMMENT = '供应商主数据';
```

#### 3.1.2 Customer（客户）

```ngql
CREATE TAG IF NOT EXISTS Customer (
  customer_number     STRING NOT NULL,
  customer_name       STRING NOT NULL,
  customer_type       STRING,          -- INTERNAL / EXTERNAL / GOVERNMENT
  status              STRING,
  country             STRING,
  city                STRING,
  address             STRING,
  contact_person      STRING,
  contact_phone       STRING,
  contact_email       STRING,
  credit_limit        DOUBLE,
  payment_terms       STRING,
  tax_id              STRING,
  currency            STRING DEFAULT "CNY",
  sales_region        STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '客户主数据';
```

#### 3.1.3 Item（物料）

```ngql
CREATE TAG IF NOT EXISTS Item (
  item_number         STRING NOT NULL,
  item_name           STRING NOT NULL,
  item_description    STRING,
  item_type           STRING,          -- RAW_MATERIAL / FINISHED_GOOD / SEMI_FINISHED / SERVICE / EXPENSE
  category            STRING,          -- 物料分类
  uom                 STRING,          -- 计量单位 (EA/KG/M/L)
  standard_cost       DOUBLE,
  list_price          DOUBLE,
  weight              DOUBLE,
  weight_uom          STRING,
  lead_time_days      INT64,
  safety_stock        DOUBLE,
  min_order_qty       DOUBLE,
  status              STRING,          -- ACTIVE / INACTIVE / OBSOLETE
  abc_class           STRING,          -- A / B / C (库存分类)
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '物料主数据';
```

#### 3.1.4 Organization（组织）

```ngql
CREATE TAG IF NOT EXISTS Organization (
  org_code            STRING NOT NULL,
  org_name            STRING NOT NULL,
  org_type            STRING,          -- COMPANY / BUSINESS_UNIT / DEPARTMENT / COST_CENTER
  parent_org_code     STRING,
  legal_entity        STRING,
  country             STRING,
  city                STRING,
  status              STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '组织结构';
```

#### 3.1.5 Employee（员工）

```ngql
CREATE TAG IF NOT EXISTS Employee (
  employee_number     STRING NOT NULL,
  employee_name       STRING NOT NULL,
  position            STRING,
  department          STRING,
  email               STRING,
  phone               STRING,
  manager_id          STRING,
  hire_date           TIMESTAMP,
  status              STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '员工';
```

#### 3.1.6 Warehouse（仓库）

```ngql
CREATE TAG IF NOT EXISTS Warehouse (
  warehouse_code      STRING NOT NULL,
  warehouse_name      STRING NOT NULL,
  warehouse_type      STRING,          -- MAIN / SUB / TRANSIT / RETURN
  location            STRING,
  capacity            DOUBLE,
  status              STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '仓库';
```

#### 3.1.7 BOM（物料清单头）

```ngql
CREATE TAG IF NOT EXISTS BOM (
  bom_number          STRING NOT NULL,
  bom_name            STRING,
  bom_type            STRING,          -- STANDARD / ENGINEERING / PLANNING
  effective_from      TIMESTAMP,
  effective_to        TIMESTAMP,
  quantity            DOUBLE DEFAULT 1.0,  -- 基准数量
  uom                 STRING,
  status              STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '物料清单头';
```

#### 3.1.8 BOMComponent（BOM 组件行）

```ngql
CREATE TAG IF NOT EXISTS BOMComponent (
  component_seq       INT64,
  quantity_per        DOUBLE NOT NULL,   -- 单位用量
  uom                 STRING,
  effective_from      TIMESTAMP,
  effective_to        TIMESTAMP,
  yield_rate          DOUBLE DEFAULT 1.0,
  wip_supply_type     STRING,           -- PUSH / PULL / PHANTOM
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = 'BOM 组件行';
```

#### 3.1.9 Currency（币种）

```ngql
CREATE TAG IF NOT EXISTS Currency (
  currency_code       STRING NOT NULL,
  currency_name       STRING,
  symbol              STRING,
  decimal_places      INT64 DEFAULT 2,
  is_base_currency    BOOL DEFAULT false,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '币种';
```

#### 3.1.10 UOM（计量单位）

```ngql
CREATE TAG IF NOT EXISTS UOM (
  uom_code            STRING NOT NULL,
  uom_name            STRING,
  uom_class           STRING,          -- QUANTITY / WEIGHT / LENGTH / VOLUME
  base_uom            STRING,
  conversion_rate     DOUBLE DEFAULT 1.0,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '计量单位';
```

### 3.2 采购域（PTP — Procure-to-Pay）

#### 3.2.1 PurchaseRequisition（采购申请）

```ngql
CREATE TAG IF NOT EXISTS PurchaseRequisition (
  pr_number           STRING NOT NULL,
  pr_type             STRING,          -- STANDARD / BLANKET / INTERNAL
  description         STRING,
  status              STRING,          -- DRAFT / PENDING_APPROVAL / APPROVED / REJECTED / CLOSED
  requester           STRING,
  request_date        TIMESTAMP,
  need_by_date        TIMESTAMP,
  total_amount        DOUBLE,
  currency            STRING DEFAULT "CNY",
  approval_date       TIMESTAMP,
  approver            STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '采购申请';
```

#### 3.2.2 PurchaseRequisitionLine（采购申请行）

```ngql
CREATE TAG IF NOT EXISTS PurchaseRequisitionLine (
  line_number         INT64 NOT NULL,
  quantity            DOUBLE NOT NULL,
  unit_price          DOUBLE,
  amount              DOUBLE,
  uom                 STRING,
  need_by_date        TIMESTAMP,
  suggested_vendor    STRING,
  status              STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '采购申请行';
```

#### 3.2.3 PurchaseOrder（采购订单）

```ngql
CREATE TAG IF NOT EXISTS PurchaseOrder (
  po_number           STRING NOT NULL,
  po_type             STRING,          -- STANDARD / BLANKET / CONTRACT / PLANNED
  description         STRING,
  status              STRING,          -- DRAFT / APPROVED / OPEN / CLOSED / CANCELLED
  buyer               STRING,
  order_date          TIMESTAMP,
  approved_date       TIMESTAMP,
  total_amount        DOUBLE NOT NULL,
  currency            STRING DEFAULT "CNY",
  exchange_rate       DOUBLE DEFAULT 1.0,
  payment_terms       STRING,
  freight_terms       STRING,
  ship_to_location    STRING,
  bill_to_location    STRING,
  close_date          TIMESTAMP,
  cancel_reason       STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '采购订单';
```

#### 3.2.4 PurchaseOrderLine（采购订单行）

```ngql
CREATE TAG IF NOT EXISTS PurchaseOrderLine (
  line_number         INT64 NOT NULL,
  line_type           STRING,          -- GOODS / SERVICE
  quantity            DOUBLE NOT NULL,
  unit_price          DOUBLE NOT NULL,
  amount              DOUBLE NOT NULL,
  uom                 STRING,
  need_by_date        TIMESTAMP,
  promised_date       TIMESTAMP,
  received_quantity   DOUBLE DEFAULT 0,
  invoiced_quantity   DOUBLE DEFAULT 0,
  status              STRING,
  tax_code            STRING,
  tax_rate            DOUBLE DEFAULT 0,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '采购订单行';
```

#### 3.2.5 Receipt（收货单）

```ngql
CREATE TAG IF NOT EXISTS Receipt (
  receipt_number      STRING NOT NULL,
  receipt_type        STRING,          -- STANDARD / RETURN
  receipt_date        TIMESTAMP NOT NULL,
  status              STRING,          -- PENDING / RECEIVED / PARTIALLY_RECEIVED / RETURNED
  receiver            STRING,
  total_quantity      DOUBLE,
  warehouse           STRING,
  comments            STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '收货单';
```

#### 3.2.6 ReceiptLine（收货单行）

```ngql
CREATE TAG IF NOT EXISTS ReceiptLine (
  line_number         INT64 NOT NULL,
  received_quantity   DOUBLE NOT NULL,
  accepted_quantity   DOUBLE,
  rejected_quantity   DOUBLE DEFAULT 0,
  uom                 STRING,
  inspection_status   STRING,          -- PENDING / PASSED / FAILED
  lot_number          STRING,
  sublocation         STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '收货单行';
```

#### 3.2.7 SupplierQualification（供应商认证）

```ngql
CREATE TAG IF NOT EXISTS SupplierQualification (
  qualification_id    STRING NOT NULL,
  qualification_type  STRING,          -- ISO9001 / SAFETY / ENVIRONMENTAL / CUSTOM
  status              STRING,          -- VALID / EXPIRED / REVOKED
  issue_date          TIMESTAMP,
  expiry_date         TIMESTAMP,
  issuing_body        STRING,
  scope               STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '供应商认证/资质';
```

### 3.3 应付域（Payable）

#### 3.3.1 Invoice（发票）

```ngql
CREATE TAG IF NOT EXISTS Invoice (
  invoice_number      STRING NOT NULL,
  invoice_type        STRING,          -- STANDARD / CREDIT_MEMO / DEBIT_MEMO / PREPAYMENT
  invoice_date        TIMESTAMP NOT NULL,
  due_date            TIMESTAMP,
  status              STRING,          -- DRAFT / VALIDATED / APPROVED / PAID / CANCELLED / ON_HOLD
  total_amount        DOUBLE NOT NULL,
  tax_amount          DOUBLE DEFAULT 0,
  currency            STRING DEFAULT "CNY",
  exchange_rate       DOUBLE DEFAULT 1.0,
  payment_method      STRING,
  description         STRING,
  gl_date             TIMESTAMP,       -- 记账日期
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '发票（应付）';
```

#### 3.3.2 InvoiceLine（发票行）

```ngql
CREATE TAG IF NOT EXISTS InvoiceLine (
  line_number         INT64 NOT NULL,
  line_type           STRING,          -- ITEM / TAX / FREIGHT / MISC
  quantity            DOUBLE,
  unit_price          DOUBLE,
  amount              DOUBLE NOT NULL,
  tax_code            STRING,
  tax_rate            DOUBLE,
  description         STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '发票行';
```

#### 3.3.3 Payment（付款）

```ngql
CREATE TAG IF NOT EXISTS Payment (
  payment_number      STRING NOT NULL,
  payment_type        STRING,          -- CHECK / ELECTRONIC / WIRE / CASH
  payment_date        TIMESTAMP NOT NULL,
  amount              DOUBLE NOT NULL,
  currency            STRING DEFAULT "CNY",
  exchange_rate       DOUBLE DEFAULT 1.0,
  status              STRING,          -- CREATED / CONFIRMED / CLEARED / VOIDED / RECONCILED
  bank_account        STRING,
  payment_method      STRING,
  check_number        STRING,
  cleared_date        TIMESTAMP,
  void_date           TIMESTAMP,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '付款';
```

#### 3.3.4 PaymentBatch（付款批次）

```ngql
CREATE TAG IF NOT EXISTS PaymentBatch (
  batch_number        STRING NOT NULL,
  batch_date          TIMESTAMP,
  total_amount        DOUBLE,
  payment_count       INT64,
  status              STRING,          -- DRAFT / CONFIRMED / COMPLETED
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '付款批次';
```

### 3.4 应收域（OTC — Order-to-Cash）

#### 3.4.1 SalesOrder（销售订单）

```ngql
CREATE TAG IF NOT EXISTS SalesOrder (
  so_number           STRING NOT NULL,
  order_type          STRING,          -- STANDARD / RETURN / INTERNAL
  order_date          TIMESTAMP NOT NULL,
  status              STRING,          -- DRAFT / BOOKED / SHIPPED / INVOICED / CLOSED / CANCELLED
  total_amount        DOUBLE NOT NULL,
  currency            STRING DEFAULT "CNY",
  exchange_rate       DOUBLE DEFAULT 1.0,
  payment_terms       STRING,
  ship_to_address     STRING,
  bill_to_address     STRING,
  salesperson         STRING,
  requested_date      TIMESTAMP,
  scheduled_date      TIMESTAMP,
  cancel_reason       STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '销售订单';
```

#### 3.4.2 SalesOrderLine（销售订单行）

```ngql
CREATE TAG IF NOT EXISTS SalesOrderLine (
  line_number         INT64 NOT NULL,
  quantity            DOUBLE NOT NULL,
  unit_price          DOUBLE NOT NULL,
  amount              DOUBLE NOT NULL,
  uom                 STRING,
  shipped_quantity    DOUBLE DEFAULT 0,
  invoiced_quantity   DOUBLE DEFAULT 0,
  status              STRING,
  tax_code            STRING,
  tax_rate            DOUBLE DEFAULT 0,
  scheduled_ship_date TIMESTAMP,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '销售订单行';
```

#### 3.4.3 Shipment（发货单）

```ngql
CREATE TAG IF NOT EXISTS Shipment (
  shipment_number     STRING NOT NULL,
  shipment_date       TIMESTAMP NOT NULL,
  status              STRING,          -- PLANNED / PICKED / SHIPPED / DELIVERED / CANCELLED
  carrier             STRING,
  tracking_number     STRING,
  total_quantity      DOUBLE,
  warehouse           STRING,
  delivery_date       TIMESTAMP,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '发货单';
```

#### 3.4.4 ShipmentLine（发货单行）

```ngql
CREATE TAG IF NOT EXISTS ShipmentLine (
  line_number         INT64 NOT NULL,
  shipped_quantity    DOUBLE NOT NULL,
  uom                 STRING,
  lot_number          STRING,
  serial_number       STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '发货单行';
```

#### 3.4.5 ARInvoice（应收发票）

```ngql
CREATE TAG IF NOT EXISTS ARInvoice (
  invoice_number      STRING NOT NULL,
  invoice_type        STRING,          -- INVOICE / CREDIT_MEMO / DEBIT_MEMO
  invoice_date        TIMESTAMP NOT NULL,
  due_date            TIMESTAMP,
  status              STRING,          -- DRAFT / COMPLETE / COLLECTED / CANCELLED
  total_amount        DOUBLE NOT NULL,
  tax_amount          DOUBLE DEFAULT 0,
  currency            STRING DEFAULT "CNY",
  exchange_rate       DOUBLE DEFAULT 1.0,
  payment_terms       STRING,
  gl_date             TIMESTAMP,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '应收发票';
```

#### 3.4.6 ARReceipt（应收收款）

```ngql
CREATE TAG IF NOT EXISTS ARReceipt (
  receipt_number      STRING NOT NULL,
  receipt_type        STRING,          -- STANDARD / MISC
  receipt_date        TIMESTAMP NOT NULL,
  amount              DOUBLE NOT NULL,
  currency            STRING DEFAULT "CNY",
  status              STRING,          -- CONFIRMED / APPLIED / REVERSED
  payment_method      STRING,          -- WIRE / CHECK / CASH
  bank_account        STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '应收收款';
```

### 3.5 总账 / 会计域

#### 3.5.1 GLAccount（总账科目）

```ngql
CREATE TAG IF NOT EXISTS GLAccount (
  account_code        STRING NOT NULL,
  account_name        STRING NOT NULL,
  account_type        STRING,          -- ASSET / LIABILITY / EQUITY / REVENUE / EXPENSE
  parent_account      STRING,
  level               INT64,
  is_leaf             BOOL DEFAULT true,
  currency            STRING,
  status              STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '总账科目';
```

#### 3.5.2 GLJournalEntry（日记账分录）

```ngql
CREATE TAG IF NOT EXISTS GLJournalEntry (
  journal_number      STRING NOT NULL,
  journal_name        STRING,
  journal_source      STRING,          -- AP / AR / PO / MANUAL
  journal_category    STRING,
  period_name         STRING,          -- 如 2026-04
  gl_date             TIMESTAMP NOT NULL,
  status              STRING,          -- UNPOSTED / POSTED / REVERSED
  total_debit         DOUBLE,
  total_credit        DOUBLE,
  description         STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '日记账分录';
```

#### 3.5.3 GLJournalLine（日记账行）

```ngql
CREATE TAG IF NOT EXISTS GLJournalLine (
  line_number         INT64 NOT NULL,
  debit_amount        DOUBLE DEFAULT 0,
  credit_amount       DOUBLE DEFAULT 0,
  description         STRING,
  reference           STRING,          -- 原始单据号
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '日记账行';
```

#### 3.5.4 XLAEvent（XLA 会计事件）

```ngql
CREATE TAG IF NOT EXISTS XLAEvent (
  event_id            STRING NOT NULL,
  event_class         STRING,          -- PURCHASE / RECEIPT / INVOICE / PAYMENT / SALES / SHIPMENT
  event_type          STRING,          -- CREATE / REVERSE / ADJUSTMENT
  event_date          TIMESTAMP NOT NULL,
  accounting_date     TIMESTAMP,
  status              STRING,          -- DRAFT / FINAL / INCOMPLETE
  source_doc_type     STRING,
  source_doc_id       STRING,
  description         STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = 'XLA 会计事件';
```

#### 3.5.5 AccountingDistribution（会计分配）

```ngql
CREATE TAG IF NOT EXISTS AccountingDistribution (
  distribution_id     STRING NOT NULL,
  line_number         INT64,
  debit_amount        DOUBLE DEFAULT 0,
  credit_amount       DOUBLE DEFAULT 0,
  currency            STRING DEFAULT "CNY",
  accounting_class    STRING,          -- CHARGE / TAX / FREIGHT / ACCRUAL
  posted_flag         BOOL DEFAULT false,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '会计分配';
```

### 3.6 审批 / 流程域

#### 3.6.1 ApprovalRecord（审批记录）

```ngql
CREATE TAG IF NOT EXISTS ApprovalRecord (
  approval_id         STRING NOT NULL,
  doc_type            STRING,          -- PR / PO / INVOICE / PAYMENT / SO
  doc_number          STRING,
  approval_action     STRING,          -- SUBMIT / APPROVE / REJECT / RETURN
  approver            STRING,
  approval_date       TIMESTAMP,
  comments            STRING,
  approval_level      INT64,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '审批记录';
```

### 3.7 合同域

#### 3.7.1 Contract（合同）

```ngql
CREATE TAG IF NOT EXISTS Contract (
  contract_number     STRING NOT NULL,
  contract_type       STRING,          -- PURCHASE / SALES / SERVICE / BLANKET
  contract_name       STRING,
  status              STRING,          -- DRAFT / ACTIVE / EXPIRED / TERMINATED
  start_date          TIMESTAMP,
  end_date            TIMESTAMP,
  total_amount        DOUBLE,
  currency            STRING DEFAULT "CNY",
  description         STRING,
  org_id INT64, dept_id INT64, data_scope STRING,
  created_at TIMESTAMP, updated_at TIMESTAMP, etl_batch_id STRING, source_system STRING, is_active BOOL DEFAULT true
) COMMENT = '合同';
```

---

**Tag 汇总**（共 57 个，v2.0 新增 23 个标记 🆕）：

> 完整 Tag/Edge 清单及 Oracle EBS 源表映射详见 `10-ontology.md` v2.0

| # | Tag 名称 | 域 | v2.0 |
|---|---------|-----|------|
| 1 | Supplier | 供应商 | |
| 2 | SupplierSite | 供应商 | 🆕 |
| 3 | SupplierQualification | 供应商 | |
| 4 | Customer | 客户 | |
| 5 | CustomerSite | 客户 | 🆕 |
| 6 | Item | 主数据 | |
| 7 | Organization | 主数据 | |
| 8 | Employee | 主数据 | |
| 9 | Warehouse | 主数据 | |
| 10 | BOM | 主数据 | |
| 11 | BOMComponent | 主数据 | |
| 12 | Currency | 主数据 | |
| 13 | UOM | 主数据 | |
| 14 | PurchaseRequisition | 采购 | |
| 15 | PurchaseRequisitionLine | 采购 | |
| 16 | PurchaseOrder | 采购 | |
| 17 | PurchaseOrderLine | 采购 | |
| 18 | POShipment | 采购 | 🆕 |
| 19 | Receipt | 采购 | |
| 20 | ReceiptLine | 采购 | |
| 21 | ReceivingTransaction | 采购 | 🆕 |
| 22 | Invoice | 应付 | |
| 23 | InvoiceLine | 应付 | |
| 24 | InvoiceDistribution | 应付 | 🆕 |
| 25 | InvoiceHold | 应付 | 🆕 |
| 26 | Payment | 应付 | |
| 27 | PaymentBatch | 应付 | |
| 28 | PaymentSchedule | 应付 | 🆕 |
| 29 | ExpenseReport | 应付 | 🆕 |
| 30 | SalesOrder | 应收 | |
| 31 | SalesOrderLine | 应收 | |
| 32 | Shipment | 应收 | |
| 33 | ShipmentLine | 应收 | |
| 34 | ARInvoice | 应收 | |
| 35 | ARInvoiceLine | 应收 | 🆕 |
| 36 | ARReceipt | 应收 | |
| 37 | Ledger | 总账 | 🆕 |
| 38 | GLPeriod | 总账 | 🆕 |
| 39 | GLCodeCombination | 总账 | 🆕 |
| 40 | GLAccount | 总账 | |
| 41 | GLJournalBatch | 总账 | 🆕 |
| 42 | GLJournalEntry | 总账 | |
| 43 | GLJournalLine | 总账 | |
| 44 | GLBalance | 总账 | 🆕 |
| 45 | CurrencyRate | 总账 | 🆕 |
| 46 | XLAEvent | 会计 | |
| 47 | XLAJournalEntry | 会计 | 🆕 |
| 48 | XLAJournalLine | 会计 | 🆕 |
| 49 | AccountingDistribution | 会计 | |
| 50 | XLADistributionLink | 会计 | 🆕 |
| 51 | InventoryTransaction | 库存 | 🆕 |
| 52 | ItemCategory | 库存 | 🆕 |
| 53 | BankAccount | 资金 | 🆕 |
| 54 | BankStatement | 资金 | 🆕 |
| 55 | BankStatementLine | 资金 | 🆕 |
| 56 | ApprovalRecord | 审批 | |
| 57 | Contract | 合同 | |

---

## 4. Edge Type 定义（83 个，v2.0 新增 45 个）

> 完整 Edge Type 定义及新增的 DDL 见 `deploy/docker/nebula-edges.ngql` v2.0

### 4.1 采购域关系

```ngql
-- PO → 供应商
CREATE EDGE TYPE IF NOT EXISTS PLACED_WITH (
  order_date TIMESTAMP,
  org_id INT64, dept_id INT64
) COMMENT = '采购订单下达给供应商';

-- PO → PO 行
CREATE EDGE TYPE IF NOT EXISTS HAS_PO_LINE (
  org_id INT64, dept_id INT64
) COMMENT = '采购订单包含行项目';

-- PO 行 → 物料
CREATE EDGE TYPE IF NOT EXISTS ORDERS_ITEM (
  quantity DOUBLE,
  unit_price DOUBLE,
  org_id INT64, dept_id INT64
) COMMENT = 'PO行订购物料';

-- PR → PO (采购申请转采购订单)
CREATE EDGE TYPE IF NOT EXISTS CONVERTS_TO_PO (
  conversion_date TIMESTAMP,
  org_id INT64, dept_id INT64
) COMMENT = '采购申请转为采购订单';

-- PR → PR 行
CREATE EDGE TYPE IF NOT EXISTS HAS_PR_LINE (
  org_id INT64, dept_id INT64
) COMMENT = '采购申请包含行项目';

-- PO → 收货单
CREATE EDGE TYPE IF NOT EXISTS HAS_RECEIPT (
  org_id INT64, dept_id INT64
) COMMENT = '采购订单对应收货';

-- 收货单 → 收货行
CREATE EDGE TYPE IF NOT EXISTS HAS_RECEIPT_LINE (
  org_id INT64, dept_id INT64
) COMMENT = '收货单包含行项目';

-- PO → 发票 (应付)
CREATE EDGE TYPE IF NOT EXISTS HAS_INVOICE (
  match_status STRING,    -- MATCHED / UNMATCHED / PARTIAL
  match_date TIMESTAMP,
  org_id INT64, dept_id INT64
) COMMENT = '采购订单对应发票（三单匹配）';

-- PO → 采购员
CREATE EDGE TYPE IF NOT EXISTS ORDERED_BY (
  org_id INT64, dept_id INT64
) COMMENT = '采购订单由采购员创建';

-- 供应商 → 认证
CREATE EDGE TYPE IF NOT EXISTS HAS_QUALIFICATION (
  org_id INT64, dept_id INT64
) COMMENT = '供应商持有认证/资质';

-- 供应商 → 物料 (供应关系)
CREATE EDGE TYPE IF NOT EXISTS SUPPLIES_ITEM (
  priority INT64,          -- 供应优先级
  unit_price DOUBLE,
  lead_time_days INT64,
  status STRING,           -- ACTIVE / INACTIVE
  effective_from TIMESTAMP,
  effective_to TIMESTAMP,
  org_id INT64, dept_id INT64
) COMMENT = '供应商供应物料（ASL - Approved Supplier List）';
```

### 4.2 应付域关系

```ngql
-- 发票 → 发票行
CREATE EDGE TYPE IF NOT EXISTS HAS_INVOICE_LINE (
  org_id INT64, dept_id INT64
) COMMENT = '发票包含行项目';

-- 发票 → 供应商
CREATE EDGE TYPE IF NOT EXISTS INVOICED_BY (
  org_id INT64, dept_id INT64
) COMMENT = '发票来自供应商';

-- 付款 → 发票
CREATE EDGE TYPE IF NOT EXISTS PAYS_INVOICE (
  paid_amount DOUBLE,
  org_id INT64, dept_id INT64
) COMMENT = '付款对应发票';

-- 付款 → 供应商
CREATE EDGE TYPE IF NOT EXISTS PAID_TO (
  org_id INT64, dept_id INT64
) COMMENT = '付款支付给供应商';

-- 付款批次 → 付款
CREATE EDGE TYPE IF NOT EXISTS CONTAINS_PAYMENT (
  org_id INT64, dept_id INT64
) COMMENT = '付款批次包含付款';
```

### 4.3 应收域关系

```ngql
-- 销售订单 → 客户
CREATE EDGE TYPE IF NOT EXISTS SOLD_TO (
  order_date TIMESTAMP,
  org_id INT64, dept_id INT64
) COMMENT = '销售订单卖给客户';

-- 销售订单 → SO 行
CREATE EDGE TYPE IF NOT EXISTS HAS_SO_LINE (
  org_id INT64, dept_id INT64
) COMMENT = '销售订单包含行项目';

-- SO 行 → 物料
CREATE EDGE TYPE IF NOT EXISTS SELLS_ITEM (
  quantity DOUBLE,
  unit_price DOUBLE,
  org_id INT64, dept_id INT64
) COMMENT = 'SO行销售物料';

-- 销售订单 → 发货单
CREATE EDGE TYPE IF NOT EXISTS HAS_SHIPMENT (
  org_id INT64, dept_id INT64
) COMMENT = '销售订单对应发货';

-- 发货单 → 发货行
CREATE EDGE TYPE IF NOT EXISTS HAS_SHIPMENT_LINE (
  org_id INT64, dept_id INT64
) COMMENT = '发货单包含行项目';

-- 销售订单 → 应收发票
CREATE EDGE TYPE IF NOT EXISTS HAS_AR_INVOICE (
  org_id INT64, dept_id INT64
) COMMENT = '销售订单对应应收发票';

-- 应收收款 → 客户
CREATE EDGE TYPE IF NOT EXISTS RECEIVED_FROM (
  org_id INT64, dept_id INT64
) COMMENT = '收款来自客户';

-- 应收收款 → 应收发票
CREATE EDGE TYPE IF NOT EXISTS APPLIES_TO (
  applied_amount DOUBLE,
  org_id INT64, dept_id INT64
) COMMENT = '收款核销应收发票';
```

### 4.4 主数据 / 组织关系

```ngql
-- BOM → 父物料
CREATE EDGE TYPE IF NOT EXISTS BOM_FOR (
  org_id INT64, dept_id INT64
) COMMENT = 'BOM 对应父物料';

-- BOM 组件 → 子物料
CREATE EDGE TYPE IF NOT EXISTS USES_COMPONENT (
  quantity_per DOUBLE,
  org_id INT64, dept_id INT64
) COMMENT = 'BOM 使用子物料';

-- 组织层级
CREATE EDGE TYPE IF NOT EXISTS PARENT_ORG (
  org_id INT64, dept_id INT64
) COMMENT = '上级组织';

-- 员工 → 组织
CREATE EDGE TYPE IF NOT EXISTS BELONGS_TO_ORG (
  org_id INT64, dept_id INT64
) COMMENT = '员工归属组织';

-- 收货 → 仓库
CREATE EDGE TYPE IF NOT EXISTS RECEIVED_AT (
  org_id INT64, dept_id INT64
) COMMENT = '收货入库到仓库';

-- 发货 → 仓库
CREATE EDGE TYPE IF NOT EXISTS SHIPPED_FROM (
  org_id INT64, dept_id INT64
) COMMENT = '从仓库发货';
```

### 4.5 会计域关系

```ngql
-- XLA 事件 → 源单据（泛化关系，source_doc_type 区分）
CREATE EDGE TYPE IF NOT EXISTS ACCOUNTING_FOR (
  event_class STRING,
  org_id INT64, dept_id INT64
) COMMENT = 'XLA 会计事件对应源单据';

-- 日记账行 → 科目
CREATE EDGE TYPE IF NOT EXISTS POSTED_TO (
  org_id INT64, dept_id INT64
) COMMENT = '日记账行记入科目';

-- 日记账 → 日记账行
CREATE EDGE TYPE IF NOT EXISTS HAS_JOURNAL_LINE (
  org_id INT64, dept_id INT64
) COMMENT = '日记账包含行';

-- 会计分配 → 科目
CREATE EDGE TYPE IF NOT EXISTS DISTRIBUTED_TO (
  org_id INT64, dept_id INT64
) COMMENT = '会计分配到科目';
```

### 4.6 审批 / 合同关系

```ngql
-- 审批记录 → 审批人
CREATE EDGE TYPE IF NOT EXISTS APPROVED_BY (
  org_id INT64, dept_id INT64
) COMMENT = '由审批人审批';

-- 审批记录 → 单据（泛化）
CREATE EDGE TYPE IF NOT EXISTS APPROVAL_FOR (
  doc_type STRING,
  org_id INT64, dept_id INT64
) COMMENT = '审批针对的单据';

-- 合同 → 供应商/客户
CREATE EDGE TYPE IF NOT EXISTS CONTRACT_WITH (
  party_type STRING,      -- SUPPLIER / CUSTOMER
  org_id INT64, dept_id INT64
) COMMENT = '合同签订方';

-- PO → 合同
CREATE EDGE TYPE IF NOT EXISTS UNDER_CONTRACT (
  org_id INT64, dept_id INT64
) COMMENT = '采购订单基于合同';
```

---

**Edge Type 汇总**（共 83 个，v2.0 新增 45 个）：

> 完整清单见 `10-ontology.md` 第 14.2 节 及 `deploy/docker/nebula-edges.ngql`

原有 38 个 Edge Type 保持不变，v2.0 新增关键 Edge Type：

| Edge Type | 方向 | 说明 | 域 |
|-----------|------|------|---|
| HAS_SUPPLIER_SITE | Supplier → SupplierSite | 供应商地点 | 供应商 |
| HAS_CUSTOMER_SITE | Customer → CustomerSite | 客户地点 | 客户 |
| HAS_PO_SHIPMENT | POLine → POShipment | 发运计划 | 采购 |
| RECEIVES_SHIPMENT | ReceiptLine → POShipment | 收货匹配发运 | 采购 |
| HAS_RCV_TRANSACTION | ReceiptLine → RcvTxn | 收货事务 | 采购 |
| RCV_PARENT | RcvTxn → RcvTxn | 事务链 | 采购 |
| HAS_INVOICE_DIST | InvLine → InvDist | 发票分配 | 应付 |
| DIST_TO_ACCOUNT | InvDist → CCID | 分配到科目 | 应付 |
| HAS_HOLD | Invoice → Hold | 冻结 | 应付 |
| HOLD_RELEASED_BY | Hold → Employee | 释放人 | 应付 |
| MATCHES_SHIPMENT | InvLine → POShipment | 三单匹配 | 应付 |
| PAID_TO_SITE | Payment → SupplierSite | 付款到地点 | 应付 |
| REMIT_TO_SITE | Invoice → SupplierSite | 发票付款地 | 应付 |
| PAID_FROM_ACCOUNT | Payment → BankAccount | 付款银行 | 应付 |
| HAS_AR_INVOICE_LINE | ARInvoice → ARInvLine | 应收发票行 | 应收 |
| BILL_TO_SITE | SO → CustomerSite | 开票地点 | 应收 |
| GENERATES_ENTRY | XLAEvent → XLAJrnl | XLA凭证 | 会计 |
| TRANSFERRED_TO_GL | XLAJrnl → GLJrnl | 传输GL | 会计 |
| IN_LEDGER | GLJrnl → Ledger | 账套 | 总账 |
| IN_PERIOD | GLJrnl → GLPeriod | 期间 | 总账 |
| BALANCE_FOR | GLBal → CCID | 余额科目 | 总账 |

---

## 5. 索引策略

### 5.1 Tag Index（单属性索引）

```ngql
-- 主键索引（用于精确查找）
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

-- 状态索引（用于过滤查询）
CREATE TAG INDEX idx_po_status ON PurchaseOrder(status(20));
CREATE TAG INDEX idx_invoice_status ON Invoice(status(20));
CREATE TAG INDEX idx_so_status ON SalesOrder(status(20));
CREATE TAG INDEX idx_supplier_status ON Supplier(status(20));
CREATE TAG INDEX idx_item_status ON Item(status(20));

-- 权限字段索引（用于权限过滤）
CREATE TAG INDEX idx_po_org ON PurchaseOrder(org_id);
CREATE TAG INDEX idx_invoice_org ON Invoice(org_id);
CREATE TAG INDEX idx_so_org ON SalesOrder(org_id);
CREATE TAG INDEX idx_supplier_org ON Supplier(org_id);
```

### 5.2 复合索引

```ngql
-- 日期+状态复合查询
CREATE TAG INDEX idx_po_date_status ON PurchaseOrder(order_date, status(20));
CREATE TAG INDEX idx_invoice_date_status ON Invoice(invoice_date, status(20));
CREATE TAG INDEX idx_so_date_status ON SalesOrder(order_date, status(20));

-- 组织+状态（权限过滤+状态筛选）
CREATE TAG INDEX idx_po_org_status ON PurchaseOrder(org_id, status(20));
CREATE TAG INDEX idx_invoice_org_status ON Invoice(org_id, status(20));
```

### 5.3 Edge Index

```ngql
-- 三单匹配查询加速
CREATE EDGE INDEX idx_has_invoice_status ON HAS_INVOICE(match_status(20));

-- 供应关系查询
CREATE EDGE INDEX idx_supplies_item_status ON SUPPLIES_ITEM(status(20));

-- 按组织过滤边
CREATE EDGE INDEX idx_placed_with_org ON PLACED_WITH(org_id);
CREATE EDGE INDEX idx_sold_to_org ON SOLD_TO(org_id);
```

### 5.4 重建索引

```ngql
-- 索引创建后需重建才能对已有数据生效
REBUILD TAG INDEX idx_supplier_number, idx_customer_number, idx_item_number;
REBUILD TAG INDEX idx_po_number, idx_invoice_number, idx_so_number;
REBUILD TAG INDEX idx_po_status, idx_invoice_status, idx_so_status;
REBUILD TAG INDEX idx_po_org, idx_invoice_org, idx_so_org;
REBUILD EDGE INDEX idx_has_invoice_status, idx_supplies_item_status;
-- ... 其余索引同理
```

---

## 6. Neo4j → NebulaGraph 语法差异对照表

| 概念 | Neo4j (Cypher) | NebulaGraph (nGQL) | 说明 |
|------|---------------|-------------------|------|
| 节点标签 | `(:Person)` | Tag: `Person` | NebulaGraph 用 Tag 概念 |
| 创建节点 | `CREATE (n:Person {name:'Tom'})` | `INSERT VERTEX Person(name) VALUES "id1":("Tom")` | 必须指定 VID |
| 创建关系 | `CREATE (a)-[:KNOWS]->(b)` | `INSERT EDGE KNOWS() VALUES "id1"->"id2":()` | 使用 VID 引用 |
| 查询节点 | `MATCH (n:Person) WHERE n.name='Tom'` | `LOOKUP ON Person WHERE Person.name == "Tom"` 或 `MATCH (n:Person) WHERE n.Person.name == "Tom"` | 属性访问需加 Tag 前缀 |
| 属性访问 | `n.name` | `n.Person.name` | **关键差异**：必须 `vertex.Tag.property` |
| 多跳遍历 | `MATCH (a)-[:KNOWS*1..3]->(b)` | `MATCH (a)-[e:KNOWS*1..3]->(b)` | 基本兼容 |
| 聚合 | `RETURN count(n)` | `RETURN count(n)` | 基本兼容 |
| 可选匹配 | `OPTIONAL MATCH` | `OPTIONAL MATCH` | 支持 |
| 删除 | `DELETE n` / `DETACH DELETE n` | `DELETE VERTEX "id1"` / `DELETE VERTEX "id1" WITH EDGE` | 语法不同 |
| ID 访问 | `id(n)` | `id(n)` | 返回 VID |
| 标签检查 | `labels(n)` | `tags(n)` | 函数名不同 |
| MERGE | `MERGE (n:Person {id:1})` | 不支持 MERGE | 需用 UPSERT 或先查后插 |
| UNWIND | `UNWIND list AS x` | `UNWIND list AS x` | 支持 |
| WITH | `WITH n, count(*) AS cnt` | `WITH n, count(*) AS cnt` | 支持 |
| LIMIT/SKIP | `LIMIT 10 SKIP 5` | `LIMIT 10 OFFSET 5` | SKIP → OFFSET |
| NULL 检查 | `WHERE n.name IS NOT NULL` | `WHERE n.Person.name IS NOT NULL` | 需 Tag 前缀 |
| 正则 | `WHERE n.name =~ 'Tom.*'` | `WHERE n.Person.name =~ 'Tom.*'` | 支持但需索引 |

**迁移关键注意事项**：

1. **属性访问必须带 Tag 前缀**：这是最常见的迁移问题
2. **VID 必须显式指定**：不像 Neo4j 自动生成 internal ID
3. **无 MERGE 语句**：需改用 `UPSERT` 或业务逻辑处理
4. **Schema 预定义**：所有 Tag / Edge Type 必须先定义再使用，不能像 Neo4j 随时创建新 Label

---

## 7. 数据冷热分区策略

### 7.1 分区规则

| 数据时间 | 分区 | 策略 |
|---------|------|------|
| 近 24 个月 | **热数据** | 存储在 NebulaGraph 主 Space，正常索引，实时查询 |
| 24-60 个月 | **温数据** | 存储在 NebulaGraph 归档 Space（`honeybadge_archive`），按需加载 |
| 60 个月以上 | **冷数据** | 导出到 PostgreSQL / HDFS，不入图 |

### 7.2 归档 Space

```ngql
CREATE SPACE IF NOT EXISTS honeybadge_archive (
  partition_num = 50,
  replica_factor = 1,
  vid_type = FIXED_STRING(64)
) COMMENT = 'HoneyBadge 归档数据（24-60个月）';
```

### 7.3 归档流程

```
每月 1 日凌晨执行：
  1. 查询 honeybadge 中 updated_at < NOW() - 24 months 的节点/边
  2. 批量导出到 honeybadge_archive
  3. 从 honeybadge 中删除已归档数据
  4. 重建受影响的索引
  5. 记录归档日志
```

---

## 8. 完整建库建表 nGQL 脚本

> 以下脚本可直接在 NebulaGraph Console 或 Studio 中执行。
> 完整脚本已在上述各章节中给出，此处提供执行顺序。

```bash
# 执行顺序（在 nebula-console 中）
# Step 1: 创建 Space
# Step 2: 等待 Space 生效（约 10 秒）
# Step 3: 创建所有 Tag
# Step 4: 创建所有 Edge Type
# Step 5: 创建所有 Index
# Step 6: 重建 Index

# 初始化脚本放置路径：
#   deploy/nebula/init-schema.ngql      -- 主 Space 初始化
#   deploy/nebula/init-archive.ngql     -- 归档 Space 初始化
#   deploy/nebula/init-indexes.ngql     -- 索引创建
#   deploy/nebula/rebuild-indexes.ngql  -- 索引重建
```

**初始化等待说明**：

```ngql
-- Space 创建后需等待心跳同步（默认 10 秒）
-- 在脚本中建议使用 :sleep 10 或在应用层等待
CREATE SPACE honeybadge (...);
-- 等待 10 秒
USE honeybadge;
-- 然后创建 Tag / Edge Type
```
