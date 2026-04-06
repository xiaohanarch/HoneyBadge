"""Tests for honeybadge-nebula-mcp server.

Tests the _impl functions using mocks for NebulaGraphClient, LLM adapter,
and NgqlValidator so no external services are needed.
"""

import importlib.util
import os
import sys

# Add src to path for honeybadge modules
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_project_root, "src"))

import pytest

from honeybadge.db.nebula import NebulaQueryResult
from honeybadge.protocols.validator import NgqlValidator

# Load the server module with a unique name to avoid collisions with other test files
_server_path = os.path.join(_project_root, "mcp-servers", "honeybadge-nebula-mcp", "server.py")
_spec = importlib.util.spec_from_file_location("nebula_mcp_server", _server_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

get_schema_impl = _mod.get_schema_impl
validate_and_execute_impl = _mod.validate_and_execute_impl
_schema_cache = _mod._schema_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeNebulaClient:
    """Fake NebulaGraphClient that returns canned results keyed by nGQL."""

    def __init__(self, responses: dict[str, NebulaQueryResult]):
        self._responses = responses

    async def execute(self, ngql: str, space: str | None = None) -> NebulaQueryResult:
        # Try exact match first, then prefix match for flexibility
        if ngql in self._responses:
            return self._responses[ngql]
        for key, value in self._responses.items():
            if ngql.strip().upper().startswith(key.upper()):
                return value
        # Default: empty success
        return NebulaQueryResult(
            columns=[], rows=[], execution_time_ms=0, success=True
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schema_returns_tags_and_edges():
    """get_schema_impl should issue SHOW TAGS, DESCRIBE TAG, SHOW EDGES,
    DESCRIBE EDGE and return formatted schema text."""

    responses = {
        "SHOW TAGS": NebulaQueryResult(
            columns=["Name"],
            rows=[{"Name": "Supplier"}, {"Name": "PurchaseOrder"}],
            execution_time_ms=5,
            success=True,
        ),
        "DESCRIBE TAG `Supplier`": NebulaQueryResult(
            columns=["Field", "Type"],
            rows=[
                {"Field": "supplier_id", "Type": "string"},
                {"Field": "supplier_name", "Type": "string"},
            ],
            execution_time_ms=2,
            success=True,
        ),
        "DESCRIBE TAG `PurchaseOrder`": NebulaQueryResult(
            columns=["Field", "Type"],
            rows=[
                {"Field": "po_number", "Type": "string"},
                {"Field": "amount", "Type": "double"},
            ],
            execution_time_ms=2,
            success=True,
        ),
        "SHOW EDGES": NebulaQueryResult(
            columns=["Name"],
            rows=[{"Name": "SUPPLIES"}],
            execution_time_ms=3,
            success=True,
        ),
        "DESCRIBE EDGE `SUPPLIES`": NebulaQueryResult(
            columns=["Field", "Type"],
            rows=[{"Field": "contract_date", "Type": "date"}],
            execution_time_ms=2,
            success=True,
        ),
    }

    client = FakeNebulaClient(responses)

    # Clear cache to force a fresh load
    _schema_cache.clear()

    schema = await get_schema_impl(client, space="test_space")

    assert "Supplier" in schema
    assert "PurchaseOrder" in schema
    assert "supplier_id" in schema
    assert "supplier_name" in schema
    assert "po_number" in schema
    assert "amount" in schema
    assert "SUPPLIES" in schema
    assert "contract_date" in schema


@pytest.mark.asyncio
async def test_validate_and_execute_passes_valid_query():
    """A valid MATCH query should pass L1-L3 and return results."""

    ngql = 'MATCH (n:Supplier) WHERE n.Supplier.supplier_name == "Acme" RETURN n LIMIT 10'

    expected_result = NebulaQueryResult(
        columns=["n"],
        rows=[{"n": {"vid": "s001", "tags": ["Supplier"]}}],
        execution_time_ms=15,
        success=True,
    )

    client = FakeNebulaClient({ngql: expected_result})
    validator = NgqlValidator()

    result = await validate_and_execute_impl(
        nebula=client,
        validator=validator,
        ngql=ngql,
        space="test_space",
    )

    assert result["success"] is True
    assert result["columns"] == ["n"]
    assert result["row_count"] == 1
    assert "trace_id" in result
    assert result["trace_id"].startswith("TRC-")


@pytest.mark.asyncio
async def test_validate_and_execute_rejects_write_operation():
    """INSERT statement should be rejected with L1_WRITE_REJECTED."""

    ngql = 'INSERT VERTEX Supplier(supplier_id) VALUES "s999":("s999")'

    client = FakeNebulaClient({})
    validator = NgqlValidator()

    result = await validate_and_execute_impl(
        nebula=client,
        validator=validator,
        ngql=ngql,
        space="test_space",
    )

    assert result["success"] is False
    assert result["error"] == "L1_WRITE_REJECTED"
    assert result["details"][0]["code"] == "E010"
    assert "trace_id" in result


@pytest.mark.asyncio
async def test_validate_and_execute_rejects_empty_query():
    """An empty string should be rejected at L1 syntax validation."""

    client = FakeNebulaClient({})
    validator = NgqlValidator()

    result = await validate_and_execute_impl(
        nebula=client,
        validator=validator,
        ngql="",
        space="test_space",
    )

    assert result["success"] is False
    assert result["error"] == "L1_SYNTAX"
    assert any(d["code"] == "E001" for d in result["details"])
    assert "trace_id" in result
