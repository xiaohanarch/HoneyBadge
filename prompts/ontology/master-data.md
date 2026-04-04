# Master Data Ontology — 主数据本体

> Version: v1.0
> Date: 2026-04-04
> Domain: Master Data — 主数据
> NebulaGraph Space: honeybadge

---

## 1. Entity Definitions — 实体定义

### 1.1 Item (物料主数据)

**Business Meaning (业务含义)**:
The Item master is the central product/catalog definition used across procurement, inventory, sales, and manufacturing. Every Item has a unique item_number that serves as the primary key across all business processes.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `item_number` | STRING NOT NULL | Unique identifier (e.g., "ITEM-001234") |
| `item_name` | STRING NOT NULL | Display name |
| `item_description` | STRING | Detailed description |
| `item_type` | STRING | RAW_MATERIAL (原材料) / FINISHED_GOOD (成品) / SEMI_FINISHED (半成品) / SERVICE (服务) / EXPENSE (费用) / CONSUMABLE (消耗品) |
| `category` | STRING | User-defined category for spend/revenue analysis |
| `uom` | STRING | Primary unit of measure (EA/KG/M/L) |
| `standard_cost` | DOUBLE | Standard cost for inventory valuation |
| `list_price` | DOUBLE | Catalog list price |
| `weight` | DOUBLE | Item weight |
| `weight_uom` | STRING | Weight unit of measure |
| `lead_time_days` | INT64 | Manufacturing or procurement lead time |
| `safety_stock` | DOUBLE | Minimum inventory buffer level |
| `min_order_qty` | DOUBLE | Minimum order quantity |
| `status` | STRING | ACTIVE / INACTIVE / OBSOLETE |
| `abc_class` | STRING | A / B / C inventory classification (A=high value, C=low value) |

**ABC Classification Business Meaning**:
- **A Items**: High value, low volume — tight control, frequent inventory counts
- **B Items**: Medium value, medium volume — moderate control
- **C Items**: Low value, high volume — loose control, periodic counts

**VID Format**: `ITEM:{item_number}` (e.g., `ITEM:ITEM-001234`)

---

### 1.2 BOM (物料清单, Bill of Materials)

**Business Meaning (业务含义)**:
Defines the relationship between a parent item (finished product) and its component items. BOMs are used for:
1. Manufacturing planning (what components needed to make finished goods)
2. Cost rollup (calculate total cost of finished goods from component costs)
3. Supply chain impact analysis (if a component is unavailable, what finished goods are affected)

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `bom_number` | STRING NOT NULL | Unique identifier |
| `bom_name` | STRING | Descriptive name |
| `bom_type` | STRING | STANDARD (标准BOM) / ENGINEERING (工程BOM) / PLANNING (计划BOM) |
| `effective_from` | TIMESTAMP | Start date this BOM is valid |
| `effective_to` | TIMESTAMP | End date (NULL = no expiry) |
| `quantity` | DOUBLE DEFAULT 1.0 | Base quantity this BOM produces |
| `uom` | STRING | Unit of measure for the base quantity |
| `status` | STRING | ACTIVE / INACTIVE / DRAFT |

**VID Format**: `BOM:{bom_number}` (e.g., `BOM:BOM-FG-001`)

---

### 1.3 BOMComponent (BOM组件行)

**Business Meaning (业务含义)**:
Individual component within a BOM, specifying which Item is used and in what quantity.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `component_seq` | INT64 | Sequence number for line ordering |
| `quantity_per` | DOUBLE NOT NULL | Quantity of this component needed per BOM base quantity |
| `uom` | STRING | Unit of measure of component |
| `effective_from` | TIMESTAMP | Component effective start date |
| `effective_to` | TIMESTAMP | Component effective end date |
| `yield_rate` | DOUBLE DEFAULT 1.0 | Expected yield (1.0 = 100% usable) |
| `wip_supply_type` | STRING | PUSH (推式) / PULL (拉式) / PHANTOM (幽灵件) |

**WIP Supply Type Meaning**:
- **PUSH**: Component is issued to WIP based on BOM requirements
- **PULL**: Component is issued based on actual production consumption (Kanban)
- **PHANTOM**: Component is not tracked as separate inventory (assembled into parent)

**VID Format**: `BOMC:{bom_number}:{component_seq}` (e.g., `BOMC:BOM-FG-001:1`)

---

### 1.4 Organization (组织)

