---
name: multi-step-analysis
description: Use when the user asks for analysis that requires decomposing a complex question into multiple queries (trend analysis, comparisons, aggregation across entities)
---

# Multi-Step Analysis Skill

## Available MCP Tools

Same as cypher-query skill: get_schema, generate_ngql, validate_and_execute, summarize_query_results, write_audit_log, check_cache, cache_result.

## Execution Flow

### Step 1: Decompose the Question
Break the user's complex question into 2-5 sub-queries. Example:

User: "对比2025年和2026年Q1的采购金额变化"
Sub-queries:
1. Query 2025 Q1 total PO amounts by month
2. Query 2026 Q1 total PO amounts by month
3. Compare results

### Step 2: Execute Sub-queries
For each sub-query, follow the generate → validate → execute cycle.

### Step 3: Cross-reference Results
Analyze results across sub-queries to find patterns, trends, or anomalies.

### Step 4: Synthesize Summary
Combine all findings into a coherent analysis report. Use tables for comparisons.

**CRITICAL**: All numbers in the report must come directly from query results. Do NOT calculate new values that weren't in the database.

### Step 5: Audit
Write a single audit log entry that captures all sub-queries and the final analysis.

## Constraints

- Maximum 8 query rounds per analysis
- Always show evidence (which query produced which data)
- Mark any anomaly with severity: INFO / WARNING / ALERT
