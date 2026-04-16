---
name: cypher-query
description: Use when handling any natural language question about ERP data (suppliers, POs, invoices, payments, items, receipts, etc.)
---

# Cypher Query Skill

Handle natural language questions by querying the HoneyBadge NebulaGraph knowledge graph.

## How to Call MCP Tools (CRITICAL)

You call MCP tools via the `exec` tool using the `mcporter` CLI. **All MCP tools are on separate servers:**

**nebula-mcp** (honeybadge-nebula):
```
mcporter call honeybadge-nebula.generate_query --args '{"question":"..."}'
mcporter call honeybadge-nebula.validate_and_execute --args '{"ngql":"...","user_context":{"user_id":"..."}}'
mcporter call honeybadge-nebula.get_schema --args '{"space":"honeybadge"}'
mcporter call honeybadge-nebula.explain_ngql --args '{"ngql":"..."}'
mcporter call honeybadge-nebula.summarize_query_results --args '{"question":"...","columns":[...],"rows":[...]}'
```

**audit-mcp** (honeybadge-audit):
```
mcporter call honeybadge-audit.write_audit_log --args '{"trace_id":"...","question":"...","ngql":"...","raw_result":{...},"summary":"..."}'
```

**cache-mcp** (honeybadge-cache):
```
mcporter call honeybadge-cache.check_cache --args '{"key":"..."}'
mcporter call honeybadge-cache.cache_result --args '{"key":"...","value":{...},"ttl":300}'
```

## Execution Flow

### Step 1: Generate nGQL
Call `mcporter call honeybadge-nebula.generate_query --args '{"question":"<user_question>"}'`

### Step 2: Validate and Execute
Call `mcporter call honeybadge-nebula.validate_and_execute --args '{"ngql":"<generated_ngql>"}'`
- If user_id is available: add `"user_context":{"user_id":"<username>"}`

On failure (L1/L2 error), retry up to 3 times with error details.

### Step 3: Investigate Further (max 5 rounds total)
Based on results, run additional queries following Step 1-2.

### Step 4: Summarize
Format results as a table. **Numbers must be EXACTLY as returned.**

### Step 5: Cache and Audit
```
mcporter call honeybadge-cache.cache_result --args '{"key":"<question_hash>","value":{...},"ttl":300}'
mcporter call honeybadge-audit.write_audit_log --args '{"trace_id":"...","question":"...","ngql":"...","raw_result":{...},"summary":"..."}'
```

### Step 6: Respond
Return summary with trace_id, row count, execution time.

## Example

User: "查供应商V001234的所有采购订单"

```
mcporter call honeybadge-nebula.generate_query --args '{"question":"查供应商V001234的所有采购订单"}'
→ ngql: "MATCH (s:Supplier)-[:PLACED_WITH]->(po:PurchaseOrder) WHERE s.Supplier.supplier_id == \"V001234\" RETURN po.purchase_order_number AS po_no, po.status AS status, po.total_amount AS amount"
mcporter call honeybadge-nebula.validate_and_execute --args '{"ngql":"MATCH (s:Supplier)-[:PLACED_WITH]->(po:PurchaseOrder) WHERE s.Supplier.supplier_id == \"V001234\" RETURN po.purchase_order_number AS po_no, po.status AS status, po.total_amount AS amount"}'
→ {success: true, rows: [...], trace_id: "TRC-..."}
```

## Constraints

- Max 5 query rounds per question
- Never fabricate data
- Never execute write operations (INSERT/UPDATE/DELETE)