**Business Meaning (业务含义)**:
The organizational hierarchy defines legal entities, business units, departments, and cost centers. All transactions (POs, SOs, invoices) are associated with an Organization for:
1. Profit and loss reporting by entity
2. Cost center tracking
3. Data access control (users can only see data for their org)

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `org_code` | STRING NOT NULL | Unique identifier |
| `org_name` | STRING NOT NULL | Display name |
| `org_type` | STRING | COMPANY (公司) / BUSINESS_UNIT (业务单元) / DEPARTMENT (部门) / COST_CENTER (成本中心) |
| `parent_org_code` | STRING | Parent org in the hierarchy |
| `legal_entity` | STRING | Legal entity name for regulatory reporting |
| `country` | STRING | Country of operations |
| `city` | STRING | City |
| `status` | STRING | ACTIVE / INACTIVE |

**Organization Hierarchy Example**:
```
ABC Corporation (COMPANY)
  └── Manufacturing BU (BUSINESS_UNIT)
        └── Production Dept (DEPARTMENT)
              └── Assembly Cost Center (COST_CENTER)
  └── Sales BU (BUSINESS_UNIT)
        └── China Sales Dept (DEPARTMENT)
              └── East Region Cost Center (COST_CENTER)
```

**VID Format**: `ORG:{org_code}` (e.g., `ORG:ORG-CN-001`)

---

### 1.5 Employee (员工)

**Business Meaning (业务含义)**:
Employee master data for:
1. PO buyers (who created the PO)
2. Requesters (who initiated PRs)
3. Approvers (who approved documents)
4. Salespersons (who own customer relationships)

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `employee_number` | STRING NOT NULL | Unique identifier (e.g., "EMP-001234") |
| `employee_name` | STRING NOT NULL | Full name |
| `position` | STRING | Job title/position |
| `department` | STRING | Department name |
| `email` | STRING | Corporate email |
| `phone` | STRING | Phone number |
| `manager_id` | STRING | Employee number of direct manager (for approval hierarchy) |
| `hire_date` | TIMESTAMP | Date of hire |
| `status` | STRING | ACTIVE / INACTIVE / TERMINATED |

**VID Format**: `EMP:{employee_number}` (e.g., `EMP:EMP-001234`)

---

### 1.6 Warehouse (仓库)

**Business Meaning (业务含义)**:
Physical locations where inventory is stored. Different warehouse types support different business scenarios.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `warehouse_code` | STRING NOT NULL | Unique identifier |
| `warehouse_name` | STRING NOT NULL | Display name |
| `warehouse_type` | STRING | MAIN (主仓库) / SUB (分仓库) / TRANSIT (在途仓库) / RETURN (退货仓库) |
| `location` | STRING | Physical address |
| `capacity` | DOUBLE | Storage capacity |
| `status` | STRING | ACTIVE / INACTIVE |

**Warehouse Type Business Meaning**:
- **MAIN**: Primary inventory storage
- **SUB**: Regional or satellite warehouse
- **TRANSIT**: Goods in transit between locations
- **RETURN**: Designated for customer returns processing

**VID Format**: `WH:{warehouse_code}` (e.g., `WH:WH-CN-SH-001`)

---

### 1.7 Currency (币种)

**Business Meaning (业务含义)**:
Currency master for multi-currency transactions.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `currency_code` | STRING NOT NULL | ISO currency code (e.g., "CNY", "USD", "EUR") |
| `currency_name` | STRING | Full name |
| `symbol` | STRING | Currency symbol (¥, $, €) |
| `decimal_places` | INT64 DEFAULT 2 | Decimal precision |
| `is_base_currency` | BOOL DEFAULT false | Is this the company's base currency |

**VID Format**: `CUR:{currency_code}` (e.g., `CUR:CNY`)

---

### 1.8 UOM (计量单位, Unit of Measure)

**Business Meaning (业务含义)**:
Units of measure for quantities in procurement, inventory, and sales.

**Core Attributes (核心属性)**:
| Attribute | Type | Description |
|-----------|------|-------------|
| `uom_code` | STRING NOT NULL | Code (e.g., "EA", "KG", "M", "L") |
| `uom_name` | STRING | Full name (e.g., "Each", "Kilogram", "Meter", "Liter") |
| `uom_class` | STRING | QUANTITY (数量) / WEIGHT (重量) / LENGTH (长度) / VOLUME (体积) |
| `base_uom` | STRING | Base unit for conversion within same class |
| `conversion_rate` | DOUBLE DEFAULT 1.0 | Conversion factor to base UOM |

