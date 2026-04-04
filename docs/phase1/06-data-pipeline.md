# ETL 数据管道

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：`01-nebula-schema.md`（目标 Schema）, `10-ontology.md`（映射规则）

---

## 1. 整体流程

```
公司同步工具                HoneyBadge ETL Pipeline
(不纳入设计)
                ┌─────────────────────────────────────────────────────┐
ERP 源系统 ──→ │  ODS 表   →  数据质量校验  →  图模型转换  →  导入    │ → NebulaGraph
  (Oracle EBS   │ (PostgreSQL) (Great Expect.)  (Python)    (nebula-  │
   / 自研 ERP)  │                                           importer) │
                └─────────────────────────────────────────────────────┘
                                    │(失败)
                                    ▼
                               隔离区 + 告警
```

**关键约定**：
- 公司同步工具负责将 ERP 数据同步到 ODS 表（PostgreSQL），HoneyBadge 从 ODS 表开始处理
- ODS 表结构由 HoneyBadge 定义，作为与公司同步工具的接口约定
- 触发机制：同步工具完成后写入标记表/发送 Kafka 消息，ETL Pipeline 感知后启动

---

## 2. ODS 层设计

### 2.1 ODS 表清单

对应 ERP 源系统表，按业务域分组（共约 41 张表）。

#### 主数据

| ODS 表名 | 对应 ERP 表 | 目标 Tag | 说明 |
|---------|-----------|---------|------|
| `ods_supplier` | AP_SUPPLIERS | Supplier | 供应商 |
| `ods_supplier_site` | AP_SUPPLIER_SITES_ALL | (Supplier 属性) | 供应商地点 |
| `ods_customer` | RA_CUSTOMERS | Customer | 客户 |
| `ods_customer_site` | HZ_CUST_SITE_USES_ALL | (Customer 属性) | 客户地点 |
| `ods_item` | MTL_SYSTEM_ITEMS_B | Item | 物料 |
| `ods_item_category` | MTL_ITEM_CATEGORIES | (Item 属性) | 物料分类 |
| `ods_organization` | HR_ALL_ORGANIZATION_UNITS | Organization | 组织 |
| `ods_employee` | PER_ALL_PEOPLE_F | Employee | 员工 |
| `ods_warehouse` | MTL_SECONDARY_INVENTORIES | Warehouse | 仓库 |
| `ods_bom_header` | BOM_STRUCTURES_B | BOM | BOM 头 |
| `ods_bom_component` | BOM_COMPONENTS_B | BOMComponent | BOM 组件 |
| `ods_uom` | MTL_UNITS_OF_MEASURE | UOM | 计量单位 |
| `ods_currency` | FND_CURRENCIES | Currency | 币种 |

#### 采购域（PTP）

| ODS 表名 | 对应 ERP 表 | 目标 Tag |
|---------|-----------|---------|
| `ods_purchase_requisition` | PO_REQUISITION_HEADERS_ALL | PurchaseRequisition |
| `ods_purchase_requisition_line` | PO_REQUISITION_LINES_ALL | PurchaseRequisitionLine |
| `ods_purchase_order` | PO_HEADERS_ALL | PurchaseOrder |
| `ods_purchase_order_line` | PO_LINES_ALL | PurchaseOrderLine |
| `ods_receipt` | RCV_SHIPMENT_HEADERS | Receipt |
| `ods_receipt_line` | RCV_SHIPMENT_LINES | ReceiptLine |
| `ods_supplier_qualification` | (自定义表) | SupplierQualification |
| `ods_asl` | PO_APPROVED_SUPPLIER_LIST | (SUPPLIES_ITEM 边) |

#### 应付域

| ODS 表名 | 对应 ERP 表 | 目标 Tag |
|---------|-----------|---------|
| `ods_ap_invoice` | AP_INVOICES_ALL | Invoice |
| `ods_ap_invoice_line` | AP_INVOICE_LINES_ALL | InvoiceLine |
| `ods_ap_payment` | AP_CHECKS_ALL | Payment |
| `ods_ap_payment_batch` | AP_PAYMENT_SCHEDULES_ALL | PaymentBatch |
| `ods_ap_invoice_payment` | AP_INVOICE_PAYMENTS_ALL | (PAYS_INVOICE 边) |

