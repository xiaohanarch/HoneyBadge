---
name: anomaly-detection
description: Use when the user asks about fraud detection, three-way matching anomalies, duplicate invoices, unusual payment patterns, or supplier concentration risk
---

# Anomaly Detection Skill

## How to Run Detection (CRITICAL)

Call the Python detection modules instead of raw mcporter CLI:

```bash
# Three-way matching (PO vs Receipt vs Invoice)
python3 -m anomaly_detection.lib.detect three-way --po-id "PO-2026-001"

# Duplicate invoice detection
python3 -m anomaly_detection.lib.detect duplicate-invoices --supplier-id "S001"

# Unusual payment patterns (last 90 days)
python3 -m anomaly_detection.lib.detect unusual-payments --days 90

# Supplier concentration risk
python3 -m anomaly_detection.lib.detect supplier-concentration --category "IT"
```

## Detection Patterns

Pattern definitions and thresholds are in `lib/patterns.py`.
Implementation is in `lib/detect.py`.

### Three-Way Matching (PO vs Receipt vs Invoice)
- Tolerance: Invoice > PO x 1.10 -> WARNING
- Alert: Invoice > PO x 1.30 -> ALERT

### Duplicate Invoice Detection
- Flag: groups with count > 1

### Unusual Payment Patterns
- Warning: payment > 2x historical average
- Alert: payment > 3x historical average

### Supplier Concentration Risk
- Warning: supplier > 60% of category spend
- Alert: supplier > 80% of category spend

## Execution Flow

1. Identify which detection pattern matches the question
2. Call the corresponding Python module
3. Review returned anomalies (already deduplicated by AnomalyTracker)
4. Present findings with severity levels
5. Audit log is written by the detection module

## CRITICAL

- Thresholds are in `lib/patterns.py` -- do not hardcode in prompts
- Never state "fraud detected" -- only flag anomalies for human review
- Always show the specific data that triggered each flag
