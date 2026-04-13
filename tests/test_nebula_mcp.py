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
get_user_permissions_impl = _mod.get_user_permissions_impl
_schema_cache = _mod._schema_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeNebulaClient:
    """Fake NebulaGraphClient that returns canned results keyed by nGQL.

    Records the last nGQL string received so tests can assert on
    what was actually sent (e.g., to verify org_id filter injection).
    """

    def __init__(self, responses: dict[str, NebulaQueryResult]):
        self._responses = responses
        self.last_ngql: str = ""

    async def execute(self, ngql: str, space: str | None = None) -> NebulaQueryResult:
        self.last_ngql = ngql
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


# ---------------------------------------------------------------------------
# Tests for get_user_permissions_impl
# ---------------------------------------------------------------------------


class TestGetUserPermissions:
    """Tests for the get_user_permissions_impl function."""

    @pytest.mark.asyncio
    async def test_known_user_returns_permissions(self):
        result = await get_user_permissions_impl("admin")
        assert result["user_id"] == "admin"
        assert "PTP" in result["allowed_processes"]
        assert result["data_scope"] == "ALL"

    @pytest.mark.asyncio
    async def test_procurement_lead_permissions(self):
        result = await get_user_permissions_impl("procurement_lead")
        assert result["user_id"] == "procurement_lead"
        assert result["allowed_processes"] == ["PTP"]
        assert result["org_ids"] is None  # full org access

    @pytest.mark.asyncio
    async def test_subsidiary_lead_permissions(self):
        result = await get_user_permissions_impl("subsidiary_lead")
        assert result["user_id"] == "subsidiary_lead"
        assert result["org_ids"] == [2]

    @pytest.mark.asyncio
    async def test_unknown_user_returns_restrictive_default(self):
        result = await get_user_permissions_impl("google_sso_12345")
        # Unknown Google SSO users get restrictive default (HTTP call will fail
        # since no real service is running in tests)
        assert result["allowed_processes"] == ["PTP"]
        assert result["org_ids"] == [1]
        assert result["user_id"] == "google_sso_12345"

    @pytest.mark.asyncio
    async def test_http_200_response_used_when_not_in_local_config(self, monkeypatch):
        """When user is not in PERMISSION_CONFIG, use HTTP 200 response."""
        import httpx

        class FakeResponse:
            status_code = 200
            def json(self):
                return {
                    "user_id": "remote_user",
                    "allowed_processes": ["OTC"],
                    "org_ids": [5],
                    "dept_ids": None,
                    "data_scope": "ORG",
                }

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def get(self, url):
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **_: FakeClient())

        result = await get_user_permissions_impl("remote_user")
        assert result["allowed_processes"] == ["OTC"]
        assert result["org_ids"] == [5]

    @pytest.mark.asyncio
    async def test_http_non_200_falls_back_to_default(self, monkeypatch):
        """Non-200 HTTP response results in restrictive default."""
        import httpx

        class FakeResponse:
            status_code = 404

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def get(self, url):
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **_: FakeClient())

        result = await get_user_permissions_impl("not_found_user")
        assert result["allowed_processes"] == ["PTP"]
        assert result["org_ids"] == [1]
        assert result["user_id"] == "not_found_user"


# ---------------------------------------------------------------------------
# Tests for PermissionEnforcer integration inside validate_and_execute_impl
# ---------------------------------------------------------------------------


class TestValidateAndExecuteWithPermissions:
    """Tests for permission enforcement inside validate_and_execute_impl."""

    @pytest.fixture
    def nebula(self):
        return FakeNebulaClient({
            "MATCH": NebulaQueryResult(
                columns=["po_number"], rows=[{"po_number": "PO-001"}],
                execution_time_ms=1, success=True,
            ),
        })

    @pytest.fixture
    def validator(self):
        return NgqlValidator()

    @pytest.mark.asyncio
    async def test_forbidden_process_returns_permission_denied(self, nebula, validator):
        user_context = {
            "user_id": "analyst",
            "permissions": {
                "user_id": "analyst",
                "allowed_processes": ["PTP"],
                "org_ids": [1],
                "dept_ids": None,
                "data_scope": "ORG",
            },
        }
        result = await validate_and_execute_impl(
            nebula, validator,
            "MATCH (so:SalesOrder) RETURN so.status",
            user_context=user_context,
        )
        assert result["success"] is False
        assert result["error"] == "L3_PERMISSION"
        assert "SalesOrder" in result["details"][0]["message"]

    @pytest.mark.asyncio
    async def test_org_filter_auto_injected(self, nebula, validator):
        user_context = {
            "user_id": "subsidiary_lead",
            "permissions": {
                "user_id": "subsidiary_lead",
                "allowed_processes": ["PTP", "OTC"],
                "org_ids": [2],
                "dept_ids": None,
                "data_scope": "ORG",
            },
        }
        result = await validate_and_execute_impl(
            nebula, validator,
            "MATCH (po:PurchaseOrder) RETURN po.po_number",
            user_context=user_context,
        )
        assert result["success"] is True
        assert "warnings" in result
        assert any("PERMISSION WARNING" in w for w in result["warnings"])
        # Verify the org_id filter was actually present in the query sent to NebulaGraph
        assert "po.org_id IN [2]" in nebula.last_ngql

    @pytest.mark.asyncio
    async def test_allowed_query_with_full_access_has_empty_warnings(self, nebula, validator):
        user_context = {
            "user_id": "admin",
            "permissions": {
                "user_id": "admin",
                "allowed_processes": ["PTP", "OTC"],
                "org_ids": None,
                "dept_ids": None,
                "data_scope": "ALL",
            },
        }
        result = await validate_and_execute_impl(
            nebula, validator,
            "MATCH (po:PurchaseOrder) RETURN po.po_number",
            user_context=user_context,
        )
        assert result["success"] is True
        assert result["warnings"] == []

    @pytest.mark.asyncio
    async def test_no_user_context_has_empty_warnings(self, nebula, validator):
        result = await validate_and_execute_impl(
            nebula, validator,
            "MATCH (po:PurchaseOrder) RETURN po.po_number",
            user_context=None,
        )
        assert result["success"] is True
        assert result["warnings"] == []
