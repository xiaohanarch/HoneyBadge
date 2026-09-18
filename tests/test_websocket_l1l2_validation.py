"""Tests for L1/L2 anti-hallucination validation wired into process_query.

Regression coverage for the wiring of NgqlValidator (L1 syntax + L2 schema)
into the WebSocket chat hot path. Before this wiring, malformed or
schema-non-compliant nGQL was only caught after a NebulaGraph round-trip;
now L1/L2 run before execution (mirroring the MCP server path), with
regeneration on failure sharing the existing retry budget.

L1 = syntax (balanced parens/quotes, known start keyword)
L2 = schema compliance (tags/edges/properties exist)
L3 = permission enforcement (org_id injection) — must still run after L1+L2.
"""
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_project_root, "src"))

# Mock asyncpg if not available (e.g. Python 3.14 where asyncpg has no wheel).
if "asyncpg" not in sys.modules:
    _asyncpg_mock = types.ModuleType("asyncpg")
    _asyncpg_mock.Pool = MagicMock()  # type: ignore[attr-defined]
    _asyncpg_mock.create_pool = AsyncMock()  # type: ignore[attr-defined]
    sys.modules["asyncpg"] = _asyncpg_mock

from honeybadge.db.nebula import NebulaQueryResult  # noqa: E402
from honeybadge.llm.adapter import LLMResponse  # noqa: E402
from honeybadge.protocols.validator import (  # noqa: E402
    SchemaEdge,
    SchemaProperty,
    SchemaTag,
)
from honeybadge.server import websocket  # noqa: E402

# ---------------------------------------------------------------------------
# Test schema (mirrors tests/test_validator.py:115-143)
# ---------------------------------------------------------------------------

_TEST_TAGS = [
    SchemaTag(
        name="Supplier",
        properties=[
            SchemaProperty(name="name", type="STRING"),
            SchemaProperty(name="status", type="STRING"),
        ],
    ),
    SchemaTag(
        name="PurchaseOrder",
        properties=[
            SchemaProperty(name="po_number", type="STRING"),
            SchemaProperty(name="status", type="STRING"),
            SchemaProperty(name="org_id", type="INT64"),
        ],
    ),
]

_TEST_EDGES = [
    SchemaEdge(
        name="PLACED_WITH",
        properties=[
            SchemaProperty(name="order_date", type="TIMESTAMP"),
            SchemaProperty(name="org_id", type="INT64"),
        ],
    ),
]

_VALID_NGQL = "MATCH (n:Supplier) RETURN n.Supplier.name AS name LIMIT 10"
_MALFORMED_NGQL = "MATCH (n:Supplier RETURN n"  # unbalanced parens (L1 E002)
_BAD_TAG_NGQL = "MATCH (n:NonExistentTag) RETURN n LIMIT 10"  # L2 E101
_WRITE_NGQL = 'INSERT VERTEX Supplier(name) VALUES "S1":("test")'


def _llm(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test",
        prompt_tokens=5,
        completion_tokens=5,
        total_tokens=10,
        finish_reason="stop",
        latency_ms=10,
    )


@pytest.fixture
def loaded_validator(monkeypatch):
    """Reset module-level validator state and pre-load the test schema.

    Ensures _ensure_validator_schema is a no-op (space already marked loaded)
    so tests don't hit NebulaGraph for schema discovery.
    """
    monkeypatch.setattr(websocket, "_validator", None)
    monkeypatch.setattr(websocket, "_validator_schema_loaded_space", None)
    monkeypatch.setattr(websocket, "_schema_cache", {})

    validator = websocket._get_validator()
    validator.load_schema(_TEST_TAGS, _TEST_EDGES)
    monkeypatch.setattr(websocket, "_validator_schema_loaded_space", "honeybadge")
    return validator


@pytest.fixture
def mock_deps():
    """Build the standard mock nebula/pg/llm dependency triple.

    Returns a dict so individual tests can override specific pieces.
    """
    mock_nebula = AsyncMock()
    mock_nebula.execute = AsyncMock(
        return_value=NebulaQueryResult(
            columns=["name"], rows=[{"name": "Acme"}], execution_time_ms=5, success=True,
        )
    )

    mock_pg = AsyncMock()
    mock_pg.get_session_audit_logs = AsyncMock(return_value=[])
    mock_pg.write_audit_log = AsyncMock()

    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=_llm(_VALID_NGQL))

    return {"nebula": mock_nebula, "pg": mock_pg, "llm": mock_llm}