**VID Format**: `UOM:{uom_code}` (e.g., `UOM:KG`)

---

## 2. Relationship Definitions — 关系定义

### 2.1 BOM_FOR (BOM对应父物料)

**Direction**: BOM → Item (parent item)

**Business Meaning (业务含义)**:
Links a BOM definition to the parent (finished) Item it produces. One Item can have multiple BOMs (for different configurations or manufacturing routes).

---

### 2.2 USES_COMPONENT (BOM使用子物料)

**Direction**: BOMComponent → Item (component item)

**Business Meaning (业务含义)**:
Links a BOMComponent to the Item being used as a component.

**BOM Structure**:
```
Parent Item ← BOM_FOR ← BOM
                              ↑
                              └── BOMComponent ← USES_COMPONENT ← Component Item
```

---

### 2.3 PARENT_ORG (上级组织)

**Direction**: Organization → Organization (parent org)

**Business Meaning (业务含义)**:
Expresses the organizational hierarchy. Allows traversal up/down the org tree.

---

### 2.4 BELONGS_TO_ORG (员工归属组织)

**Direction**: Employee → Organization

**Business Meaning (业务含义)**:
Links an employee to the Organization they belong to. A buyer can only create POs within their Organization.

---

### 2.5 SUPPLIES_ITEM (供应商供应物料)

**Direction**: Supplier → Item

**Business Meaning**: See supplier.md — this relationship is in the Supplier domain but links to Item master.

---

### 2.6 ORDERS_ITEM / SELLS_ITEM (PO/SO行关联物料)

**Direction**: POLine/SOLine → Item

**Business Meaning**: Links procurement or sales lines to the Item master.

---

## 3. BOM Expansion Queries — BOM展开查询

### 3.1 Single-Level BOM Query (单层BOM展开)

```ngql
-- Get direct components of a parent item
MATCH (parent:Item)<-[:BOM_FOR]-(bom:BOM),
      (bc:BOMComponent)-[:USES_COMPONENT]->(child:Item)
WHERE parent.Item.item_number == "FG-001"
  AND bom.BOM.effective_from <= now()
  AND (bom.BOM.effective_to IS NULL OR bom.BOM.effective_to >= now())
RETURN parent.Item.item_number AS parent_item,
       parent.Item.item_name AS parent_name,
       bc.BOMComponent.component_seq AS seq,
       child.Item.item_number AS component,
       child.Item.item_name AS component_name,
       bc.BOMComponent.quantity_per AS qty_per,
       child.Item.uom AS uom,
       child.Item.item_type AS component_type;
```

---

### 3.2 Multi-Level BOM Expansion (多层BOM递归展开)

```ngql
-- Expand BOM to multiple levels (e.g., 3 levels deep)
-- Shows all sub-components recursively
MATCH (parent:Item)<-[:BOM_FOR]-(bom:BOM),
      (bom)-[:HAS_COMPONENTS*1..3]->(child:Item)
WHERE parent.Item.item_number == "FG-001"
RETURN parent.Item.item_number AS top_level_item,
       parent.Item.item_number AS level_0,  -- Would need pathunnesting in real query
       child.Item.item_number AS component,
       child.Item.item_name AS component_name,
       child.Item.item_type AS item_type
-- Note: Full recursive BOM expansion requires more complex path handling in nGQL
```

---

### 3.3 BOM Cost Rollup (BOM成本滚加)

```ngql
-- Calculate total material cost of a finished good
-- Sums component costs multiplied by quantities
MATCH (parent:Item)<-[:BOM_FOR]-(bom:BOM),
      (bc:BOMComponent)-[:USES_COMPONENT]->(child:Item)
WHERE parent.Item.item_number == "FG-001"
  AND bom.BOM.effective_from <= now()
  AND (bom.BOM.effective_to IS NULL OR bom.BOM.effective_to >= now())
WITH parent.Item.item_number AS item,
     parent.Item.item_name AS name,
     child.Item.standard_cost AS component_cost,
     bc.BOMComponent.quantity_per AS qty_per,
     (child.Item.standard_cost * bc.BOMComponent.quantity_per) AS line_cost
RETURN item,
       name,
       sum(line_cost) AS total_material_cost,
       collect({
         component: child.Item.item_number,
         cost: component_cost,
         qty: qty_per,
         line_cost: line_cost
       }) AS component_breakdown;
```

---

## 4. Supply Chain Impact Analysis — 供应链影响分析

### 4.1 Supplier Disruption Impact (供应商断供影响分析)

