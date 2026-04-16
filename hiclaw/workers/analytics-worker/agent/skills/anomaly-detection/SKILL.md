---
name: anomaly-detection
description: Use when the user asks about fraud detection, three-way matching anomalies, duplicate invoices, unusual payment patterns, or supplier concentration risk
---

# Anomaly Detection Skill

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
mcporter call honeybadge-cache.cache_result --args '{"key":"...","value":{...},"ttl":300}'
```

## Detection Patterns

### Three-Way Matching (PO vs Receipt vs Invoice)
1. Query PO amounts per line
2. Query Receipt quantities per PO
3. Query Invoice amounts per PO
4. Compare: flag where Invoice amount > PO amount × 1.10 (10% tolerance)

### Duplicate Invoice Detection
1. Query invoices grouped by (supplier, amount, invoice_date)
2. Flag groups with count > 1

### Unusual Payment Patterns
1. Query payments in last 90 days
2. Flag payments > 2× supplier's historical average
3. Flag payments to new suppliers (registration < 90 days) above threshold

### Supplier Concentration Risk
1. Query total spend per supplier for a category
2. Flag if any single supplier > 60% of category spend

## Execution Flow

1. Identify which detection pattern matches the question
2. Execute relevant sub-queries (2-5 rounds)
3. Apply flagging logic based on data returned
4. Present findings with severity:
   - **INFO**: Within normal range
   - **WARNING**: Exceeds soft threshold
   - **ALERT**: Exceeds hard threshold
5. Write audit log with full evidence chain

## CRITICAL

- Thresholds are approximate guidelines — flagging is based on actual query data
- Never state "fraud detected" — only flag anomalies for human review
- Always show the specific data that triggered each flag
