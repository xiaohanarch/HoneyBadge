"""Tests for multi-tenant isolation hardening.

Covers:
  - M1: org_id column in audit_logs schema and AuditLogEntry
  - M2: Org-level audit filtering (admin sees own org, superadmin sees all)
  - M3: Cache MCP tenant-prefixed keys
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Load the cache-mcp server module explicitly by file path to avoid
# sys.path collision with honeybadge-nebula-mcp/server.py (both are "server").
_CACHE_MCP_PATH = Path(__file__).resolve().parent.parent / "mcp-servers" / "honeybadge-cache-mcp"


def _load_cache_server_module():
    """Load cache-mcp/server.py as an isolated module."""
    mod_path = _CACHE_MCP_PATH / "server.py"
    spec = importlib.util.spec_from_file_location("cache_mcp_server", mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_cache_server = _load_cache_server_module()


# ---------------------------------------------------------------------------
# M1: AuditLogEntry carries org_id; schema includes org_id column
# ---------------------------------------------------------------------------

class TestAuditLogOrgId:
    """Verify org_id is part of the audit log data model."""

    def test_audit_log_entry_has_org_id_field(self) -> None:
        """AuditLogEntry must have an org_id field for tenant tagging."""
        from honeybadge.db.postgres import AuditLogEntry

        entry = AuditLogEntry(
            trace_id="TRC-test",
            question="test",
            cypher="MATCH (n) RETURN n",
            raw_result={},
            summary="test",
            user_id="analyst",
            session_id="sess-1",
            execution_time_ms=10,
            row_count=0,
            org_id=1000,
        )
        assert entry.org_id == 1000

    def test_audit_log_entry_org_id_defaults_none(self) -> None:
        """org_id is optional (None) for backward compatibility."""
        from honeybadge.db.postgres import AuditLogEntry

        entry = AuditLogEntry(
            trace_id="TRC-test",
            question="test",
            cypher="MATCH (n) RETURN n",
            raw_result={},
            summary="test",
            user_id="analyst",
            session_id="sess-1",
            execution_time_ms=10,
            row_count=0,
        )
        assert entry.org_id is None

    def test_schema_adds_org_id_column(self) -> None:
        """init_schema must include ALTER TABLE to add org_id column."""
        import inspect

        from honeybadge.db.postgres import PostgreSQLClient

        source = inspect.getsource(PostgreSQLClient.init_schema)
        assert "ADD COLUMN IF NOT EXISTS org_id" in source, (
            "init_schema must add org_id column for multi-tenant audit isolation"
        )
        assert "idx_audit_org_id" in source, "Must index org_id for query performance"

    def test_insert_includes_org_id(self) -> None:
        """write_audit_log must insert org_id from the entry."""
        import inspect

        from honeybadge.db.postgres import PostgreSQLClient

        source = inspect.getsource(PostgreSQLClient.write_audit_log)
        assert "org_id" in source, "INSERT must include org_id column"
        assert "entry.org_id" in source, "INSERT must pass entry.org_id value"


# ---------------------------------------------------------------------------
# M2: Org-level audit filtering in audit API
# ---------------------------------------------------------------------------

class TestAuditOrgFiltering:
    """Verify the audit API enforces org-level isolation for privileged users."""

    def test_superadmin_role_constant_exists(self) -> None:
        from honeybadge.server.audit import _SUPERADMIN_ROLE

        assert _SUPERADMIN_ROLE == "superadmin"

    def test_is_superadmin_explicit_role(self) -> None:
        from honeybadge.server.audit import _is_superadmin

        user = {"roles": ["superadmin"], "org_id": 1000}
        assert _is_superadmin(user) is True

    def test_is_superadmin_org_id_none_with_admin(self) -> None:
        """Legacy admin pattern: org_id=None in JWT signals cross-org access."""
        from honeybadge.server.audit import _is_superadmin

        user = {"roles": ["admin"], "org_id": None}
        assert _is_superadmin(user) is True

    def test_is_not_superadmin_when_org_scoped_admin(self) -> None:
        """An admin with a specific org_id is NOT superadmin."""
        from honeybadge.server.audit import _is_superadmin

        user = {"roles": ["admin"], "org_id": 1000}
        assert _is_superadmin(user) is False

    def test_is_not_superadmin_for_auditor(self) -> None:
        from honeybadge.server.audit import _is_superadmin

        user = {"roles": ["auditor"], "org_id": 1000}
        assert _is_superadmin(user) is False

    def test_user_org_id_extraction_int(self) -> None:
        from honeybadge.server.audit import _user_org_id

        assert _user_org_id({"org_id": 1000}) == 1000

    def test_user_org_id_extraction_string(self) -> None:
        from honeybadge.server.audit import _user_org_id

        assert _user_org_id({"org_id": "1000"}) == 1000

    def test_user_org_id_extraction_none(self) -> None:
        from honeybadge.server.audit import _user_org_id

        assert _user_org_id({"org_id": None}) is None
        assert _user_org_id({}) is None

    @pytest.mark.asyncio
    async def test_org_scoped_admin_blocked_from_other_org(self) -> None:
        """An admin from org 1000 cannot view audit records from org 2000."""
        from honeybadge.server.audit import get_audit_trail

        mock_pg = MagicMock()
        mock_pg.get_audit_log = AsyncMock(return_value={
            "trace_id": "TRC-test",
            "question": "test",
            "cypher": "MATCH (n) RETURN n",
            "summary": "test",
            "session_id": "sess-1",
            "user_id": "analyst",
            "execution_time_ms": 10,
            "row_count": 0,
            "created_at": MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
            "raw_result": {},
            "org_id": 2000,
        })

        admin_user = {"roles": ["admin"], "org_id": 1000, "username": "admin_a"}

        with pytest.raises(Exception) as exc_info:
            await get_audit_trail(trace_id="TRC-test", user=admin_user, pg=mock_pg)

        assert exc_info.value.status_code == 403
        assert "another organization" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_org_scoped_admin_can_view_own_org(self) -> None:
        """An admin from org 1000 can view audit records from org 1000."""
        from honeybadge.server.audit import get_audit_trail

        mock_pg = MagicMock()
        mock_pg.get_audit_log = AsyncMock(return_value={
            "trace_id": "TRC-test",
            "question": "test",
            "cypher": "MATCH (n) RETURN n",
            "summary": "test",
            "session_id": "sess-1",
            "user_id": "analyst",
            "execution_time_ms": 10,
            "row_count": 0,
            "created_at": MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
            "raw_result": {},
            "org_id": 1000,
        })

        admin_user = {"roles": ["admin"], "org_id": 1000, "username": "admin_a"}

        result = await get_audit_trail(trace_id="TRC-test", user=admin_user, pg=mock_pg)
        assert result.trace_id == "TRC-test"

    @pytest.mark.asyncio
    async def test_superadmin_can_view_any_org(self) -> None:
        """A superadmin can view audit records from any organization."""
        from honeybadge.server.audit import get_audit_trail

        mock_pg = MagicMock()
        mock_pg.get_audit_log = AsyncMock(return_value={
            "trace_id": "TRC-test",
            "question": "test",
            "cypher": "MATCH (n) RETURN n",
            "summary": "test",
            "session_id": "sess-1",
            "user_id": "analyst",
            "execution_time_ms": 10,
            "row_count": 0,
            "created_at": MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
            "raw_result": {},
            "org_id": 2000,
        })

        superadmin = {"roles": ["superadmin"], "org_id": 1000, "username": "root"}

        result = await get_audit_trail(trace_id="TRC-test", user=superadmin, pg=mock_pg)
        assert result.trace_id == "TRC-test"

    @pytest.mark.asyncio
    async def test_superadmin_can_view_null_org_records(self) -> None:
        """Superadmin can view legacy records with org_id=NULL."""
        from honeybadge.server.audit import get_audit_trail

        mock_pg = MagicMock()
        mock_pg.get_audit_log = AsyncMock(return_value={
            "trace_id": "TRC-legacy",
            "question": "test",
            "cypher": "MATCH (n) RETURN n",
            "summary": "test",
            "session_id": "sess-1",
            "user_id": "old_user",
            "execution_time_ms": 10,
            "row_count": 0,
            "created_at": MagicMock(isoformat=lambda: "2026-01-01T00:00:00Z"),
            "raw_result": {},
            "org_id": None,
        })

        superadmin = {"roles": ["admin"], "org_id": None, "username": "root"}

        result = await get_audit_trail(trace_id="TRC-legacy", user=superadmin, pg=mock_pg)
        assert result.trace_id == "TRC-legacy"


# ---------------------------------------------------------------------------
# M3: Cache MCP tenant-prefixed keys
# ---------------------------------------------------------------------------

class TestCacheTenantIsolation:
    """Verify cache keys are namespaced by org_id to prevent cross-tenant leakage."""

    def test_tenant_key_without_org_id(self) -> None:
        """Without org_id, key is returned as-is (backward compatible)."""
        assert _cache_server._tenant_key("question_hash_123", org_id=None) == "question_hash_123"

    def test_tenant_key_with_org_id(self) -> None:
        """With org_id, key is prefixed with org namespace."""
        assert _cache_server._tenant_key("question_hash_123", org_id=1000) == "org:1000:question_hash_123"

    def test_tenant_key_different_orgs_produce_different_keys(self) -> None:
        """The same base key must produce different namespaced keys per org."""
        key_a = _cache_server._tenant_key("supplier_query", org_id=1000)
        key_b = _cache_server._tenant_key("supplier_query", org_id=2000)
        assert key_a != key_b
        assert "1000" in key_a
        assert "2000" in key_b

    @pytest.mark.asyncio
    async def test_check_cache_uses_org_prefix(self) -> None:
        """check_cache_impl must look up the org-prefixed key."""
        mock_redis = MagicMock()
        mock_redis.get_cache = AsyncMock(return_value={"data": "cached"})

        await _cache_server.check_cache_impl(mock_redis, key="mykey", org_id=1000)

        mock_redis.get_cache.assert_called_once_with("org:1000:mykey")

    @pytest.mark.asyncio
    async def test_check_cache_without_org_uses_plain_key(self) -> None:
        """check_cache_impl without org_id uses the plain key (backward compat)."""
        mock_redis = MagicMock()
        mock_redis.get_cache = AsyncMock(return_value=None)

        await _cache_server.check_cache_impl(mock_redis, key="mykey", org_id=None)

        mock_redis.get_cache.assert_called_once_with("mykey")

    @pytest.mark.asyncio
    async def test_cache_result_uses_org_prefix(self) -> None:
        """cache_result_impl must store under the org-prefixed key."""
        mock_redis = MagicMock()
        mock_redis.set_cache = AsyncMock()

        result = await _cache_server.cache_result_impl(
            mock_redis, key="mykey", value={"data": 1}, ttl=300, org_id=2000
        )

        mock_redis.set_cache.assert_called_once_with(
            "org:2000:mykey", {"data": 1}, 300
        )
        assert result["key"] == "org:2000:mykey"

    @pytest.mark.asyncio
    async def test_cache_result_without_org_uses_plain_key(self) -> None:
        """cache_result_impl without org_id uses the plain key (backward compat)."""
        mock_redis = MagicMock()
        mock_redis.set_cache = AsyncMock()

        result = await _cache_server.cache_result_impl(
            mock_redis, key="mykey", value={"data": 1}, ttl=300, org_id=None
        )

        mock_redis.set_cache.assert_called_once_with("mykey", {"data": 1}, 300)
        assert result["key"] == "mykey"
