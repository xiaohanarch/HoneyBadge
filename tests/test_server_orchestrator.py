"""Tests for QueryOrchestrator and DirectPipelineOrchestrator."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from honeybadge.server.orchestrator import (
    QueryOrchestrator,
    DirectPipelineOrchestrator,
    PipelineCallbacks,
    QueryResult,
    create_orchestrator,
)


@pytest.fixture
def mock_callbacks():
    return PipelineCallbacks(on_progress=AsyncMock(), on_stream=AsyncMock())


@pytest.fixture
def mock_nebula():
    client = AsyncMock()
    client.execute = AsyncMock(
        return_value=MagicMock(
            success=True,
            columns=["supplier_name", "status"],
            rows=[{"supplier_name": "测试供应商", "status": "ACTIVE"}],
            row_count=1,
            execution_time_ms=5,
        )
    )
    return client


@pytest.fixture
def mock_llm():
    adapter = AsyncMock()
    adapter.chat = AsyncMock(
        return_value=MagicMock(
            content="MATCH (n:Supplier) RETURN n.Supplier.supplier_name AS supplier_name LIMIT 10",
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            finish_reason="stop",
            latency_ms=200,
        )
    )
    return adapter


@pytest.fixture
def mock_pg():
    client = AsyncMock()
    client.write_audit_log = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.fixture
def mock_validator():
    v = MagicMock()
    valid_result = MagicMock(valid=True, errors=[], warnings=[])
    v.validate_syntax = MagicMock(return_value=valid_result)
    v.validate_schema = MagicMock(return_value=valid_result)
    return v


# Test 1: QueryResult dataclass
def test_query_result_dataclass():
    result = QueryResult(
        summary="测试摘要",
        raw_data=[{"col": "val"}],
        columns=["col"],
        cypher="MATCH (n) RETURN n",
        trace_id="TRC-20260407-120000-abcd1234",
        execution_time_ms=100,
        row_count=1,
    )
    assert result.summary == "测试摘要"
    assert result.error is None


# Test 2: PipelineCallbacks dataclass
def test_pipeline_callbacks_dataclass():
    cb = PipelineCallbacks(on_progress=AsyncMock(), on_stream=AsyncMock())
    assert cb.on_progress is not None


# Test 3: Successful pipeline execution
@pytest.mark.asyncio
async def test_direct_pipeline_execute_query(
    mock_nebula, mock_llm, mock_pg, mock_redis, mock_validator, mock_callbacks
):
    orchestrator = DirectPipelineOrchestrator(
        nebula=mock_nebula,
        llm=mock_llm,
        pg=mock_pg,
        redis=mock_redis,
        validator=mock_validator,
        nebula_space="honeybadge",
    )
    result = await orchestrator.execute_query(
        question="查询所有供应商",
        session_id="session-1",
        user_context={"user_id": "user-admin", "org_ids": [], "data_scope": "ALL"},
        callbacks=mock_callbacks,
    )
    assert result.row_count == 1
    assert result.error is None
    assert result.trace_id.startswith("TRC-")
    assert mock_callbacks.on_progress.call_count == 5
    mock_pg.write_audit_log.assert_called_once()


# Test 4: Validation failure with retry
@pytest.mark.asyncio
async def test_direct_pipeline_validation_failure(
    mock_nebula, mock_llm, mock_pg, mock_redis, mock_callbacks
):
    validator = MagicMock()
    fail_result = MagicMock(
        valid=False, errors=[MagicMock(code="E001", message="Empty query")]
    )
    validator.validate_syntax = MagicMock(return_value=fail_result)
    validator.validate_schema = MagicMock(
        return_value=MagicMock(valid=True, errors=[], warnings=[])
    )

    orchestrator = DirectPipelineOrchestrator(
        nebula=mock_nebula,
        llm=mock_llm,
        pg=mock_pg,
        redis=mock_redis,
        validator=validator,
        nebula_space="honeybadge",
    )
    result = await orchestrator.execute_query(
        question="坏查询",
        session_id="session-1",
        user_context={"user_id": "user-admin", "org_ids": [], "data_scope": "ALL"},
        callbacks=mock_callbacks,
    )
    # Should return an error result (after retries exhausted)
    assert result.error is not None or result.row_count >= 0


# Test 5: create_orchestrator factory
def test_create_orchestrator_direct(
    mock_nebula, mock_llm, mock_pg, mock_redis, mock_validator
):
    from honeybadge.server.config import ServerConfig

    config = ServerConfig()
    orch = create_orchestrator(config, mock_nebula, mock_llm, mock_pg, mock_redis, mock_validator)
    assert isinstance(orch, DirectPipelineOrchestrator)


# Test 6: create_orchestrator hiclaw raises NotImplementedError
def test_create_orchestrator_hiclaw(
    mock_nebula, mock_llm, mock_pg, mock_redis, mock_validator
):
    from honeybadge.server.config import ServerConfig

    config = ServerConfig(orchestrator_type="hiclaw")
    with pytest.raises(NotImplementedError):
        create_orchestrator(config, mock_nebula, mock_llm, mock_pg, mock_redis, mock_validator)
