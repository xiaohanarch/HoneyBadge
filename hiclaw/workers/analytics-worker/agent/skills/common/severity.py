"""Severity classification for anomaly detection."""
from enum import Enum


class Severity(str, Enum):
    """Anomaly severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ALERT = "ALERT"


def classify(value: float, soft_threshold: float, hard_threshold: float) -> Severity:
    """Classify a value against soft and hard thresholds.

    Args:
        value: The measured value (e.g., invoice amount ratio).
        soft_threshold: Value at or above this triggers WARNING.
        hard_threshold: Value at or above this triggers ALERT.

    Returns:
        Severity.INFO if below soft_threshold,
        Severity.WARNING if at/above soft but below hard,
        Severity.ALERT if at/above hard_threshold.
    """
    if value >= hard_threshold:
        return Severity.ALERT
    if value >= soft_threshold:
        return Severity.WARNING
    return Severity.INFO
