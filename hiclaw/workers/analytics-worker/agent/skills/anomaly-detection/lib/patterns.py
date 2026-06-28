"""Threshold constants and pattern definitions for anomaly detection.

Values derived from the original anomaly-detection/SKILL.md prose.
"""

# Three-way matching: flag if Invoice amount > PO amount x 1.10 (10% tolerance)
THREE_WAY_TOLERANCE = 1.10

# Duplicate invoices: flag groups with count > 1
DUPLICATE_INVOICE_COUNT = 1

# Unusual payments: flag payments > 2x supplier's historical average
PAYMENT_DEVIATION_FACTOR = 2.0

# New supplier threshold: registration < 90 days
NEW_SUPPLIER_DAYS = 90

# Supplier concentration: flag if any single supplier > 60% of category spend
SUPPLIER_CONCENTRATION = 0.60

# Severity thresholds for three-way mismatch
# WARNING at 10% over, ALERT at 30% over
THREE_WAY_WARNING_RATIO = 1.10
THREE_WAY_ALERT_RATIO = 1.30
