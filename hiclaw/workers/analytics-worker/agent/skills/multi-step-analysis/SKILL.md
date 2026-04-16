---
name: multi-step-analysis
description: Use when the user asks for analysis that requires decomposing a complex question into multiple queries (trend analysis, comparisons, aggregation across entities)
---

# Multi-Step Analysis Skill

## How to Call MCP Tools (CRITICAL)

You call MCP tools via the `exec` tool using the `mcporter` CLI.

**nebula-mcp** (honeybadge-nebula):
```
mcporter call honeybadge-nebula.generate_query --args '{"question":"..."}'
mcporter call honeybadge-nebula.validate_and_execute --args '{"ngql":"...","user_context":{"user_id":"..."}}'
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

### Step 1: Decompose
Break the complex question into 2-5 sub-queries.

Example: "对比2025年和2026年Q1的采购金额变化"
- Sub 1: Query 2025 Q1 PO amounts by month
- Sub 2: Query 2026 Q1 PO amounts by month
- Sub 3: Compare results

### Step 2: Execute Sub-queries
For each sub-query: generate_query → validate_and_execute

### Step 3: Cross-reference Results
Find patterns, trends, or anomalies across sub-queries.

### Step 4: Synthesize
Present findings with severity levels:
- **INFO**: Within normal range
- **WARNING**: Exceeds soft threshold
- **ALERT**: Exceeds hard threshold

**CRITICAL**: All numbers must come directly from query results. Do NOT calculate values not in the database.

### Step 5: Audit
Write one audit log entry capturing all sub-queries and the final analysis.

## Constraints

- Max 8 query rounds per analysis
- Always show evidence (which query produced which data)
- Mark anomalies with severity level
