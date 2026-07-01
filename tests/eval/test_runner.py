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


@pytest.mark.asyncio
async def test_run_offline_eval_l3_injects_org_id_for_analyst() -> None:
    """L3 PermissionEnforcer should inject org_id for non-admin users.

    The LLM generates nGQL without org_id (user_context=None). L3 then
    injects s.Supplier.org_id IN [1000] for the analyst. The has_org_id
    rule check passes on the post-enforcement nGQL.
    """
    case = EvalCase(
        id="NGQL-SUP-TEST",
        category="ngql_accuracy",
        subcategory="supplier_risk",
        question="查询高风险供应商有哪些",
        user_context="analyst",
        ci=CISection(
            golden_ngql="MATCH (s:Supplier) WHERE s.Supplier.org_id IN [1000] RETURN s.Supplier.supplier_name LIMIT 100",
            checks=[Check(type="syntax_valid"), Check(type="has_limit"), Check(type="has_org_id")],
        ),
        offline=OfflineSection(
            judge=JudgeSection(rubric="Is it correct?", pass_criteria=4, runs=1),
        ),
    )

    mock_adapter = AsyncMock()
    mock_resp = MagicMock()
    # LLM generates without org_id — L3 should inject it
    mock_resp.content = "MATCH (s:Supplier) RETURN s.Supplier.supplier_name AS supplier_name LIMIT 100"
    mock_adapter.chat = AsyncMock(return_value=mock_resp)

    mock_judge_adapter = AsyncMock()
    mock_judge_resp = MagicMock()
    mock_judge_resp.content = '{"score": 5, "reason": "correct"}'
    mock_judge_adapter.chat = AsyncMock(return_value=mock_judge_resp)

    with patch("eval.runner.build_llm_adapter", return_value=mock_adapter), \
         patch("eval.runner.build_judge_adapter", return_value=mock_judge_adapter), \
         patch("eval.runner.get_schema_info", return_value="schema"), \
         patch("eval.runner.render_ontology", return_value="ontology"):
        results = await run_offline_eval([case], runs=1, threshold=0.8)

    assert len(results) == 1
    assert results[0].case_id == "NGQL-SUP-TEST"
    assert results[0].pass_rate == 1.0
    assert results[0].passed is True
    assert results[0].run_scores == [5]


@pytest.mark.asyncio
async def test_run_offline_eval_antihal_l3_rejection_passes() -> None:
    """Antihal case where L3 rejects the query should be marked as pass.

    Analyst (PTP only) asks about SalesOrder (OTC). L3 raises
    PermissionViolationError. Since category is antihal_permission, the
    run is marked as pass with score 5.
    """
    case = EvalCase(
        id="ANTIHAL-L3-TEST",
        category="antihal_permission",
        subcategory="process_acl",
        question="查询所有销售订单",
        user_context="analyst",
        ci=CISection(
            golden_ngql="MATCH (so:SalesOrder) WHERE so.SalesOrder.org_id IN [1000] RETURN so.SalesOrder.so_number LIMIT 100",
            checks=[Check(type="syntax_valid")],
        ),
        offline=OfflineSection(
            judge=JudgeSection(rubric="Should be rejected by L3", pass_criteria=4, runs=1),
        ),
    )

    mock_adapter = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.content = "MATCH (so:SalesOrder) RETURN so.SalesOrder.so_number AS so_number LIMIT 100"
    mock_adapter.chat = AsyncMock(return_value=mock_resp)

    mock_judge_adapter = AsyncMock()
    mock_judge_adapter.chat = AsyncMock(return_value=MagicMock())

    with patch("eval.runner.build_llm_adapter", return_value=mock_adapter), \
         patch("eval.runner.build_judge_adapter", return_value=mock_judge_adapter), \
         patch("eval.runner.get_schema_info", return_value="schema"), \
         patch("eval.runner.render_ontology", return_value="ontology"):
        results = await run_offline_eval([case], runs=1, threshold=0.8)

    assert len(results) == 1
    assert results[0].case_id == "ANTIHAL-L3-TEST"
    assert results[0].pass_rate == 1.0
    assert results[0].passed is True
    assert results[0].run_scores == [5]
    assert "L3 correctly rejected" in results[0].judge_reasons[0]


@pytest.mark.asyncio
async def test_run_offline_eval_l3_rejection_non_antihal_fails() -> None:
    """Non-antihal case where L3 rejects should be marked as fail.

    A ngql_accuracy case with analyst (PTP only) asking about SalesOrder (OTC).
    L3 raises PermissionViolationError. Since category is NOT antihal_permission,
    the run is marked as fail with score 0.
    """
    case = EvalCase(
        id="NGQL-OTC-TEST",
        category="ngql_accuracy",
        subcategory="test",
        question="查询所有销售订单",
        user_context="analyst",
        ci=CISection(
            golden_ngql="MATCH (so:SalesOrder) WHERE so.SalesOrder.org_id IN [1000] RETURN so.SalesOrder.so_number LIMIT 100",
            checks=[Check(type="syntax_valid")],
        ),
        offline=OfflineSection(
            judge=JudgeSection(rubric="Should work", pass_criteria=4, runs=1),
        ),
    )

    mock_adapter = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.content = "MATCH (so:SalesOrder) RETURN so.SalesOrder.so_number AS so_number LIMIT 100"
    mock_adapter.chat = AsyncMock(return_value=mock_resp)

    mock_judge_adapter = AsyncMock()
    mock_judge_adapter.chat = AsyncMock(return_value=MagicMock())

    with patch("eval.runner.build_llm_adapter", return_value=mock_adapter), \
         patch("eval.runner.build_judge_adapter", return_value=mock_judge_adapter), \
         patch("eval.runner.get_schema_info", return_value="schema"), \
         patch("eval.runner.render_ontology", return_value="ontology"):
        results = await run_offline_eval([case], runs=1, threshold=0.8)

    assert len(results) == 1
    assert results[0].case_id == "NGQL-OTC-TEST"
    assert results[0].pass_rate == 0.0
    assert results[0].passed is False
    assert results[0].run_scores == [0]
