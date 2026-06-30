"""Unit tests for anomaly detection patterns."""
from unittest.mock import MagicMock

from anomaly_detection.lib.detect import (
    detect_duplicate_invoices,
    detect_supplier_concentration,
    detect_three_way_mismatch,
    detect_unusual_payments,
)
from anomaly_detection.lib.patterns import (
    DUPLICATE_INVOICE_COUNT,
    NEW_SUPPLIER_DAYS,
    PAYMENT_DEVIATION_FACTOR,
    SUPPLIER_CONCENTRATION,
    THREE_WAY_TOLERANCE,
)
from common.mcp_client import QueryResult
from common.severity import Severity


def _make_result(rows, trace_id="t1"):
    return QueryResult(
        trace_id=trace_id, ngql="MATCH", columns=["c"], rows=rows,
        row_count=len(rows), execution_time_ms=1, success=True,
    )


class TestThresholds:
    def test_three_way_tolerance_is_1_10(self):
        assert THREE_WAY_TOLERANCE == 1.10

    def test_duplicate_invoice_count_is_1(self):
        assert DUPLICATE_INVOICE_COUNT == 1

    def test_payment_deviation_factor_is_2(self):
        assert PAYMENT_DEVIATION_FACTOR == 2.0

    def test_new_supplier_days_is_90(self):
        assert NEW_SUPPLIER_DAYS == 90

    def test_supplier_concentration_is_60_percent(self):
        assert SUPPLIER_CONCENTRATION == 0.60


class TestThreeWayMismatch:
    def test_flags_when_invoice_exceeds_po_by_10_percent(self):
        rows = [
            {"po_amount": 100, "invoice_amount": 111, "po_id": "PO-1"},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_three_way_mismatch(ctx, "PO-1")
        assert len(anomalies) == 1
        assert anomalies[0].type == "three_way_mismatch"
        assert anomalies[0].severity in (Severity.WARNING.value, Severity.ALERT.value)

    def test_no_flag_when_invoice_within_tolerance(self):
        rows = [
            {"po_amount": 100, "invoice_amount": 105, "po_id": "PO-1"},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_three_way_mismatch(ctx, "PO-1")
        assert len(anomalies) == 0

    def test_flags_alert_when_invoice_exceeds_po_by_50_percent(self):
        rows = [
            {"po_amount": 100, "invoice_amount": 150, "po_id": "PO-1"},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_three_way_mismatch(ctx, "PO-1")
        assert len(anomalies) == 1
        assert anomalies[0].severity == Severity.ALERT.value


class TestDuplicateInvoices:
    def test_flags_when_count_greater_than_1(self):
        rows = [
            {"supplier": "S1", "amount": 100, "invoice_date": "2026-01-01", "count": 2},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_duplicate_invoices(ctx)
        assert len(anomalies) == 1
        assert anomalies[0].type == "duplicate_invoice"

    def test_no_flag_when_count_is_1(self):
        rows = [
            {"supplier": "S1", "amount": 100, "invoice_date": "2026-01-01", "count": 1},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_duplicate_invoices(ctx)
        assert len(anomalies) == 0


class TestUnusualPayments:
    def test_flags_when_payment_exceeds_2x_average(self):
        rows = [
            {"supplier": "S1", "amount": 500, "avg_amount": 200},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_unusual_payments(ctx, days=90)
        assert len(anomalies) == 1
        assert anomalies[0].type == "unusual_payment"

    def test_no_flag_when_payment_within_normal_range(self):
        rows = [
            {"supplier": "S1", "amount": 200, "avg_amount": 200},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_unusual_payments(ctx, days=90)
        assert len(anomalies) == 0


class TestSupplierConcentration:
    def test_flags_when_supplier_exceeds_60_percent(self):
        rows = [
            {"supplier": "S1", "category_spend": 700, "total_spend": 1000},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_supplier_concentration(ctx)
        assert len(anomalies) == 1
        assert anomalies[0].type == "supplier_concentration"

    def test_no_flag_when_supplier_below_60_percent(self):
        rows = [
            {"supplier": "S1", "category_spend": 500, "total_spend": 1000},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_supplier_concentration(ctx)
        assert len(anomalies) == 0