#### 应收域（OTC）

| ODS 表名 | 对应 ERP 表 | 目标 Tag |
|---------|-----------|---------|
| `ods_sales_order` | OE_ORDER_HEADERS_ALL | SalesOrder |
| `ods_sales_order_line` | OE_ORDER_LINES_ALL | SalesOrderLine |
| `ods_shipment` | WSH_DELIVERY_DETAILS | Shipment |
| `ods_shipment_line` | WSH_DELIVERY_ASSIGNMENTS | ShipmentLine |
| `ods_ar_invoice` | RA_CUSTOMER_TRX_ALL | ARInvoice |
| `ods_ar_receipt` | AR_CASH_RECEIPTS_ALL | ARReceipt |
| `ods_ar_receipt_application` | AR_RECEIVABLE_APPLICATIONS_ALL | (APPLIES_TO 边) |

#### 总账/会计域

| ODS 表名 | 对应 ERP 表 | 目标 Tag |
|---------|-----------|---------|
| `ods_gl_account` | GL_CODE_COMBINATIONS | GLAccount |
| `ods_gl_journal` | GL_JE_HEADERS | GLJournalEntry |
| `ods_gl_journal_line` | GL_JE_LINES | GLJournalLine |
| `ods_xla_event` | XLA_EVENTS | XLAEvent |
| `ods_xla_distribution` | XLA_DISTRIBUTION_LINKS | AccountingDistribution |

#### 审批/合同

| ODS 表名 | 对应 ERP 表 | 目标 Tag |
|---------|-----------|---------|
| `ods_approval_record` | (审批流水表) | ApprovalRecord |
| `ods_contract` | OKC_K_HEADERS_ALL_B | Contract |

### 2.2 ODS 表通用结构

每个 ODS 表包含以下标准列：

```sql
-- 以 ods_purchase_order 为例
CREATE TABLE ods_purchase_order (
  -- 业务字段（对应 ERP 源表）
  po_header_id        BIGINT NOT NULL,
  po_number           VARCHAR(64) NOT NULL,
  po_type             VARCHAR(30),
  description         VARCHAR(500),
  status              VARCHAR(30),
  buyer_id            BIGINT,
  buyer_name          VARCHAR(100),
  vendor_id           BIGINT,
  order_date          TIMESTAMP,
  approved_date       TIMESTAMP,
  total_amount        NUMERIC(18,2),
  currency_code       VARCHAR(10),
  payment_terms       VARCHAR(50),
  ship_to_location    VARCHAR(200),
  bill_to_location    VARCHAR(200),
  org_id              BIGINT,

  -- ETL 标准字段
  etl_batch_id        VARCHAR(64) NOT NULL,   -- ETL 批次号
  etl_load_time       TIMESTAMP NOT NULL DEFAULT NOW(),
  source_system       VARCHAR(30) NOT NULL,   -- EBS / CUSTOM_ERP
  source_update_time  TIMESTAMP,              -- 源系统最后更新时间
  is_deleted          BOOLEAN DEFAULT false,  -- 源系统是否已删除
  dq_status           VARCHAR(20) DEFAULT 'pending',  -- pending/passed/failed/quarantined
  dq_errors           JSONB                   -- 质量校验错误详情
);

CREATE INDEX idx_ods_po_batch ON ods_purchase_order(etl_batch_id);
CREATE INDEX idx_ods_po_number ON ods_purchase_order(po_number);
CREATE INDEX idx_ods_po_dq ON ods_purchase_order(dq_status);
```

### 2.3 触发机制

```
方案 A（推荐）：Kafka 消息触发
  同步工具完成后 → 发送 Kafka 消息到 topic: etl-trigger
  消息内容: {"batch_id": "ETL-20260404-001", "tables": ["ods_purchase_order", ...], "timestamp": "..."}
  ETL Pipeline 消费消息后启动处理

方案 B：标记表轮询
  同步工具完成后 → 写入 etl_sync_status 表
  ETL Pipeline 每 5 分钟轮询，发现新批次后启动
```

---

## 3. 数据质量校验（Great Expectations）

### 3.1 校验规则体系

