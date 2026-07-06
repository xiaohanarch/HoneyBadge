"""Tests for ETL data quality validation.

Focus: cross-column (column_a / column_b) pair comparison in
DataQualityChecker._check_business_rule. Previously this rule type
silently passed without executing any query, giving false confidence
in data quality.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from honeybadge.etl.quality import (
    DataQualityChecker,
    Severity,
    ValidationRule,
)


class _MockConn:
    """Minimal asyncpg connection mock."""

    def __init__(self, fetch_result):
        self.fetch = AsyncMock(return_value=fetch_result)


class _MockAcquire:
    """Async context manager matching asyncpg.Pool.acquire()."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return None


def _make_checker(fetch_result) -> DataQualityChecker:
    """Build a DataQualityChecker with a mocked pool returning fetch_result."""
    checker = DataQualityChecker.__new__(DataQualityChecker)
    conn = _MockConn(fetch_result)
    pool = MagicMock()
    pool.acquire.return_value = _MockAcquire(conn)
    checker._pool = pool
    return checker


def _pair_rule() -> ValidationRule:
    """The approved_date_after_order rule (column_a >= column_b, or_equal)."""
    return ValidationRule(
        name="approved_date_after_order",
        rule_type="business_rule",
        column="approved_date",
        description="Approved date must be >= order date",
        params={
            "column_a": "approved_date",
            "column_b": "order_date",
            "or_equal": True,
        },
        severity=Severity.WARNING,
    )


@pytest.mark.asyncio
async def test_pair_comparison_detects_violation():
    """Rule with column_a/column_b must catch rows where A < B."""
    violation_rows = [{"val": "2024-01-01"}, {"val": "2024-01-05"}]
    checker = _make_checker(violation_rows)
    rule = _pair_rule()

    result = await checker._check_business_rule(
        table_name="ods_purchase_order",
        batch_id="ETL-test-001",
        rule=rule,
    )

    assert result.passed is False
    assert len(result.failed_values) == 2
    assert "2024-01-01" in result.failed_values


@pytest.mark.asyncio
async def test_pair_comparison_passes_when_no_violation():
    """Rule with column_a/column_b must pass when no rows violate."""
    checker = _make_checker([])
    rule = _pair_rule()

    result = await checker._check_business_rule(
        table_name="ods_purchase_order",
        batch_id="ETL-test-001",
        rule=rule,
    )

    assert result.passed is True
    assert result.failed_values == []


@pytest.mark.asyncio
async def test_pair_comparison_uses_rule_fields_not_only_params():
    """column_a/column_b set as rule fields (not just params) must work too."""
    rule = ValidationRule(
        name="ship_after_order",
        rule_type="business_rule",
        column="ship_date",
        description="Ship date must be > order date",
        column_a="ship_date",
        column_b="order_date",
        or_equal=False,
        severity=Severity.WARNING,
    )
    checker = _make_checker([{"val": "2024-01-01"}])

    result = await checker._check_business_rule(
        table_name="ods_purchase_order",
        batch_id="ETL-test-001",
        rule=rule,
    )

    assert result.passed is False
    assert result.failed_values == ["2024-01-01"]