**Business Context**: When a supplier is blocked or experiences production issues, we need to identify which finished goods will be affected.

```ngql
-- Find finished goods that depend on a specific supplier for raw materials
-- Trace through: Supplier → RAW Item → BOM → Finished Good
MATCH (s:Supplier)-[:SUPPLIES_ITEM]->(raw:Item)
WHERE s.Supplier.supplier_number == "V001234"
  AND s.Supplier.status == "ACTIVE"
  AND raw.Item.item_type == "RAW_MATERIAL"
WITH s.Supplier.supplier_name AS supplier_name,
     raw.Item.item_number AS raw_material,
     raw.Item.item_name AS material_name
-- Find BOMs that use this raw material as a component
MATCH (raw)<-[:USES_COMPONENT]-(bc:BOMComponent)-[:BELONGS_TO]->(bom:BOM)
MATCH (bom)-[:BOM_FOR]->(fg:Item)
WHERE fg.Item.item_type == "FINISHED_GOOD"
  AND fg.Item.status == "ACTIVE"
WITH supplier_name,
     raw_material,
     material_name,
     fg.Item.item_number AS finished_good,
     fg.Item.item_name AS fg_name,
     bc.BOMComponent.quantity_per AS qty_needed
RETURN supplier_name,
       raw_material,
       material_name,
       finished_good,
       fg_name,
       qty_needed
ORDER BY fg_name, raw_material;
```

---

### 4.2 Component Shortage Impact (物料短缺影响分析)

**Business Context**: When a raw material is in shortage, identify which finished goods will be affected.

```ngql
-- Find finished goods that use a specific component
-- Used for shortage planning or substitute identification
MATCH (comp:Item)<-[:USES_COMPONENT]-(bc:BOMComponent)-[:BELONGS_TO]->(bom:BOM)-[:BOM_FOR]->(fg:Item)
WHERE comp.Item.item_number == "RM-001"
  AND fg.Item.status == "ACTIVE"
  AND (bom.BOM.effective_from IS NULL OR bom.BOM.effective_from <= now())
  AND (bom.BOM.effective_to IS NULL OR bom.BOM.effective_to >= now())
RETURN comp.Item.item_number AS component,
       fg.Item.item_number AS affected_finished_good,
       fg.Item.item_name AS fg_name,
       fg.Item.category AS category,
       bc.BOMComponent.quantity_per AS qty_per_bom,
       fg.Item.safety_stock AS safety_stock,
       fg.Item.standard_cost AS fg_cost;
```

---

### 4.3 Customer Dependency Analysis (客户依赖度分析)

**Business Context**: Understand revenue risk — what percentage of revenue comes from top customers.

```ngql
-- Analyze revenue concentration by customer
-- Calculate each customer's share of total revenue
MATCH (so:SalesOrder)-[:SOLD_TO]->(c:Customer)
WHERE so.SalesOrder.status IN ["INVOICED", "CLOSED"]
  AND so.SalesOrder.order_date >= datetime_add(now(), INTERVAL -365 DAY)
WITH c.Customer.customer_number AS customer_number,
     c.Customer.customer_name AS customer_name,
     sum(so.SalesOrder.total_amount) AS total_revenue
WITH collect({customer: customer_name, revenue: total_revenue}) AS all_customers,
     sum(total_revenue) AS total_company_revenue
UNWIND all_customers AS cust
WITH cust.customer AS customer_name,
     cust.revenue AS revenue,
     total_company_revenue,
     (cust.revenue / total_company_revenue * 100) AS revenue_share_pct
WHERE revenue_share_pct > 5  -- Only show customers with >5% share
RETURN customer_name,
       revenue,
       round(revenue_share_pct, 2) AS share_pct,
       CASE
         WHEN revenue_share_pct > 30 THEN "CRITICAL_CONCENTRATION"
         WHEN revenue_share_pct > 15 THEN "HIGH_CONCENTRATION"
         ELSE "MODERATE"
       END AS risk_level
ORDER BY revenue_share_pct DESC;
```

---

## 5. Example nGQL Queries — nGQL 查询示例

### Query 1: Item Search by Category (按类别搜索物料)

**Business Context**: Procurement team searches for all raw materials in a specific category for sourcing review.

```ngql
-- Find all ACTIVE raw materials in a category
MATCH (i:Item)
WHERE i.Item.item_type == "RAW_MATERIAL"
  AND i.Item.category == "Electronic Components"
  AND i.Item.status == "ACTIVE"
RETURN i.Item.item_number AS item_number,
       i.Item.item_name AS item_name,
       i.Item.uom AS uom,
       i.Item.standard_cost AS standard_cost,
       i.Item.lead_time_days AS lead_time,
       i.Item.safety_stock AS safety_stock
ORDER BY item_number
LIMIT 50;
```

