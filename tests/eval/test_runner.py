# tests/eval/test_runner.py
"""Unit tests for eval.runner — offline eval main loop (mocked LLM)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.case_loader import Check, CISection, EvalCase, JudgeSection, OfflineSection
from eval.runner import run_offline_eval


def _make_case(case_id: str, category: str = "ngql_accuracy") -> EvalCase:
    return EvalCase(
        id=case_id,
        category=category,
        subcategory="test",
        question="test question",
        user_context="admin",
        ci=CISection(
            golden_ngql="MATCH (s:Supplier) RETURN s LIMIT 10",
            checks=[Check(type="syntax_valid"), Check(type="has_limit")],
        ),
        offline=OfflineSection(
            judge=JudgeSection(rubric="Is it correct?", pass_criteria=4, runs=2),
        ),
    )


@pytest.mark.asyncio
async def test_run_offline_eval_all_pass() -> None:
    cases = [_make_case("TEST-001")]

    mock_adapter = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.content = "MATCH (s:Supplier) RETURN s LIMIT 10"
    mock_adapter.chat = AsyncMock(return_value=mock_resp)

    mock_judge_adapter = AsyncMock()
    mock_judge_resp = MagicMock()
    mock_judge_resp.content = '{"score": 5, "reason": "perfect"}'
    mock_judge_adapter.chat = AsyncMock(return_value=mock_judge_resp)

    with patch("eval.runner.build_llm_adapter", return_value=mock_adapter), \
         patch("eval.runner.build_judge_adapter", return_value=mock_judge_adapter), \
         patch("eval.runner.get_schema_info", return_value="schema"), \
         patch("eval.runner.render_ontology", return_value="ontology"):
        results = await run_offline_eval(cases, runs=2, threshold=0.8)

    assert len(results) == 1
    assert results[0].case_id == "TEST-001"
    assert results[0].pass_rate == 1.0
    assert results[0].passed is True


@pytest.mark.asyncio
async def test_run_offline_eval_skips_cases_without_offline() -> None:
    case_no_offline = EvalCase(
        id="NO-OFFLINE",
        category="antihal_permission",
        subcategory="test",
        question="test",
        user_context="admin",
        ci=CISection(golden_ngql="DELETE VERTEX *", checks=[Check(type="rejected_by_L1")]),
        offline=None,
    )
    results = await run_offline_eval([case_no_offline], runs=1, threshold=0.8)
    assert results == []
