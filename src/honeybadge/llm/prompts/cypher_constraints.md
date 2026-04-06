# NebulaGraph nGQL Syntax Constraints

## Overview

This document provides detailed syntax constraints for nGQL (NebulaGraph Query Language), specifically highlighting differences from Neo4j Cypher that are commonly confused.

## Critical Syntax Differences from Cypher

### 1. Property Access - Tag Prefix Required

In nGQL, **all property access must include the Tag prefix**.

```ngql
-- Correct (with Tag prefix)
n.Supplier.supplier_name
n.PurchaseOrder.po_number
n.Item.item_description

-- Incorrect (missing Tag prefix - this will cause errors)
n.supplier_name
n.po_number
```

### 2. Comparison Operators - Use Double Equals

```ngql
-- Correct
WHERE n.Supplier.supplier_name == "Acme Corp"
WHERE n.PurchaseOrder.total_amount > 10000

-- Incorrect (single equals is assignment in nGQL)
WHERE n.Supplier.supplier_name = "Acme Corp"
```

### 3. Pagination Syntax

```ngql
-- Correct (nGQL style)
LIMIT 10 OFFSET 5

-- Incorrect (Neo4j Cypher style)
SKIP 5 LIMIT 10
```

### 4. Path Operations

```ngql
-- Shortest path (nGQL specific syntax)
FIND SHORTEST PATH FROM "SUP001" TO "SUP002" OVER * BIDIRECT UPTO 5 STEPS

-- Equivalent in Cypher would be different MATCH patterns
```

### 5. Tag Inspection

```ngql
-- Correct (nGQL)
WHERE tags(n) == ["Supplier"]

-- Incorrect (Cypher style)
WHERE labels(n) == ["Supplier"]
```

### 6. NULL Checks

```ngql
-- Correct (Tag prefix required)
WHERE n.Supplier.contact_email IS NOT NULL

-- Incorrect
WHERE n.contact_email IS NOT NULL
```

## Write Operation Restrictions

The following operations are **FORBIDDEN** for query generation:

| Operation | Reason |
|-----------|--------|
| INSERT | Write operation - not allowed |
| UPDATE | Write operation - not allowed |
| UPSERT | Write operation - not allowed |
| DELETE | Write operation - not allowed |
| DROP | Schema modification - not allowed |
| CREATE | Schema modification - not allowed |
| ALTER | Schema modification - not allowed |
| INSERT VERTEX | Write operation - not allowed |
| INSERT EDGE | Write operation - not allowed |

## Required Query Components

### LIMIT Clause

Every query **must include LIMIT** to prevent excessive result sets:

```ngql
-- Always required (default 100)
LIMIT 100

-- Unless user specifies otherwise
LIMIT 50

-- Or for aggregate queries where full result is needed
LIMIT 1000
```

### Tag and Edge Naming

- Tags use `PascalCase`: `Supplier`, `PurchaseOrder`, `ItemMaster`
- Edges use `UPPER_SNAKE_CASE`: `SUPPLIES`, `PURCHASED_BY`, `DELIVERED_TO`

```ngql
-- Tag reference in pattern
MATCH (n:Supplier)

-- Edge reference
MATCH (n:Supplier)-[:SUPPLIES]->(m:Item)

-- Property access (ALWAYS with prefix)
WHERE n.Supplier.supplier_name == "Acme Corp"
```

## Common Error Patterns

### Pattern 1: Missing Tag Prefix in WHERE

```ngql
-- WRONG
MATCH (n:Supplier)
WHERE supplier_name == "Acme Corp"  -- Missing Tag prefix

-- CORRECT
MATCH (n:Supplier)
WHERE n.Supplier.supplier_name == "Acme Corp"
```

### Pattern 2: Using Single Equals

```ngql
-- WRONG
WHERE n.Item.price = 100

-- CORRECT
WHERE n.Item.price == 100
```

### Pattern 3: Using SKIP Instead of OFFSET

```ngql
-- WRONG
MATCH (n:PurchaseOrder) RETURN n LIMIT 10 SKIP 10

-- CORRECT
MATCH (n:PurchaseOrder) RETURN n LIMIT 10 OFFSET 10
```

### Pattern 4: Missing LIMIT on Large Traversals

```ngql
-- WRONG (can return huge result set)
MATCH (n:Supplier)-[:SUPPLIES]->(m:Item)<-[:PURCHASED]-(p:PO)

-- CORRECT
MATCH (n:Supplier)-[:SUPPLIES]->(m:Item)<-[:PURCHASED]-(p:PO)
LIMIT 100
```

## Query Complexity Limits

| Limit Type | Maximum Value |
|------------|---------------|
| Traversal depth | 5 hops |
| Result set size | 100 rows (default LIMIT) |
| String length | Varies by storage |
| IN list size | 1000 items |

## Video ID (VID) References

When referencing vertices by VID, use string format:

```ngql
-- Correct
FETCH PROP ON Supplier "SUP001"

-- Using VID in patterns
MATCH (n:Supplier)-[:SUPPLIES]->(m:Item)
WHERE n.Supplier.supplier_id == "SUP001"
```

## Schema Validation

Before generating queries, always validate against the current schema:

- Tag names must exist in the schema
- Edge types must exist in the schema
- Property names must exist on the specified Tag/Edge
- Property types must match the comparison/value type