```python
# expectations/purchase_order.py
import great_expectations as gx

def get_po_expectations():
    """采购订单校验规则。"""
    return [
        # 1. 空值检查
        {"type": "expect_column_values_to_not_be_null", "column": "po_number"},
        {"type": "expect_column_values_to_not_be_null", "column": "vendor_id"},
        {"type": "expect_column_values_to_not_be_null", "column": "total_amount"},
        {"type": "expect_column_values_to_not_be_null", "column": "order_date"},
        {"type": "expect_column_values_to_not_be_null", "column": "org_id"},

        # 2. 类型/范围检查
        {"type": "expect_column_values_to_be_between",
         "column": "total_amount", "min_value": 0},
        {"type": "expect_column_values_to_be_in_set",
         "column": "currency_code", "value_set": ["CNY", "USD", "EUR", "JPY", "GBP", "HKD"]},
        {"type": "expect_column_values_to_be_in_set",
         "column": "status",
         "value_set": ["DRAFT", "APPROVED", "OPEN", "CLOSED", "CANCELLED"]},

        # 3. 格式检查
        {"type": "expect_column_values_to_match_regex",
         "column": "po_number", "regex": r"^PO[-/]\S+$"},

        # 4. 唯一性
        {"type": "expect_column_values_to_be_unique", "column": "po_number"},

        # 5. 引用完整性（供应商必须存在）
        {"type": "expect_column_values_to_be_in_set",
         "column": "vendor_id", "value_set": "@existing_supplier_ids"},

        # 6. 时序校验
        {"type": "expect_column_pair_values_A_to_be_greater_than_B",
         "column_A": "approved_date", "column_B": "order_date", "or_equal": True},
    ]
```

### 3.2 引用完整性校验

```python
class ReferentialIntegrityCheck:
    """跨表引用完整性校验。"""

    RULES = {
        "ods_purchase_order.vendor_id": "ods_supplier.vendor_id",
        "ods_purchase_order.buyer_id": "ods_employee.employee_id",
        "ods_purchase_order_line.item_id": "ods_item.inventory_item_id",
        "ods_receipt.po_header_id": "ods_purchase_order.po_header_id",
        "ods_ap_invoice.vendor_id": "ods_supplier.vendor_id",
        "ods_sales_order.customer_id": "ods_customer.customer_id",
        "ods_bom_component.component_item_id": "ods_item.inventory_item_id",
    }

    async def check(self, batch_id: str) -> list[dict]:
        errors = []
        for fk, pk in self.RULES.items():
            fk_table, fk_col = fk.split(".")
            pk_table, pk_col = pk.split(".")

            # 查找悬挂引用
            orphans = await db.execute(f"""
                SELECT t.{fk_col}, count(*) as cnt
                FROM {fk_table} t
                LEFT JOIN {pk_table} p ON t.{fk_col} = p.{pk_col}
                WHERE t.etl_batch_id = '{batch_id}'
                  AND p.{pk_col} IS NULL
                  AND t.{fk_col} IS NOT NULL
                GROUP BY t.{fk_col}
            """)

            if orphans:
                errors.append({
                    "rule": f"{fk} → {pk}",
                    "orphan_count": sum(r['cnt'] for r in orphans),
                    "sample_values": [r[fk_col] for r in orphans[:5]]
                })
        return errors
```

### 3.3 校验结果处理

```
校验结果处理:
  PASSED  → 更新 dq_status='passed'，继续图模型转换
  FAILED  → 分两级:
    WARNING（非关键字段为空等）: 标记 dq_status='passed_with_warnings'，继续处理
    CRITICAL（主键为空/引用断裂等）: 标记 dq_status='quarantined'，移入隔离区

隔离区:
  表名: etl_quarantine
  字段: source_table, source_id, batch_id, error_type, error_detail, created_at
  告警: 隔离记录 > 100 条触发 P2 告警
```

---

## 4. 图模型转换引擎

### 4.1 转换规则定义