def _patch_schema_str(schema_str: str = "# test schema\n"):
    """Patch get_filtered_schema_str to avoid NebulaGraph schema-discovery calls."""
    return patch.object(
        websocket,
        "get_filtered_schema_str",
        new=AsyncMock(return_value=schema_str),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_l1_syntax_error_triggers_regeneration(loaded_validator, mock_deps):
    """L1 failure (unbalanced parens) regenerates nGQL, then succeeds."""
    mock_deps["llm"].chat = AsyncMock(
        side_effect=[
            _llm(_MALFORMED_NGQL),  # initial generation — malformed
            _llm(_VALID_NGQL),      # regeneration — valid
            _llm("找到 1 个供应商"),  # summarize
        ]
    )

    with _patch_schema_str():
        result = await websocket.process_query(
            question="查询供应商",
            session_id="sess-l1",
            nebula=mock_deps["nebula"],
            pg=mock_deps["pg"],
            llm_adapter=mock_deps["llm"],
            user_id="admin",
        )

    assert "error" not in result
    assert result["row_count"] == 1
    # The valid nGQL must have been executed (after regeneration).
    mock_deps["nebula"].execute.assert_awaited()
    # Last execute call carried the valid nGQL (after rewrite, which is a no-op
    # here since the valid query already uses three-part access).
    last_call_ngql = mock_deps["nebula"].execute.call_args.args[0]
    assert "MATCH" in last_call_ngql
    assert "Supplier" in last_call_ngql
    # LLM was called 3 times: generate, regenerate, summarize.
    assert mock_deps["llm"].chat.await_count == 3


@pytest.mark.asyncio
async def test_l2_schema_error_triggers_regeneration(loaded_validator, mock_deps):
    """L2 failure (nonexistent tag) regenerates nGQL, then succeeds."""
    mock_deps["llm"].chat = AsyncMock(
        side_effect=[
            _llm(_BAD_TAG_NGQL),   # initial — references NonExistentTag
            _llm(_VALID_NGQL),      # regeneration — valid tag
            _llm("找到 1 个供应商"),  # summarize
        ]
    )

    with _patch_schema_str():
        result = await websocket.process_query(
            question="查询供应商",
            session_id="sess-l2",
            nebula=mock_deps["nebula"],
            pg=mock_deps["pg"],
            llm_adapter=mock_deps["llm"],
            user_id="admin",
        )

    assert "error" not in result
    mock_deps["nebula"].execute.assert_awaited()
    last_call_ngql = mock_deps["nebula"].execute.call_args.args[0]
    assert "NonExistentTag" not in last_call_ngql
    assert "Supplier" in last_call_ngql
    assert mock_deps["llm"].chat.await_count == 3


@pytest.mark.asyncio
async def test_write_operation_is_hard_rejected(loaded_validator, mock_deps):
    """Write ops (INSERT/UPDATE/etc.) are rejected with no retry and no execute."""
    mock_deps["llm"].chat = AsyncMock(return_value=_llm(_WRITE_NGQL))

    with _patch_schema_str():
        result = await websocket.process_query(
            question="插入一个供应商",
            session_id="sess-write",
            nebula=mock_deps["nebula"],
            pg=mock_deps["pg"],
            llm_adapter=mock_deps["llm"],
            user_id="admin",
        )

    # Hard reject surfaces as an error response.
    assert "error" in result
    assert "L1_WRITE_REJECTED" in result["error"]
    # nebula.execute must never be called with the write nGQL. (get_filtered_schema_str
    # is patched, so the only nebula.execute calls would be query execution.)
    mock_deps["nebula"].execute.assert_not_awaited()
    # No regeneration: LLM called exactly once (initial generation only).
    assert mock_deps["llm"].chat.await_count == 1


@pytest.mark.asyncio
async def test_l1l2_failure_exhausts_retries_and_returns_error(loaded_validator, mock_deps):
    """When L1 always fails, retries are exhausted and an error is surfaced."""
    mock_deps["llm"].chat = AsyncMock(return_value=_llm(_MALFORMED_NGQL))

    with _patch_schema_str():
        result = await websocket.process_query(
            question="查询供应商",
            session_id="sess-exhaust",
            nebula=mock_deps["nebula"],
            pg=mock_deps["pg"],
            llm_adapter=mock_deps["llm"],
            user_id="admin",
        )

    assert "error" in result
    assert "L1_SYNTAX" in result["error"]
    # nebula.execute never reached (L1 failed on every attempt before execute).
    mock_deps["nebula"].execute.assert_not_awaited()
    # max_retries=2 → 3 attempts → 3 LLM calls (initial + 2 regenerations).
    # No summarize call (we never reached a successful execute).
    assert mock_deps["llm"].chat.await_count == 3


@pytest.mark.asyncio
async def test_valid_ngql_passes_l1l2_unchanged(loaded_validator, mock_deps):
    """Happy path: valid nGQL passes L1/L2/L3 on the first attempt."""
    mock_deps["llm"].chat = AsyncMock(
        side_effect=[
            _llm(_VALID_NGQL),     # generate
            _llm("找到 1 个供应商"),  # summarize
        ]
    )

    with _patch_schema_str():
        result = await websocket.process_query(
            question="查询供应商",
            session_id="sess-ok",
            nebula=mock_deps["nebula"],
            pg=mock_deps["pg"],
            llm_adapter=mock_deps["llm"],
            user_id="admin",
        )

    assert "error" not in result
    assert result["row_count"] == 1
    # Exactly one execute call (the valid nGQL).
    assert mock_deps["nebula"].execute.await_count == 1
    executed_ngql = mock_deps["nebula"].execute.call_args.args[0]
    assert "MATCH" in executed_ngql
    # Exactly two LLM calls: generate + summarize (no regeneration).
    assert mock_deps["llm"].chat.await_count == 2


@pytest.mark.asyncio
async def test_l3_permission_still_runs_after_l1l2(loaded_validator, mock_deps):
    """L3 enforce() must still be invoked after L1+L2 pass (regression guard).

    L3 was previously called before the retry loop; it now runs inside the loop
    after L1+L2. This test ensures L3 is not skipped when L1/L2 are wired in.
    """
    mock_deps["llm"].chat = AsyncMock(
        side_effect=[
            _llm(_VALID_NGQL),
            _llm("ok"),
        ]
    )

    # Spy on the real enforcer: wrap enforce to track invocation while preserving
    # real behavior (admin context → no filter injection).
    real_enforcer = websocket._permission_enforcer
    enforce_spy = MagicMock(wraps=real_enforcer.enforce)
    with patch.object(real_enforcer, "enforce", enforce_spy), _patch_schema_str():
        result = await websocket.process_query(
            question="查询供应商",
            session_id="sess-l3",
            nebula=mock_deps["nebula"],
            pg=mock_deps["pg"],
            llm_adapter=mock_deps["llm"],
            user_id="admin",
        )

    assert "error" not in result
    # L3 enforce was called exactly once (valid nGQL passed L1+L2 on first try).
    enforce_spy.assert_called_once()
