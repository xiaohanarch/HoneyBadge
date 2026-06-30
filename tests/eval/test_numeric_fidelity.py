# tests/eval/test_numeric_fidelity.py
"""Unit tests for honeybadge.llm.numeric_fidelity — deterministic, no LLM.

The checker was promoted from ``eval/scorers/`` to the runtime package so it is
importable from both the production chat path and the eval suite. These tests
exercise the runtime-canonical copy; the logic is unchanged from the original
eval-only implementation.
"""
from __future__ import annotations

from typing import Any

from honeybadge.llm.numeric_fidelity import extract_numbers, validate_numeric_fidelity

# --- extract_numbers ---


def test_extract_numbers_finds_integers() -> None:
    assert extract_numbers("金额为 100000 元") == {"100000"}


def test_extract_numbers_finds_decimals() -> None:
    assert extract_numbers("偏差达 23.5%") == {"23.5"}


def test_extract_numbers_finds_thousands_separators() -> None:
    # "100,000" is normalized to "100000" (commas stripped).
    assert extract_numbers("总额 100,000") == {"100000"}


def test_extract_numbers_does_not_split_plain_six_digit_integer() -> None:
    # Regression guard: a plain 6-digit integer must match as ONE number,
    # not split into "100" + "000" by the comma-grouped alternative.
    assert extract_numbers("x 100000 y") == {"100000"}


# --- validate_numeric_fidelity ---


def test_validate_passes_when_numbers_match() -> None:
    raw_results: list[dict[str, Any]] = [{"amount": "100000"}]
    result = validate_numeric_fidelity("金额为 100000 元", raw_results, ["amount"])
    assert result.passed


def test_validate_fails_when_number_modified() -> None:
    raw_results: list[dict[str, Any]] = [{"amount": "100000"}]
    result = validate_numeric_fidelity("金额为 123000 元", raw_results, ["amount"])
    assert not result.passed
    assert "100000" in result.detail


def test_validate_fails_when_number_missing() -> None:
    raw_results: list[dict[str, Any]] = [{"amount": "100000"}]
    result = validate_numeric_fidelity("未找到相关记录", raw_results, ["amount"])
    assert not result.passed
    assert "100000" in result.detail


def test_validate_passes_with_extra_summary_numbers() -> None:
    # Summary may mention counts/percentages not in raw results -> still PASS.
    raw_results: list[dict[str, Any]] = [{"amount": "100000"}]
    result = validate_numeric_fidelity("共 3 笔，合计 100000 元", raw_results, ["amount"])
    assert result.passed


def test_validate_passes_for_empty_results() -> None:
    result = validate_numeric_fidelity("无数据", [], ["amount"])
    assert result.passed


def test_validate_fails_for_multiple_mismatches() -> None:
    # 3 raw numbers, 2 modified (200 -> 250, 300 -> 350) -> FAIL listing both.
    raw_results: list[dict[str, Any]] = [
        {"a": "100"},
        {"a": "200"},
        {"a": "300"},
    ]
    result = validate_numeric_fidelity("数值为 100 和 250 和 350", raw_results, ["a"])
    assert not result.passed
    assert "200" in result.detail
    assert "300" in result.detail
    assert "100" not in result.detail


def test_validate_handles_multiple_rows() -> None:
    raw_results: list[dict[str, Any]] = [
        {"a": "10"},
        {"a": "20"},
        {"a": "30"},
        {"a": "40"},
        {"a": "50"},
    ]
    result = validate_numeric_fidelity("10 20 30 40 50", raw_results, ["a"])
    assert result.passed
