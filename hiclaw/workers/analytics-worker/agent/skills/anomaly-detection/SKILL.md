---
name: anomaly-detection
description: Use when the user asks about fraud detection, three-way matching anomalies, duplicate invoices, unusual payment patterns, or supplier concentration risk
---

# Anomaly Detection Skill

## Detection Patterns

### Three-Way Matching (PO vs Receipt vs Invoice)
1. Query PO amounts per line
2. Query Receipt quantities per PO
3. Query Invoice amounts per PO
4. Compare: flag where Invoice amount > PO amount * 1.10 (10% tolerance)

### Duplicate Invoice Detection
1. Query invoices grouped by (supplier, amount, invoice_date)
2. Flag groups with count > 1

### Unusual Payment Patterns
1. Query payments in last 90 days
2. Flag payments significantly above supplier's average (>2x)
3. Flag payments to new suppliers (registration < 90 days) above threshold

### Supplier Concentration Risk
1. Query total spend per supplier for a category
2. Flag if any single supplier > 60% of category spend

## Execution Flow

1. Identify which detection pattern matches the user's question
2. Execute the relevant queries (2-5 rounds)
3. Apply the flagging logic based on query results
4. Present findings with severity levels:
   - **INFO**: Within normal range but worth noting
   - **WARNING**: Exceeds soft threshold, needs review
   - **ALERT**: Exceeds hard threshold, requires immediate attention
5. Write audit log with all evidence

## CRITICAL

- All thresholds are approximate guidelines. The actual flagging is based on data returned by queries.
- Never state "fraud detected" — only flag anomalies that need human review.
- Always show the specific data that triggered the flag.
