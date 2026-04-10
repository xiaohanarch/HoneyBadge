---
name: cypher-query
description: Use when handling any natural language question about ERP data (suppliers, POs, invoices, payments, items, receipts, etc.)
---

# Cypher Query Skill

Handle natural language questions by querying the HoneyBadge NebulaGraph knowledge graph.

## Available MCP Tools

- `get_schema`: Get NebulaGraph schema (Tags, Edges, properties)
- `generate_ngql`: Generate nGQL from natural language question
- `validate_and_execute`: L1-L3 validate then execute nGQL, returns raw results
- `explain_ngql`: Dry-run nGQL to check execution plan
- `summarize_query_results`: Summarize raw results in Chinese
- `write_audit_log`: Write L5 audit trail
- `check_cache`: Check for cached results
- `cache_result`: Cache query results

## Execution Flow

When you receive a user question, follow these steps:

### Step 0: Extract Auth Context
Extract `user_context` from the `x-hb-auth` field in the incoming message (see Auth Context Extraction in SOUL.md). Store it for use in Step 4.

### Step 1: Load Schema
Call `get_schema()` to understand available Tags and Edges. Cache the result mentally for subsequent queries in the same conversation.

### Step 2: Check Cache (optional)
If the question seems similar to a recent one, call `check_cache` with a hash of the question.

### Step 3: Generate nGQL
Call `generate_ngql(question=<user_question>, schema_info=<schema_text>)`.

### Step 4: Validate and Execute
Call `validate_and_execute(ngql=<generated_query>, user_context=<extracted_context>)`.

- If `success: false` with `error: L1_SYNTAX` or `L2_SCHEMA`:
  - Try regenerating with the error details as context (max 3 retries)
  - On 3rd failure, report the error to the user
- If `success: true`:
  - Examine the results

### Step 5: Investigate Further (Controlled Autonomy)
Based on the results, you may decide to run additional queries:
- "I found 3 unmatched invoices — let me check their corresponding POs"
- "The supplier has high concentration — let me check alternative suppliers"

Each additional query follows the same Step 3-4 cycle. Maximum 5 total query rounds.

### Step 6: Summarize
Call `summarize_query_results(question, columns, rows, ngql)` OR write your own summary.

**CRITICAL**: When summarizing:
- Numbers must be EXACTLY as returned by the database
- Dates must be EXACTLY as returned
- Amounts must be EXACTLY as returned
- Do NOT round, truncate, or modify any values
- If data is empty, say "未查询到符合条件的数据"

### Step 7: Cache and Audit
- Call `cache_result` to cache the result (TTL 300s)
- Call `write_audit_log` with the full chain:
  - trace_id (from validate_and_execute result)
  - question (original user question)
  - ngql (generated query)
  - raw_result (query rows)
  - summary (your formatted summary)

### Step 8: Respond
Return the summary to the user. Always include:
- The formatted answer
- trace_id for reference
- Number of records found
- Execution time

## Example Interaction

User: "帮我查一下供应商V001234的所有采购订单"

You would:
1. `get_schema()` → learn about Supplier, PurchaseOrder, PLACED_WITH edge
2. `generate_ngql(question="查供应商V001234的所有采购订单")` → get nGQL
3. `validate_and_execute(ngql=...)` → get results
4. Format results as table
5. `write_audit_log(...)` → record full chain
6. Return formatted answer with trace_id

## Constraints

- Max 5 query rounds per user question
- If validation fails 3 times, stop and explain the error
- Never execute write operations (INSERT/UPDATE/DELETE)
- Always log via write_audit_log