```python
# transform/mapping.py

VERTEX_MAPPINGS = {
    "Supplier": {
        "source_table": "ods_supplier",
        "vid_template": "SUP:{vendor_id}",
        "properties": {
            "supplier_number": "vendor_number",
            "supplier_name": "vendor_name",
            "supplier_type": "vendor_type_lookup_code",
            "status": "CASE WHEN end_date_active IS NULL THEN 'ACTIVE' ELSE 'INACTIVE' END",
            "country": "country",
            "city": "city",
            "contact_person": "contact_name",
            "contact_phone": "phone",
            "tax_id": "vat_registration_num",
            "payment_terms": "payment_terms",
            "org_id": "org_id",
            "dept_id": "NULL",          # 供应商无部门
            "data_scope": "'全公司'",
            "source_system": "source_system",
        }
    },
    "PurchaseOrder": {
        "source_table": "ods_purchase_order",
        "vid_template": "PO:{po_number}",
        "properties": {
            "po_number": "po_number",
            "po_type": "po_type",
            "status": "status",
            "buyer": "buyer_name",
            "order_date": "order_date",
            "approved_date": "approved_date",
            "total_amount": "total_amount",
            "currency": "currency_code",
            "payment_terms": "payment_terms",
            "org_id": "org_id",
            "source_system": "source_system",
        }
    },
    # ... 其他 Tag 映射
}

EDGE_MAPPINGS = {
    "PLACED_WITH": {
        "source_table": "ods_purchase_order",
        "src_vid": "PO:{po_number}",
        "dst_vid": "SUP:{vendor_id}",
        "properties": {
            "order_date": "order_date",
            "org_id": "org_id",
        }
    },
    "HAS_PO_LINE": {
        "source_table": "ods_purchase_order_line",
        "src_vid": "PO:{po_number}",
        "dst_vid": "POL:{po_number}-{line_number}",
        "properties": {
            "org_id": "org_id",
        }
    },
    # ... 其他 Edge 映射
}
```

### 4.2 转换执行器

```python
class GraphTransformer:
    """将 ODS 数据转换为 NebulaGraph 导入格式。"""

    def transform_vertices(self, tag: str, batch_id: str) -> str:
        """生成 nebula-importer CSV 文件。"""
        mapping = VERTEX_MAPPINGS[tag]
        sql = self._build_select_sql(mapping, batch_id)
        rows = db.execute(sql)

        output_path = f"import/{batch_id}/vertex_{tag}.csv"
        with open(output_path, 'w') as f:
            # 写入 header
            headers = [":VID"] + list(mapping["properties"].keys())
            f.write(",".join(headers) + "\n")

            for row in rows:
                vid = mapping["vid_template"].format(**row)
                values = [vid] + [str(row.get(v, "")) for v in mapping["properties"].values()]
                f.write(",".join(values) + "\n")

        return output_path

    def transform_edges(self, edge_type: str, batch_id: str) -> str:
        """生成 nebula-importer CSV 文件。"""
        mapping = EDGE_MAPPINGS[edge_type]
        sql = self._build_select_sql(mapping, batch_id)
        rows = db.execute(sql)

        output_path = f"import/{batch_id}/edge_{edge_type}.csv"
        with open(output_path, 'w') as f:
            headers = [":SRC_VID", ":DST_VID"] + list(mapping["properties"].keys())
            f.write(",".join(headers) + "\n")

            for row in rows:
                src = mapping["src_vid"].format(**row)
                dst = mapping["dst_vid"].format(**row)
                values = [src, dst] + [str(row.get(v, "")) for v in mapping["properties"].values()]
                f.write(",".join(values) + "\n")

        return output_path
```

### 4.3 增量 vs 全量策略

| 策略 | 适用场景 | 实现方式 |
|------|---------|---------|
| 全量 | 首次导入、Schema 变更后 | DELETE + INSERT 所有数据 |
| 增量 | 日常 T+1 更新 | 基于 source_update_time 筛选变更数据，UPSERT |

```python
def get_incremental_filter(table: str, batch_id: str) -> str:
    """获取增量数据过滤条件。"""
    last_batch = get_last_successful_batch(table)
    if last_batch:
        return f"source_update_time > '{last_batch.end_time}'"
    else:
        return "1=1"  # 首次全量
```

---

## 5. 导入方式

### 5.1 nebula-importer（推荐）

