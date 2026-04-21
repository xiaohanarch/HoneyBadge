# Inventory Ontology

> **Purpose**: Inventory movements and item categorization. Physical warehouse entity is in `master-data.md`.
> **Keywords**: inventory, 库存, 物料事务, transaction, 出入库, 调拨, transfer, 盘点, cycle count, 杂发, 杂收, 分类, category, 物料分类
> **Tags**: `InventoryTransaction` (🆕v2.0), `ItemCategory` (🆕v2.0)
> **Edges**: `INV_TXN_FOR_ITEM` (🆕), `INV_TXN_AT` (🆕), `INV_TXN_SOURCE` (🆕), `ITEM_IN_CATEGORY` (🆕), `PARENT_CATEGORY` (🆕)

---

## Entities

### InventoryTransaction 🆕v2.0
- **vid**: `INVTX:{transaction_id}`
- **source**: `MTL_MATERIAL_TRANSACTIONS`
- **key props**: `transaction_id STRING`, `transaction_type STRING`, `transaction_date TIMESTAMP`, `quantity DOUBLE`, `uom STRING`, `transaction_cost DOUBLE`, `source_type STRING`, `source_id STRING`
- **transaction_type enum**:
  - `PO_RECEIPT` — 采购入库
  - `PO_RETURN` — 采购退货
  - `SALES_ISSUE` — 销售出库
  - `SALES_RETURN` — 销售退货
  - `SUBINVENTORY_TRANSFER` — 子库存转移
  - `INTER_ORG_TRANSFER` — 组织间转移
  - `CYCLE_COUNT_ADJ` — 盘点调整
  - `MISC_RECEIPT` / `MISC_ISSUE` — 杂收/杂发
  - `WIP_ISSUE` / `WIP_RECEIPT` — 生产领料/入库
- **semantics**: Every physical movement of material. Fraud watch: frequent large `MISC_ISSUE` or `CYCLE_COUNT_ADJ` without approvals.

### ItemCategory 🆕v2.0
- **vid**: `CAT:{category_id}`
- **source**: `MTL_CATEGORIES_B` + `MTL_CATEGORY_SETS`
- **key props**: `category_id STRING`, `category_set_name STRING`, `segment1 STRING`, `segment2 STRING`, `description STRING`
- **semantics**: Multi-dimensional classification — items can belong to multiple categories for purchasing, inventory, costing views.

---

## Relationships

| edge | direction | key attrs | semantics |
|------|-----------|-----------|-----------|
| `INV_TXN_FOR_ITEM` 🆕 | InventoryTransaction → Item | — | |
| `INV_TXN_AT` 🆕 | InventoryTransaction → Warehouse | — | |
| `INV_TXN_SOURCE` 🆕 | InventoryTransaction → Receipt / Shipment | — | 事务来源单据 |
| `ITEM_IN_CATEGORY` 🆕 | Item → ItemCategory | — | |
| `PARENT_CATEGORY` 🆕 | ItemCategory → ItemCategory | — | 分类层级 |

---

## Business Rules

- **R-INV-1** (P2 HIGH): Inventory balance — for any Item × Warehouse: `SUM(InventoryTransaction.quantity signed by type)` should equal reported on-hand (with `PO_RECEIPT`, `MISC_RECEIPT`, `SALES_RETURN` = +qty; `SALES_ISSUE`, `MISC_ISSUE`, `PO_RETURN` = -qty).
- **R-INV-2** (P1 CRITICAL — fraud): `CYCLE_COUNT_ADJ` with `|quantity * transaction_cost| > 500,000` OR frequency >5 per warehouse per 30 days = inventory fraud signal.
- **R-INV-3** (P2 HIGH — fraud): `MISC_ISSUE` without an `APPROVAL_FOR → ApprovalRecord` (see `master-data.md`) for the movement.
- **R-INV-4** (P3 MEDIUM): `INTER_ORG_TRANSFER` volumes should be symmetric (outflow from org A = inflow to org B) within 7 days.
- **R-INV-5** (P2 HIGH): Items with active POs but `is_active = false` or `status = 'OBSOLETE'` = control violation.

---

## Example Queries

### Q: 某物料近 30 天的库存变动
```ngql
MATCH (tx:InventoryTransaction)-[:INV_TXN_FOR_ITEM]->(i:Item)
WHERE i.Item.item_number == "ITEM-001234"
  AND tx.InventoryTransaction.transaction_date > now() - 30 * 86400
MATCH (tx)-[:INV_TXN_AT]->(w:Warehouse)
RETURN tx.InventoryTransaction.transaction_type,
       tx.InventoryTransaction.transaction_date,
       tx.InventoryTransaction.quantity,
       w.Warehouse.warehouse_name
ORDER BY tx.InventoryTransaction.transaction_date;
```

### Q: 大额盘点调整（R-INV-2）
```ngql
MATCH (tx:InventoryTransaction)
WHERE tx.InventoryTransaction.transaction_type == "CYCLE_COUNT_ADJ"
  AND abs(tx.InventoryTransaction.quantity * tx.InventoryTransaction.transaction_cost) > 500000
MATCH (tx)-[:INV_TXN_AT]->(w:Warehouse)
MATCH (tx)-[:INV_TXN_FOR_ITEM]->(i:Item)
RETURN tx.InventoryTransaction.transaction_id,
       tx.InventoryTransaction.transaction_date,
       i.Item.item_number, w.Warehouse.warehouse_name,
       tx.InventoryTransaction.quantity,
       tx.InventoryTransaction.quantity * tx.InventoryTransaction.transaction_cost AS value_impact;
```

### Q: 杂发无审批（R-INV-3）
```ngql
MATCH (tx:InventoryTransaction)
WHERE tx.InventoryTransaction.transaction_type == "MISC_ISSUE"
  AND tx.InventoryTransaction.quantity * tx.InventoryTransaction.transaction_cost > 50000
WHERE NOT EXISTS {
  MATCH (ap:ApprovalRecord)-[:APPROVAL_FOR]->(tx2)
  WHERE ap.ApprovalRecord.doc_number == tx.InventoryTransaction.transaction_id
}
RETURN tx.InventoryTransaction.transaction_id,
       tx.InventoryTransaction.transaction_date,
       tx.InventoryTransaction.quantity * tx.InventoryTransaction.transaction_cost AS value;
```

### Q: 物料分类树
```ngql
MATCH (i:Item)-[:ITEM_IN_CATEGORY]->(c:ItemCategory)
WHERE i.Item.item_number == "ITEM-001234"
OPTIONAL MATCH path = (c)-[:PARENT_CATEGORY*1..5]->(root:ItemCategory)
RETURN c.ItemCategory.description AS leaf_category,
       [n IN nodes(path) | n.ItemCategory.description] AS path_to_root;
```

---

## Query Hints

- "库存事务" / "inventory transaction" → `InventoryTransaction`.
- "盘点" / "cycle count" → `transaction_type = 'CYCLE_COUNT_ADJ'`.
- "杂发" / "杂收" → `MISC_ISSUE` / `MISC_RECEIPT`.
- "调拨" / "transfer" → `SUBINVENTORY_TRANSFER` / `INTER_ORG_TRANSFER`.
- "物料分类" → `ItemCategory` + `ITEM_IN_CATEGORY`.
- "某库存事务来自哪张单据" → `INV_TXN_SOURCE` → Receipt/Shipment.
