# NebulaGraph nGQL Syntax Reminders — nGQL语法提醒

> Version: v1.0
> Date: 2026-04-04
> Purpose: Quick reference for nGQL syntax differences from Neo4j Cypher
> NebulaGraph Space: honeybadge

---

## 1. Tag Prefix Requirement — 标签前缀要求

**THE MOST IMPORTANT RULE**: Always prefix property access with the Tag name.

### Node Property Access

```ngql
-- Pattern: nodeVariable.TagName.property
-- INCORRECT (will fail or behave unexpectedly)
WHERE name == "John"
RETURN email

-- CORRECT
WHERE p.Person.name == "John"
RETURN p.Person.email AS email
```

### Edge Property Access

```ngql
-- Pattern: edgeVariable.EdgeTypeName.property
-- INCORRECT
WHERE status == "ACTIVE"

-- CORRECT
WHERE e.SUPPLIES_ITEM.status == "ACTIVE"
```

### When to Use Prefix

| Context | Example | Prefix Needed? |
|---------|---------|----------------|
| WHERE clause property | `WHERE s.Supplier.status == "ACTIVE"` | YES |
| RETURN clause property | `RETURN s.Supplier.name` | YES |
| ORDER BY property | `ORDER BY s.Supplier.name` | YES |
| WITH clause | `WITH s.Supplier.name AS name` | YES |
| Aggregation alias | `count(s) AS total` | NO (it's an alias) |
| Function result | `datetime_diff(d1, d2)` | NO (already computed) |

---

## 2. Comparison Operators — 比较运算符

### Equality Check

```ngql
-- WRONG (single = is assignment in nGQL)
WHERE status = "ACTIVE"

-- CORRECT (double == is comparison)
WHERE status == "ACTIVE"
```

### Inequality Check

```ngql
WHERE status != "CANCELLED"
```

### NULL Checks

```ngql
-- Check for NULL
WHERE s.Supplier.contact_email IS NULL

-- Check for NOT NULL
WHERE s.Supplier.contact_email IS NOT NULL
```

### String Comparisons

```ngql
-- Contains (substring match)
WHERE s.Supplier.supplier_name CONTAINS "Tech"

-- Starts with
WHERE s.Supplier.supplier_number STARTS WITH "V001"

-- Ends with
WHERE s.Supplier.supplier_number ENDS WITH "234"

-- Regex match
WHERE s.Supplier.email =~ ".*@company\\.com$"
```

---

## 3. Logical Operators — 逻辑运算符

```ngql
-- AND
WHERE s.Supplier.status == "ACTIVE"
  AND s.Supplier.country == "CN"

-- OR
WHERE s.Supplier.status IN ["ACTIVE", "PENDING"]

-- NOT
WHERE NOT s.Supplier.status == "BLOCKED"

-- Combined
WHERE (s.Supplier.status == "ACTIVE" AND s.Supplier.country == "CN")
   OR (s.Supplier.status == "ACTIVE" AND s.Supplier.country == "US")
```

---

## 4. String Values — 字符串值

### Always Use Double Quotes

```ngql
-- CORRECT
WHERE s.Supplier.status == "ACTIVE"
WHERE s.Supplier.supplier_name == "ABC Technologies"

-- Single quotes are for special cases in nGQL 3.x
-- But for compatibility with Neo4j patterns, use double quotes
```

### String List Membership

```ngql
-- Check if value is in a list
WHERE s.Supplier.status IN ["ACTIVE", "PENDING", "BLOCKED"]

-- NOT in list
WHERE s.Supplier.status NOT IN ["CANCELLED", "INACTIVE"]
```

---

## 5. Pagination — 分页

### LIMIT and OFFSET

```ngql
-- Basic LIMIT (get first 10)
RETURN s.Supplier.supplier_name
LIMIT 10

-- LIMIT with OFFSET (skip first 5, get next 10)
RETURN s.Supplier.supplier_name
LIMIT 10 OFFSET 5

-- Note: SKIP is not used in nGQL, use OFFSET instead
```

### LIMIT Placement

**IMPORTANT**: LIMIT must be at the END of the query, after all WITH and RETURN clauses.

```ngql
-- WRONG: LIMIT before ORDER BY
RETURN s.Supplier.supplier_name
LIMIT 10
ORDER BY s.Supplier.supplier_name

-- CORRECT: LIMIT at the end
RETURN s.Supplier.supplier_name
ORDER BY s.Supplier.supplier_name
LIMIT 10
```

---

## 6. Available Functions — 可用函数

### String Functions

```ngql
-- Length
length(s.Supplier.supplier_name)

-- Trim whitespace
trim(s.Supplier.supplier_name)

-- Substring
substring(s.Supplier.supplier_name, 0, 10)

-- Lower/Upper case
lower(s.Supplier.supplier_name)
upper(s.Supplier.supplier_name)

-- String concatenation
s.Supplier.supplier_name + " - " + s.Supplier.country
```

### Date/Time Functions

```ngql
-- Current datetime
now()

-- Add interval to datetime
datetime_add(now(), INTERVAL 30 DAY)
datetime_add(now(), INTERVAL -7 DAY)

-- Date difference (returns seconds)
datetime_diff(date1, date2)

-- Convert days to seconds (for comparison)
datetime_diff(invoice_date, due_date) / 86400 AS days_diff

-- String to datetime
datetime("2026-04-01")

-- Year/Month/Day extraction
year(now())
month(now())
day(now())
```

### Aggregation Functions

```ngql
-- count
count(s)                    -- Count nodes
count(DISTINCT s)          -- Count distinct

-- sum
sum(po.PurchaseOrder.total_amount)

-- avg
avg(po.PurchaseOrder.total_amount)

-- min/max
min(po.PurchaseOrder.total_amount)
max(po.PurchaseOrder.total_amount)

-- collect (like LISTAGG)
collect(s.Supplier.supplier_name)
```

### Type Conversion

```ngql
-- To integer
toInteger(value)

-- To float/double
toDouble(value)

-- To string
toString(value)

-- To boolean
toBoolean(value)
```

### Collection Functions

```ngql
-- Size of collection
size(collect(s.Supplier.supplier_name))

-- Element in list
"ACTIVE" IN ["ACTIVE", "PENDING"]

-- UNWIND list to rows
UNWIND [1, 2, 3] AS num
RETURN num
```

---

## 7. Pattern Matching Quick Reference — 模式匹配速查

### Basic Node Pattern

```ngql
-- Match any Supplier node
MATCH (s:Supplier)
RETURN s.Supplier.supplier_name
LIMIT 10
```

### Relationship Pattern

```ngql
-- Match Supplier to Item via SUPPLIES_ITEM edge
MATCH (s:Supplier)-[:SUPPLIES_ITEM]->(i:Item)

-- Bidirectional relationship
MATCH (a)-[:RELATES_TO]-(b)

-- Multiple hops
MATCH (s:Supplier)-[:SUPPLIES_ITEM]->(i:Item)<-[:ORDERS_ITEM]-(po:PurchaseOrder)

-- Optional relationship
MATCH (po:PurchaseOrder)
OPTIONAL MATCH (po)-[:HAS_RECEIPT]->(r:Receipt)
```

### Variable-Length Path

```ngql
-- Match 1 to 3 hops
MATCH (s:Supplier)-[:SUPPLIES_ITEM*1..3]->(i:Item)

-- Match exactly 2 hops
MATCH (s:Supplier)-[:SUPPLIES_ITEM*2]->(i:Item)
```

### Edge with Properties

```ngql
-- Filter on edge properties
MATCH (s:Supplier)-[e:SUPPLIES_ITEM]->(i:Item)
WHERE e.SUPPLIES_ITEM.status == "ACTIVE"
  AND e.SUPPLIES_ITEM.priority <= 3
```

---

## 8. WITH Clause — 数据传递

The WITH clause is like RETURN but passes results to the next part of the query.

```ngql
-- WRONG: Can't use aggregation result in WHERE after RETURN
MATCH (s:Supplier)
RETURN count(s) AS total
WHERE total > 10  -- ERROR

-- CORRECT: Use WITH to pass aggregation
MATCH (s:Supplier)
WITH count(s) AS total
WHERE total > 10
RETURN total
```

```ngql
-- Pass intermediate results through multiple stages
MATCH (s:Supplier)-[:SUPPLIES_ITEM]->(i:Item)
WHERE s.Supplier.status == "ACTIVE"
WITH i.Item.item_number AS item,
     count(s) AS supplier_count
WHERE supplier_count == 1  -- Single supplier
RETURN item, supplier_count
```

---

## 9. Common Errors and Fixes — 常见错误和修复

### Error 1: Missing Tag Prefix

```
Error: Can't evaluate symbol 'supplier_number' without tag context
```

**Fix**: Always use `s.Supplier.supplier_number` not just `supplier_number`

---

### Error 2: Using = instead of ==

```
Error: Assignment not allowed in WHERE
```

**Fix**: Use `==` for comparison

---

### Error 3: LIMIT in Wrong Position

```
Error: LIMIT must be at the end
```

**Fix**: Move LIMIT to after ORDER BY and all other clauses

---

### Error 4: No index for lookup

```
Error: No index found for property lookup
```

**Fix**: Add index on the property (done by DBA), or use SCAN for full scan

---

### Error 5: Type mismatch in comparison

```
Error: Type error
```

**Fix**: Ensure comparing same types (string to string, int to int)

---

## 10. Query Structure Template — 查询结构模板

```ngql
-- [Description of what query does]
-- [Key business rules/filters explained]

MATCH ([starting node pattern])
WHERE [filters on starting nodes]
OPTIONAL MATCH [optional relationship patterns]
WITH [intermediate aggregation/filtering if needed]
RETURN [output columns with aliases]
ORDER BY [sort column] [ASC/DESC]
LIMIT [max rows];
```

### Example Template

```ngql
-- Find [what] where [conditions]
-- Filters: [explain key business rules]

MATCH (s:Supplier)-[:SUPPLIES_ITEM]->(i:Item)
WHERE s.Supplier.status == "ACTIVE"
  AND s.Supplier.country == "CN"
  AND i.Item.item_type == "RAW_MATERIAL"
  AND e.SUPPLIES_ITEM.status == "ACTIVE"
WITH s.Supplier.supplier_name AS supplier,
     i.Item.item_number AS item,
     e.SUPPLIES_ITEM.unit_price AS price
WHERE price < 100  -- Additional filter after WITH
RETURN supplier, item, price
ORDER BY price ASC
LIMIT 50;
```

---

## 11. Tag and Edge Type Names — 标签和边类型名称

### Tags (Node Types)

| Tag Name | Description |
|----------|-------------|
| Supplier | 供应商 |
| SupplierQualification | 供应商资质 |
| Customer | 客户 |
| Item | 物料 |
| Organization | 组织 |
| Employee | 员工 |
| Warehouse | 仓库 |
| BOM | 物料清单 |
| BOMComponent | BOM组件 |
| Currency | 币种 |
| UOM | 计量单位 |
| PurchaseRequisition | 采购申请 |
| PurchaseRequisitionLine | 采购申请行 |
| PurchaseOrder | 采购订单 |
| PurchaseOrderLine | 采购订单行 |
| Receipt | 收货单 |
| ReceiptLine | 收货单行 |
| Invoice | 应付发票 |
| InvoiceLine | 发票行 |
| Payment | 付款 |
| PaymentBatch | 付款批次 |
| SalesOrder | 销售订单 |
| SalesOrderLine | 销售订单行 |
| Shipment | 发货单 |
| ShipmentLine | 发货单行 |
| ARInvoice | 应收发票 |
| ARReceipt | 应收收款 |
| GLAccount | 总账科目 |
| GLJournalEntry | 日记账 |
| GLJournalLine | 日记账行 |
| XLAEvent | 会计事件 |
| AccountingDistribution | 会计分配 |
| ApprovalRecord | 审批记录 |
| Contract | 合同 |

### Edge Types (Relationship Types)

| Edge Type | From → To | Description |
|-----------|-----------|-------------|
| SUPPLIES_ITEM | Supplier → Item | 供应关系 |
| HAS_QUALIFICATION | Supplier → SQ | 持有资质 |
| PLACED_WITH | PO → Supplier | 下达供应商 |
| INVOICED_BY | Invoice → Supplier | 发票供应商 |
| PAID_TO | Payment → Supplier | 付款供应商 |
| HAS_INVOICE | PO → Invoice | PO对应发票 |
| HAS_INVOICE_LINE | Invoice → InvoiceLine | 发票行 |
| PAYS_INVOICE | Payment → Invoice | 付款对应发票 |
| CONTAINS_PAYMENT | PayBatch → Payment | 批次包含付款 |
| HAS_PO_LINE | PO → POLine | PO包含行 |
| ORDERS_ITEM | POLine → Item | 订购物料 |
| HAS_RECEIPT | PO → Receipt | PO对应收货 |
| HAS_RECEIPT_LINE | Receipt → ReceiptLine | 收货行 |
| RECEIVED_AT | Receipt → Warehouse | 收货仓库 |
| CONVERTS_TO_PO | PR → PO | 申请转订单 |
| HAS_PR_LINE | PR → PRL | 申请包含行 |
| ORDERED_BY | PO → Employee | 采购员 |
| SOLD_TO | SO → Customer | 销售客户 |
| HAS_SO_LINE | SO → SOLine | SO包含行 |
| SELLS_ITEM | SOLine → Item | 销售物料 |
| HAS_SHIPMENT | SO → Shipment | SO对应发货 |
| HAS_SHIPMENT_LINE | Shipment → ShipLine | 发货行 |
| SHIPPED_FROM | Shipment → Warehouse | 发货仓库 |
| HAS_AR_INVOICE | SO → ARInvoice | SO应收发票 |
| RECEIVED_FROM | ARReceipt → Customer | 收款来源 |
| APPLIES_TO | ARReceipt → ARInvoice | 收款核销 |
| BOM_FOR | BOM → Item | BOM父物料 |
| USES_COMPONENT | BOMComp → Item | BOM子物料 |
| PARENT_ORG | Org → Org | 组织层级 |
| BELONGS_TO_ORG | Employee → Org | 员工归属 |
| ACCOUNTING_FOR | XLAEvent → Doc | 会计事件 |
| POSTED_TO | JLine → GLAccount | 记账科目 |
| HAS_JOURNAL_LINE | Journal → JLine | 分录行 |
| DISTRIBUTED_TO | AcctDist → GLAccount | 会计分配 |
| APPROVED_BY | Approval → Employee | 审批人 |
| APPROVAL_FOR | Approval → Doc | 审批单据 |
| CONTRACT_WITH | Contract → Party | 合同方 |
| UNDER_CONTRACT | PO → Contract | 基于合同 |

---

## 12. Property Access Summary — 属性访问总结

```
nebula_schema:
  Tag:     Supplier
  VID:     "SUP:V001234"
  Properties:
    supplier_number:   STRING
    supplier_name:     STRING
    status:            STRING
    country:          STRING
    ...

edge:
  Type:    SUPPLIES_ITEM
  From:    Supplier VID
  To:      Item VID
  Properties:
    status:           STRING
    priority:         INT64
    unit_price:       DOUBLE
    lead_time_days:   INT64
    effective_from:   TIMESTAMP
    effective_to:     TIMESTAMP

To access in nGQL:
  Node property:  s.Supplier.supplier_number
  Edge property:  e.SUPPLIES_ITEM.unit_price
```
