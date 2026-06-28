---
name: multi-step-analysis
description: Use when the user asks for analysis that requires decomposing a complex question into multiple queries (trend analysis, comparisons, aggregation across entities)
---

# Multi-Step Analysis Skill

## How to Run Analysis (CRITICAL)

Call the Python analysis modules:

```bash
# Decompose a complex question into sub-queries
python3 -m multi_step_analysis.lib.decompose --question "对比2025年和2026年Q1的采购金额变化"

# Cross-reference results from multiple rounds
python3 -m multi_step_analysis.lib.decompose cross-reference \
  --results-dir /tmp/mcp_results/
```

## Execution Flow

### Step 1: Decompose
```bash
python3 -m multi_step_analysis.lib.decompose --question "<QUESTION>"
```
Breaks the complex question into 2-5 sub-queries with round numbers.

### Step 2: Execute Sub-queries
For each sub-query: use `common.mcp_client` to generate_query -> validate_and_execute.

### Step 3: Cross-reference Results
```bash
python3 -m multi_step_analysis.lib.decompose cross-reference --results-dir /tmp/
```
Finds patterns, trends, or anomalies across sub-query results.

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
