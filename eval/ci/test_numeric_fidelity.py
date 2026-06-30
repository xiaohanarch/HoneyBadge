# eval/ci/test_numeric_fidelity.py
"""CI-layer tests for numeric fidelity: each seed case must pass/fail as designed.

For every summarize-fidelity seed case:
  * the ``expected_summary`` (preserves all raw numbers) must PASS validation;
  * the ``tampered_summary`` (adversarially modified numbers) must FAIL validation.

These tests exercise the checker against synthetic data — no LLM, no database.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from eval.scorers.numeric_fidelity import validate_numeric_fidelity

if TYPE_CHECKING:
    from eval.ci.conftest import SummarizeCase


@pytest.mark.eval_ci
def test_expected_summary_passes_fidelity(summarize_case: SummarizeCase) -> None:
    """A correct summary preserving all raw numbers must PASS."""
    result = validate_numeric_fidelity(
        summarize_case.expected_summary,
        summarize_case.raw_results,
        summarize_case.columns,
    )
    assert result.passed, (
        f"{summarize_case.id}: expected summary should PASS but failed: {result.detail}"
    )


@pytest.mark.eval_ci
def test_tampered_summary_fails_fidelity(summarize_case: SummarizeCase) -> None:
    """An adversarial summary with modified numbers must FAIL."""
    result = validate_numeric_fidelity(
        summarize_case.tampered_summary,
        summarize_case.raw_results,
        summarize_case.columns,
    )
    assert not result.passed, (
        f"{summarize_case.id}: tampered summary should FAIL but passed"
    )
