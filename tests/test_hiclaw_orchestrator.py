"""Tests for HiClawOrchestrator."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from honeybadge.gateway.matrix_client import MatrixMessage
from honeybadge.server.orchestrator import (
    HiClawOrchestrator,
    PipelineCallbacks,
    QueryResult,
)


def _make_result_msg(trace_id: str) -> MatrixMessage:
    return MatrixMessage(
        msgtype="result",
        trace_id=trace_id,
        summary="发现3笔异常交易",
        ngql="MATCH (po:PurchaseOrder) RETURN po",
        rows=[{"po_number": "PO001", "amount": 100}],
        columns=["po_number", "amount"],
        row_count=1,
        execution_time_ms=300,
    )


def _make_error_msg(trace_id: str) -> MatrixMessage:
    return MatrixMessage(
        msgtype="error",
        trace_id=trace_id,
        error_code="VALIDATION_ERROR",
        error_message="L1 语法校验失败",
        recoverable=False,
    )


@pytest.fixture
def mock_matrix():
    m = AsyncMock()
    m.submit_and_wait = AsyncMock()
    return m


@pytest.fixture
def mock_pg():
    pg = AsyncMock()
    pg.write_audit_log = AsyncMock()
    return pg


@pytest.fixture
def mock_callbacks():
    return PipelineCallbacks(on_progress=AsyncMock(), on_stream=AsyncMock())


@pytest.mark.asyncio
async def test_hiclaw_orchestrator_returns_query_result_on_success(
    mock_matrix, mock_pg, mock_callbacks
):
    """Successful HiClaw response maps correctly to QueryResult."""
    trace_id = "TRC-20260408-120000-hiclaw01"
    mock_matrix.submit_and_wait.return_value = _make_result_msg(trace_id)

    orchestrator = HiClawOrchestrator(
        matrix_client=mock_matrix, pg=mock_pg, query_timeout=10.0
    )

    with patch(
        "honeybadge.server.orchestrator.generate_trace_id", return_value=trace_id
    ):
        result = await orchestrator.execute_query(
            question="查找异常交易",
            session_id="sess-001",
            user_context={"user_id": "u1", "org_id": "org1", "roles": []},
            callbacks=mock_callbacks,
        )

    assert result.error is None
    assert result.summary == "发现3笔异常交易"
    assert result.cypher == "MATCH (po:PurchaseOrder) RETURN po"
    assert result.row_count == 1
    assert result.columns == ["po_number", "amount"]
    assert result.trace_id == trace_id
    assert result.execution_time_ms == 300


@pytest.mark.asyncio
async def test_hiclaw_orchestrator_returns_error_on_error_message(
    mock_matrix, mock_pg, mock_callbacks
):
    """Error response from Worker maps to QueryResult with error field set."""
    trace_id = "TRC-20260408-120000-hiclaw02"
    mock_matrix.submit_and_wait.return_value = _make_error_msg(trace_id)

    orchestrator = HiClawOrchestrator(
        matrix_client=mock_matrix, pg=mock_pg, query_timeout=10.0
    )

    with patch(
        "honeybadge.server.orchestrator.generate_trace_id", return_value=trace_id
    ):
        result = await orchestrator.execute_query(
            question="查找异常交易",
            session_id="sess-002",
            user_context={"user_id": "u1", "org_id": "org1", "roles": []},
            callbacks=mock_callbacks,
        )

    assert result.error is not None
    assert "VALIDATION_ERROR" in result.error
    assert result.summary == ""
    # Worker already wrote audit — orchestrator must NOT write one
    mock_pg.write_audit_log.assert_not_called()


@pytest.mark.asyncio
async def test_hiclaw_orchestrator_timeout_returns_error_and_writes_audit(
    mock_matrix, mock_pg, mock_callbacks
):
    """Timeout returns QueryResult(error=...) and writes one audit log entry."""
    mock_matrix.submit_and_wait.side_effect = asyncio.TimeoutError()

    orchestrator = HiClawOrchestrator(
        matrix_client=mock_matrix, pg=mock_pg, query_timeout=5.0
    )

    result = await orchestrator.execute_query(
        question="查找异常交易",
        session_id="sess-003",
        user_context={"user_id": "u1", "org_id": "org1", "roles": []},
        callbacks=mock_callbacks,
    )

    assert result.error is not None
    assert "timed out" in result.error.lower()
    mock_pg.write_audit_log.assert_called_once()


@pytest.mark.asyncio
async def test_hiclaw_orchestrator_passes_plain_text_to_on_stream(
    mock_matrix, mock_pg, mock_callbacks
):
    """HiClaw native text (CONTRACT-004) is forwarded to callbacks.on_stream."""
    trace_id = "TRC-20260408-120000-hiclaw03"

    async def fake_submit(
        question, trace_id, user_context, session_id, on_room_text, timeout
    ):
        await on_room_text("正在路由到 graph-worker...")
        return _make_result_msg(trace_id)

    mock_matrix.submit_and_wait.side_effect = fake_submit

    orchestrator = HiClawOrchestrator(
        matrix_client=mock_matrix, pg=mock_pg, query_timeout=10.0
    )

    with patch(
        "honeybadge.server.orchestrator.generate_trace_id", return_value=trace_id
    ):
        await orchestrator.execute_query(
            question="查找异常交易",
            session_id="sess-004",
            user_context={"user_id": "u1", "org_id": "org1", "roles": []},
            callbacks=mock_callbacks,
        )

    mock_callbacks.on_stream.assert_any_call("正在路由到 graph-worker...", "thinking", False)