---

### Query 2: Organization Hierarchy Traversal (组织层级遍历)

**Business Context**: HR system needs to find all cost centers under a business unit for budget reporting.

```ngql
-- Find all organizations under a parent (e.g., "BU-CN-MFG")
-- Traverse the org hierarchy
MATCH (parent:Organization)-[:PARENT_ORG*1..5]->(child:Organization)
WHERE parent.Organization.org_code == "BU-CN-MFG"
  AND child.Organization.status == "ACTIVE"
RETURN parent.Organization.org_name AS top_org,
       child.Organization.org_code AS child_org_code,
       child.Organization.org_name AS child_org_name,
       child.Organization.org_type AS org_type,
       length(path) AS level  -- Would need path in actual query
ORDER BY level, org_type;
```

---

### Query 3: Employee Reporting Chain (员工汇报链)

**Business Context**: Approval routing needs to find the manager chain for an employee.

```ngql
-- Trace manager hierarchy for an employee
-- Used for approval workflow routing
MATCH (emp:Employee)-[:REPORTS_TO*1..5]->(mgr:Employee)
WHERE emp.Employee.employee_number == "EMP-001234"
  AND mgr.Employee.status == "ACTIVE"
RETURN emp.Employee.employee_name AS employee,
       mgr.Employee.employee_name AS manager,
       mgr.Employee.position AS manager_position,
       length(path) AS level_up
ORDER BY level_up;
```

---

### Query 4: Warehouse Inventory Snapshot (仓库库存快照)

**Business Context**: Inventory manager reviews stock levels across warehouses for a critical item.

```ngql
-- Note: This requires inventory transaction data linked to warehouse
-- Query pattern for items stored in specific warehouses
MATCH (wh:Warehouse)<-[:RECEIVED_AT]-(r:Receipt)-[:HAS_RECEIPT_LINE]->(rl:ReceiptLine),
      (r)<-[:HAS_RECEIPT]-(po:PurchaseOrder)-[:HAS_PO_LINE]->(pol:PurchaseOrderLine)-[:ORDERS_ITEM]->(i:Item)
WHERE i.Item.item_number == "ITEM-001234"
  AND wh.Warehouse.status == "ACTIVE"
  AND r.Receipt.status IN ["RECEIVED", "PARTIALLY_RECEIVED"]
-- Calculate total received quantity by warehouse
WITH wh.Warehouse.warehouse_code AS warehouse,
     wh.Warehouse.warehouse_name AS warehouse_name,
     sum(rl.ReceiptLine.accepted_quantity) AS total_received,
     count(DISTINCT r.Receipt.receipt_number) AS receipt_count
RETURN warehouse,
       warehouse_name,
       total_received,
       receipt_count
ORDER BY total_received DESC;
```

---

### Query 5: Multi-Level BOM Full Expansion (多层BOM完整展开)

**Business Context**: Engineering wants to see the complete multi-level bill of materials for a finished product to understand sub-assembly dependencies.

```ngql
-- Multi-level BOM expansion with path tracking
-- Shows complete product structure from raw materials to finished goods
MATCH path = (parent:Item)<-[:BOM_FOR]-(bom:BOM)
         -[:HAS_COMPONENTS*1..3]->(comp:Item)
WHERE parent.Item.item_number == "FG-001"
  AND parent.Item.status == "ACTIVE"
  -- Filter for effective BOMs
  AND (bom.BOM.effective_from IS NULL OR bom.BOM.effective_from <= now())
  AND (bom.BOM.effective_to IS NULL OR bom.BOM.effective_to >= now())
WITH nodes(path) AS path_nodes,
     parent.Item.item_number AS top_level
-- Extract item numbers from path (simplified representation)
UNWIND path_nodes AS node
WITH top_level,
     CASE
       WHEN node.Item.item_number IS NOT NULL THEN "Item"
       WHEN node.BOM.bom_number IS NOT NULL THEN "BOM"
       ELSE "BOMComponent"
     END AS node_type,
     coalesce(node.Item.item_number, node.BOM.bom_number) AS identifier,
     coalesce(node.Item.item_name, node.BOM.bom_name) AS name
-- Note: Actual implementation would need more sophisticated path parsing
RETURN top_level, identifier, name, node_type
LIMIT 200;
```