```yaml
# import/nebula-importer.yaml
version: v3
description: HoneyBadge T+1 Daily Import
removeTempFiles: false

clientSettings:
  retry: 3
  concurrency: 10
  space: honeybadge
  connection:
    address: ${NEBULA_GRAPHD_HOST}:${NEBULA_GRAPHD_PORT}
    user: ${NEBULA_USER}
    password: ${NEBULA_PASSWORD}

sources:
  # Vertex: Supplier
  - path: import/${BATCH_ID}/vertex_Supplier.csv
    csv:
      withHeader: true
      delimiter: ","
    tags:
      - name: Supplier
        id:
          type: STRING
          index: 0
        props:
          - name: supplier_number
            type: STRING
            index: 1
          - name: supplier_name
            type: STRING
            index: 2
          # ... 其他属性

  # Edge: PLACED_WITH
  - path: import/${BATCH_ID}/edge_PLACED_WITH.csv
    csv:
      withHeader: true
    edges:
      - name: PLACED_WITH
        src:
          type: STRING
          index: 0
        dst:
          type: STRING
          index: 1
        props:
          - name: order_date
            type: TIMESTAMP
            index: 2
```

### 5.2 性能参考

| 指标 | 预期值 |
|------|--------|
| 节点导入速率 | ~50,000 条/秒 (nebula-importer) |
| 边导入速率 | ~30,000 条/秒 |
| Phase 1 数据量 | ~100 万节点 + ~500 万边 |
| 预计导入时间 | ~5 分钟 |

---

## 6. 调度

### 6.1 T+1 调度流程

```
每日凌晨 02:00 触发:

  02:00  接收同步完成通知（Kafka / 标记表）
  02:05  启动数据质量校验
  02:30  校验完成，隔离异常数据
  02:35  启动图模型转换
  03:00  转换完成，生成导入文件
  03:05  启动 nebula-importer 导入
  03:30  导入完成
  03:35  执行图完整性巡检
  03:45  更新 ETL 运行状态
  04:00  发送完成通知（成功/失败）
```

### 6.2 调度配置

```python
# 使用 Python APScheduler 或 Cron

# Cron 配置
# 0 2 * * * /opt/honeybadge/etl/run_pipeline.sh >> /var/log/etl/pipeline.log 2>&1
```

---

## 7. 异常处理

### 7.1 隔离区

```sql
CREATE TABLE etl_quarantine (
  id              BIGSERIAL PRIMARY KEY,
  batch_id        VARCHAR(64) NOT NULL,
  source_table    VARCHAR(64) NOT NULL,
  source_id       VARCHAR(128),          -- 源记录主键
  error_type      VARCHAR(30) NOT NULL,  -- null_check / type_check / ref_integrity / business_rule
  error_detail    JSONB NOT NULL,
  severity        VARCHAR(10) NOT NULL,  -- warning / critical
  resolved        BOOLEAN DEFAULT false,
  resolved_by     VARCHAR(64),
  resolved_at     TIMESTAMP,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_quarantine_batch ON etl_quarantine(batch_id);
CREATE INDEX idx_quarantine_unresolved ON etl_quarantine(resolved, created_at DESC);
```

### 7.2 告警规则

| 条件 | 级别 | 通知方式 |
|------|------|---------|
| 隔离记录 > 100 条 / 批次 | P2 | 邮件 / 企业微信 |
| 关键表校验失败率 > 5% | P1 | 邮件 / 企业微信 / 短信 |
| ETL 超过 26 小时未执行 | P1 | 邮件 / 企业微信 |
| 导入失败 | P1 | 邮件 / 企业微信 |
| 数据新鲜度超期（latest_update > 2 天） | P2 | 邮件 |

### 7.3 ETL 运行状态表

```sql
CREATE TABLE etl_run_log (
  id              BIGSERIAL PRIMARY KEY,
  batch_id        VARCHAR(64) NOT NULL UNIQUE,
  status          VARCHAR(20) NOT NULL,  -- running / success / failed / partial
  start_time      TIMESTAMP NOT NULL,
  end_time        TIMESTAMP,
  total_records   BIGINT,
  passed_records  BIGINT,
  failed_records  BIGINT,
  quarantined     BIGINT,
  import_duration_sec INT,
  error_summary   JSONB,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```
