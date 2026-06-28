"""Unit tests for severity classification."""
import pytest
from common.severity import Severity, classify


class TestSeverityEnum:
    def test_severity_values(self):
        assert Severity.INFO == "INFO"
        assert Severity.WARNING == "WARNING"
        assert Severity.ALERT == "ALERT"

    def test_severity_is_string_enum(self):
        assert isinstance(Severity.INFO, str)


class TestClassify:
    def test_returns_info_when_below_soft_threshold(self):
        result = classify(value=50, soft_threshold=100, hard_threshold=200)
        assert result == Severity.INFO

    def test_returns_warning_at_soft_threshold(self):
        result = classify(value=100, soft_threshold=100, hard_threshold=200)
        assert result == Severity.WARNING

    def test_returns_warning_between_thresholds(self):
        result = classify(value=150, soft_threshold=100, hard_threshold=200)
        assert result == Severity.WARNING

    def test_returns_alert_at_hard_threshold(self):
        result = classify(value=200, soft_threshold=100, hard_threshold=200)
        assert result == Severity.ALERT

    def test_returns_alert_above_hard_threshold(self):
        result = classify(value=300, soft_threshold=100, hard_threshold=200)
        assert result == Severity.ALERT

    def test_works_with_float_thresholds(self):
        result = classify(value=1.05, soft_threshold=1.0, hard_threshold=1.10)
        assert result == Severity.WARNING
