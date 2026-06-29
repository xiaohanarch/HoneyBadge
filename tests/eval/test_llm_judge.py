# tests/eval/test_llm_judge.py
"""Unit tests for eval.scorers.llm_judge — LLM-as-judge scoring (mocked)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from eval.scorers.llm_judge import LLMJudge, parse_judge_response


def test_parse_judge_response_valid_json() -> None:
    resp = '{"score": 4, "reason": "correct query"}'
    score, reason = parse_judge_response(resp)
    assert score == 4
    assert reason == "correct query"


def test_parse_judge_response_with_markdown_fence() -> None:
    resp = '```json\n{"score": 5, "reason": "perfect"}\n```'
    score, reason = parse_judge_response(resp)
    assert score == 5
    assert reason == "perfect"


def test_parse_judge_response_invalid() -> None:
    resp = "I cannot evaluate this"
    score, reason = parse_judge_response(resp)
    assert score == 0
    assert "parse" in reason.lower() or "invalid" in reason.lower()


@pytest.mark.asyncio
async def test_judge_evaluate_calls_adapter() -> None:
    mock_adapter = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.content = '{"score": 4, "reason": "good"}'
    mock_adapter.chat = AsyncMock(return_value=mock_resp)

    judge = LLMJudge(mock_adapter)
    score, reason = await judge.evaluate(
        question="查询高风险供应商",
        generated_ngql="MATCH (s:Supplier) WHERE s.Supplier.credit_rating IN ['C','D'] RETURN s LIMIT 100",
        rubric="Is this correct?",
    )
    assert score == 4
    assert reason == "good"
    mock_adapter.chat.assert_called_once()
