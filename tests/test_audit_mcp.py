"""Tests for honeybadge-audit-mcp server."""

import importlib.util
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_project_root, "src"))

# Mock asyncpg if not available (e.g. Python 3.14 where asyncpg has no wheel)
if "asyncpg" not in sys.modules:
    _asyncpg_mock = types.ModuleType("asyncpg")
    _asyncpg_mock.Pool = MagicMock()  # type: ignore[attr-defined]
    _asyncpg_mock.create_pool = AsyncMock()  # type: ignore[attr-defined]
    sys.modules["asyncpg"] = _asyncpg_mock

import pytest

# Load server module with unique name to avoid collisions
_server_path = os.path.join(_project_root, "mcp-servers", "honeybadge-audit-mcp", "server.py")
_spec = importlib.util.spec_from_file_location("audit_mcp_server", _server_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

write_audit_log_impl = _mod.write_audit_log_impl
get_audit_trail_impl = _mod.get_audit_trail_impl


@pytest.fixture
def mock_pg_client():
    client = AsyncMock()
    client.write_audit_log = AsyncMock(return_value=True)
    client.get_audit_log = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_write_audit_log(mock_pg_client):
    """Test that write_audit_log_impl creates an AuditLogEntry and writes it."""
    result = await write_audit_log_impl(
        mock_pg_client,
        trace_id="trace-001",
        question="How many POs last month?",
        ngql="MATCH (p:PurchaseOrder) RETURN count(p)",
        raw_result={"count": 42},
        summary="There were 42 purchase orders last month.",
        user_id="user-123",
        session_id="session-abc",
        execution_time_ms=150,
        row_count=1,
        error_message=None,
    )

    assert result["success"] is True
    assert result["trace_id"] == "trace-001"
    mock_pg_client.write_audit_log.assert_called_once()

    # Verify the AuditLogEntry was constructed correctly
    entry = mock_pg_client.write_audit_log.call_args[0][0]
    assert entry.trace_id == "trace-001"
    assert entry.question == "How many POs last month?"
    assert entry.cypher == "MATCH (p:PurchaseOrder) RETURN count(p)"
    assert entry.raw_result == {"count": 42}
    assert entry.summary == "There were 42 purchase orders last month."
    assert entry.user_id == "user-123"
    assert entry.session_id == "session-abc"
    assert entry.execution_time_ms == 150
    assert entry.row_count == 1
    assert entry.error_message is None


@pytest.mark.asyncio
async def test_get_audit_trail(mock_pg_client):
    """Test that get_audit_trail_impl retrieves an audit entry by trace_id."""
    expected = {
        "trace_id": "trace-002",
        "question": "Top suppliers by spend?",
        "cypher": "MATCH (s:Supplier)-[:SUPPLIES]->(p:PO) RETURN s.name, sum(p.amount)",
        "raw_result": {"rows": [{"name": "SupplierA", "total": 1000000}]},
        "summary": "SupplierA leads with 1M spend.",
        "user_id": "user-456",
        "session_id": "session-def",
        "execution_time_ms": 230,
        "row_count": 5,
        "error_message": None,
    }
    mock_pg_client.get_audit_log = AsyncMock(return_value=expected)

    result = await get_audit_trail_impl(mock_pg_client, trace_id="trace-002")

    assert result is not None
    assert result["trace_id"] == "trace-002"
    assert result["question"] == "Top suppliers by spend?"
    mock_pg_client.get_audit_log.assert_called_once_with("trace-002")


@pytest.mark.asyncio
async def test_get_audit_trail_not_found(mock_pg_client):
    """Test that get_audit_trail_impl returns None when trace_id is not found."""
    result = await get_audit_trail_impl(mock_pg_client, trace_id="nonexistent")
    assert result is None
    mock_pg_client.get_audit_log.assert_called_once_with("nonexistent")
