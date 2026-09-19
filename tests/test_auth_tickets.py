"""Tests for the auth-ticket identity chain (MCP L0 verification).

Covers:
  - TicketStore: issue/resolve roundtrip, use-count limit, TTL expiry
  - POST /api/auth/ticket + GET /api/internal/ticket/{t} endpoints
  - validate_and_execute_impl: a verified identity OVERRIDES the
    self-reported user_id; invalid/expired tokens and missing tokens
    (HONEYBADGE_REQUIRE_AUTH=1) are rejected fail-closed
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from honeybadge.db.nebula import NebulaQueryResult
from honeybadge.permission_service.config import PERMISSION_CONFIG
from honeybadge.server.auth import create_access_token
from honeybadge.server.tickets import TicketStore

_TEST_SECRET = "test-secret"
_MCP_PATH = os.path.join(os.path.dirname(__file__), "..", "mcp-servers", "honeybadge-nebula-mcp")


def _mcp_module() -> Any:
    """Import the MCP server module (tests/conftest.py style sys.path insert)."""
    if _MCP_PATH not in sys.path:
        sys.path.insert(0, _MCP_PATH)
    import server as mcp_server

    return mcp_server


def _token(username: str, secret: str = _TEST_SECRET, expire_minutes: int = 60) -> str:
    return create_access_token(
        {"sub": f"id-{username}", "username": username, "roles": ["analyst"], "org_id": None},
        secret,
        expire_minutes,
    )


def _mock_nebula() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock(
        return_value=NebulaQueryResult(
            columns=["n"], rows=[{"n": 1}], execution_time_ms=5, success=True,
        )
    )
    return mock


# ---------------------------------------------------------------------------
# TicketStore
# ---------------------------------------------------------------------------
class TestTicketStore:
    def test_roundtrip(self) -> None:
        store = TicketStore()
        ticket, ttl = store.issue("jwt-value")
        assert ttl > 0
        assert store.resolve(ticket) == "jwt-value"

    def test_use_count_exhaustion(self) -> None:
        store = TicketStore(max_uses=2)
        ticket, _ = store.issue("jwt-value")
        assert store.resolve(ticket) == "jwt-value"
        assert store.resolve(ticket) == "jwt-value"
        assert store.resolve(ticket) is None

    def test_unknown_ticket(self) -> None:
        store = TicketStore()
        assert store.resolve("no-such-ticket") is None

    def test_ttl_expiry(self) -> None:
        store = TicketStore(ttl_seconds=0)
        ticket, _ = store.issue("jwt-value")
        assert store.resolve(ticket) is None


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------
class TestTicketEndpoints:
    def _client(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        from fastapi.testclient import TestClient

        from honeybadge.server.app import create_app
        from honeybadge.server.config import ServerConfig

        monkeypatch.setenv("HONEYBADGE_SERVICE_TOKEN", "svc-token")
        config = ServerConfig(host="127.0.0.1", port=8090, jwt_secret=_TEST_SECRET)
        app = create_app(config)
        return TestClient(app)

    def test_issue_and_resolve_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        token = _token("analyst")
        with self._client(monkeypatch) as client:
            resp = client.post("/api/auth/ticket", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
            ticket = resp.json()["data"]["ticket"]
            assert isinstance(ticket, str) and ticket

            resp2 = client.get(
                f"/api/internal/ticket/{ticket}", headers={"X-HB-Service-Token": "svc-token"}
            )
            assert resp2.status_code == 200
            assert resp2.json()["data"]["token"] == token

    def test_issue_requires_valid_bearer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with self._client(monkeypatch) as client:
            resp = client.post("/api/auth/ticket")
            assert resp.status_code == 401
            resp2 = client.post(
                "/api/auth/ticket", headers={"Authorization": "Bearer not-a-jwt"}
            )
            assert resp2.status_code == 401

    def test_resolve_requires_service_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        token = _token("analyst")
        with self._client(monkeypatch) as client:
            issued = client.post("/api/auth/ticket", headers={"Authorization": f"Bearer {token}"})
            ticket = issued.json()["data"]["ticket"]

            no_header = client.get(f"/api/internal/ticket/{ticket}")
            assert no_header.status_code == 403
            wrong_header = client.get(
                f"/api/internal/ticket/{ticket}", headers={"X-HB-Service-Token": "wrong"}
            )
            assert wrong_header.status_code == 403

    def test_resolve_unknown_ticket_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with self._client(monkeypatch) as client:
            resp = client.get(
                "/api/internal/ticket/nope", headers={"X-HB-Service-Token": "svc-token"}
            )
            assert resp.status_code == 404

    def test_resolve_fails_closed_without_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi.testclient import TestClient

        from honeybadge.server.app import create_app
        from honeybadge.server.config import ServerConfig

        monkeypatch.delenv("HONEYBADGE_SERVICE_TOKEN", raising=False)
        config = ServerConfig(host="127.0.0.1", port=8090, jwt_secret=_TEST_SECRET)
        with TestClient(create_app(config)) as client:
            resp = client.get(
                "/api/internal/ticket/anything", headers={"X-HB-Service-Token": "svc-token"}
            )
            assert resp.status_code == 403


# ---------------------------------------------------------------------------
# validate_and_execute_impl auth verification
# ---------------------------------------------------------------------------
class TestMcpAuthVerification:
    @pytest.mark.asyncio
    async def test_verified_identity_overrides_self_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Token says 'analyst' but the caller self-reports 'admin' —
        permissions must be fetched for the VERIFIED identity."""
        mcp = _mcp_module()
        monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
        monkeypatch.delenv("HONEYBADGE_REQUIRE_AUTH", raising=False)
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)

        captured: dict[str, str] = {}

        async def fake_perms(uid: str) -> dict[str, Any]:
            captured["uid"] = uid
            return asdict(PERMISSION_CONFIG["admin"])

        monkeypatch.setattr(mcp, "get_user_permissions_impl", fake_perms)

        result = await mcp.validate_and_execute_impl(
            nebula=_mock_nebula(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context={"user_id": "admin", "auth_token": _token("analyst")},
        )
        assert result["success"] is True
        assert captured["uid"] == "analyst"

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mcp = _mcp_module()
        monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)

        result = await mcp.validate_and_execute_impl(
            nebula=_mock_nebula(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context={"user_id": "admin", "auth_token": _token("admin", secret="wrong")},
        )
        assert result["success"] is False
        assert result["error"] == "L0_AUTH_INVALID"

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import jwt as pyjwt

        mcp = _mcp_module()
        monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)

        expired = pyjwt.encode(
            {"sub": "u", "username": "analyst", "exp": 1}, _TEST_SECRET, algorithm="HS256"
        )
        result = await mcp.validate_and_execute_impl(
            nebula=_mock_nebula(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context={"user_id": "admin", "auth_token": expired},
        )
        assert result["success"] is False
        assert result["error"] == "L0_AUTH_INVALID"

    @pytest.mark.asyncio
    async def test_require_auth_rejects_missing_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mcp = _mcp_module()
        monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
        monkeypatch.setenv("HONEYBADGE_REQUIRE_AUTH", "1")
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)

        result = await mcp.validate_and_execute_impl(
            nebula=_mock_nebula(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context={"user_id": "admin"},
        )
        assert result["success"] is False
        assert result["error"] == "L0_AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_unresolvable_ticket_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mcp = _mcp_module()
        monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
        monkeypatch.delenv("HONEYBADGE_SERVER_URL", raising=False)
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)

        result = await mcp.validate_and_execute_impl(
            nebula=_mock_nebula(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context={"user_id": "admin", "auth_ticket": "bogus-ticket"},
        )
        assert result["success"] is False
        assert result["error"] == "L0_AUTH_INVALID"

    @pytest.mark.asyncio
    async def test_legacy_path_without_token_still_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without REQUIRE_AUTH, a plain user_id (no token) keeps the
        legacy fail-closed-on-forbidden / open-on-valid behavior."""
        mcp = _mcp_module()
        monkeypatch.setenv("JWT_SECRET", _TEST_SECRET)
        monkeypatch.delenv("HONEYBADGE_REQUIRE_AUTH", raising=False)
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)

        captured: dict[str, str] = {}

        async def fake_perms(uid: str) -> dict[str, Any]:
            captured["uid"] = uid
            return asdict(PERMISSION_CONFIG["admin"])

        monkeypatch.setattr(mcp, "get_user_permissions_impl", fake_perms)

        result = await mcp.validate_and_execute_impl(
            nebula=_mock_nebula(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context={"user_id": "admin"},
        )
        assert result["success"] is True
        assert captured["uid"] == "admin"
