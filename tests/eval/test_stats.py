# tests/eval/test_stats.py
"""Unit tests for eval.stats — N-run pass-rate statistics."""
from __future__ import annotations

import pytest

from eval.stats import EvalResult, compute_pass_rate, summarize_results


def test_compute_pass_rate_all_pass() -> None:
    run_results = [True, True, True]
    assert compute_pass_rate(run_results) == 1.0


def test_compute_pass_rate_mixed() -> None:
    run_results = [True, False, True]
    assert compute_pass_rate(run_results) == pytest.approx(0.667, abs=0.01)


def test_compute_pass_rate_empty() -> None:
    assert compute_pass_rate([]) == 0.0


def test_summarize_results_by_category() -> None:
    results = [
        EvalResult(case_id="A-001", category="ngql_accuracy", pass_rate=1.0, passed=True),
        EvalResult(case_id="A-002", category="ngql_accuracy", pass_rate=0.0, passed=False),
        EvalResult(case_id="B-001", category="antihal_permission", pass_rate=1.0, passed=True),
    ]
    summary = summarize_results(results, threshold=0.8)
    assert summary.total == 3
    assert summary.passed == 2
    assert summary.pass_rate == pytest.approx(0.667, abs=0.01)
    assert "ngql_accuracy" in summary.by_category
    assert summary.by_category["ngql_accuracy"]["pass_rate"] == 0.5
    assert summary.by_category["ngql_accuracy"]["count"] == 2
