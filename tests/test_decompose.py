"""Unit tests for question decomposition and cross-reference."""
from unittest.mock import MagicMock

import pytest
from common.mcp_client import QueryResult
from multi_step_analysis.lib.decompose import (
    SubQuery,
    compare_trends,
    cross_reference,
    decompose,
)


def _make_result(rows, trace_id="t1"):
    return QueryResult(
        trace_id=trace_id, ngql="GO", columns=["c"], rows=rows,
        row_count=len(rows), execution_time_ms=1, success=True,
    )


class TestSubQuery:
    def test_is_frozen_dataclass(self):
        sq = SubQuery(description="desc", question="q", round=1)
        assert sq.question == "q"
        with pytest.raises(Exception):
            sq.question = "modified"


class TestDecompose:
    def test_returns_2_to_5_subqueries(self):
        client = MagicMock()
        client.generate_query.return_value = {
            "sub_questions": [
                "Query 2025 Q1 PO amounts",
                "Query 2026 Q1 PO amounts",
                "Compare results",
            ]
        }
        sub_queries = decompose("对比2025年和2026年Q1的采购金额", client)
        assert 2 <= len(sub_queries) <= 5
        assert all(sq.round > 0 for sq in sub_queries)

    def test_assigns_increasing_round_numbers(self):
        client = MagicMock()
        client.generate_query.return_value = {
            "sub_questions": ["q1", "q2", "q3"]
        }
        sub_queries = decompose("test question", client)
        rounds = [sq.round for sq in sub_queries]
        assert rounds == sorted(rounds)
        assert rounds[0] == 1

    def test_handles_single_subquery(self):
        client = MagicMock()
        client.generate_query.return_value = {"sub_questions": ["q1"]}
        sub_queries = decompose("simple question", client)
        assert len(sub_queries) == 1


class TestCrossReference:
    def test_finds_increasing_trend(self):
        results = [
            _make_result([{"month": "2025-01", "amount": 100}], "t1"),
            _make_result([{"month": "2026-01", "amount": 150}], "t2"),
        ]
        patterns = cross_reference(results)
        assert "trends" in patterns
        assert len(patterns["trends"]) > 0

    def test_returns_empty_for_no_patterns(self):
        results = [_make_result([], "t1")]
        patterns = cross_reference(results)
        assert patterns.get("trends", []) == []


class TestCompareTrends:
    def test_detects_increase(self):
        result = compare_trends(
            [{"amount": 100}], [{"amount": 150}]
        )
        assert result["direction"] == "increase"
        assert result["change_percent"] == 50.0

    def test_detects_decrease(self):
        result = compare_trends(
            [{"amount": 200}], [{"amount": 100}]
        )
        assert result["direction"] == "decrease"

    def test_handles_no_change(self):
        result = compare_trends(
            [{"amount": 100}], [{"amount": 100}]
        )
        assert result["direction"] == "stable"

    def test_handles_empty_data(self):
        result = compare_trends([], [])
        assert result["direction"] == "unknown"