---

### Query 6: UOM Conversion Lookup (单位换算查询)

**Business Context**: System needs to convert quantities between UOMs for a transaction.

```ngql
-- Find UOM conversion factors within a UOM class
-- Example: Convert between KG and LB (both WEIGHT class)
MATCH (uom1:UOM)-[:CONVERTS_TO]->(uom2:UOM)
WHERE uom1.UOM.uom_class == "WEIGHT"
  AND uom1.UOM.uom_code IN ["KG", "LB", "G"]
WITH uom1.UOM.uom_code AS from_uom,
     uom2.UOM.uom_code AS to_uom,
     uom1.UOM.conversion_rate AS conversion_factor
-- Calculate converted quantity
-- Example: 100 KG to LB (factor: 1 KG = 2.20462 LB)
RETURN from_uom,
       to_uom,
       conversion_factor,
       100 AS example_qty,
       (100 * conversion_factor) AS converted_qty;
```

---

### Query 7: ABC Inventory Classification Analysis (ABC库存分类分析)

**Business Context**: Inventory manager wants to understand the distribution of items by ABC class and their inventory value contribution.

```ngql
-- Analyze inventory value distribution by ABC class
-- Shows how A (high value) items contribute to total inventory value
MATCH (i:Item)
WHERE i.Item.status == "ACTIVE"
  AND i.Item.item_type IN ["RAW_MATERIAL", "FINISHED_GOOD", "SEMI_FINISHED"]
  AND i.Item.standard_cost IS NOT NULL
  AND i.Item.standard_cost > 0
WITH i.Item.abc_class AS abc_class,
     i.Item.item_number AS item_number,
     i.Item.item_name AS item_name,
     i.Item.standard_cost AS unit_cost,
     -- Estimate annual usage/frequency (would come from transaction data)
     100 AS estimated_annual_usage,  -- Placeholder
     (i.Item.standard_cost * 100) AS estimated_inventory_value
WITH abc_class,
     count(*) AS item_count,
     sum(estimated_inventory_value) AS class_value,
     collect({item: item_number, value: estimated_inventory_value}) AS top_items
WITH abc_class,
     item_count,
     class_value,
     class_value / sum(class_value) OVER () * 100 AS value_share_pct,
     top_items[0..5] AS top_5_items  -- Top 5 by value
RETURN abc_class,
       item_count,
       round(class_value, 2) AS total_value,
       round(value_share_pct, 1) AS value_share_pct,
       top_5_items
ORDER BY value_share_pct DESC;
```

---

## 6. Summary Table — 汇总表

| Entity | VID Format | Description |
|--------|------------|-------------|
| Item | `ITEM:{item_number}` | Product/material master |
| BOM | `BOM:{bom_number}` | Bill of materials header |
| BOMComponent | `BOMC:{bom_number}:{seq}` | BOM component line |
| Organization | `ORG:{org_code}` | Organizational hierarchy |
| Employee | `EMP:{employee_number}` | Employee master |
| Warehouse | `WH:{warehouse_code}` | Storage locations |
| Currency | `CUR:{currency_code}` | Currency definitions |
| UOM | `UOM:{uom_code}` | Unit of measure |

| Relationship | Direction | Description |
|--------------|-----------|-------------|
| BOM_FOR | BOM → Item | BOM produces parent item |
| USES_COMPONENT | BOMComponent → Item | Component used in BOM |
| PARENT_ORG | Org → Org | Organizational hierarchy |
| BELONGS_TO_ORG | Employee → Org | Employee belongs to org |
| SUPPLIES_ITEM | Supplier → Item | Supplier approved for item |
| ORDERS_ITEM | POLine → Item | PO orders item |
| SELLS_ITEM | SOLine → Item | SO sells item |
| RECEIVED_AT | Receipt → Warehouse | Goods received at warehouse |
| SHIPPED_FROM | Shipment → Warehouse | Goods shipped from warehouse |

---

## 7. Key Business Rules — 关键业务规则

1. **BOM Effective Dating**: Only BOMs where `effective_from <= current_date <= effective_to` should be used in planning
2. **Organization Data Scope**: All transaction data must be associated with an Organization for reporting and access control
3. **Item Status**: Only ACTIVE items can be used in new POs or SOs
4. **UOM Consistency**: Quantities in POLine, ReceiptLine, and InvoiceLine should use the same UOM for a given Item
5. **Employee-Org Association**: Buyers can only create POs under their assigned Organization
