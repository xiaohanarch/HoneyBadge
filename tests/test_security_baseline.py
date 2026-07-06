"""Tests for security baseline hardening.

Covers:
  - ServerConfig production-mode secret validation (S2)
  - Audit endpoint user isolation (S4)
  - Token revocation store (S9)
  - JWT JTI generation (S9)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from honeybadge.server.auth import create_access_token, decode_token
from honeybadge.server.security import TokenRevocationStore, extract_jti


# ---------------------------------------------------------------------------
# S2: ServerConfig production validation
# ---------------------------------------------------------------------------

class TestProductionConfigValidation:
    """Verify that insecure defaults are rejected in production mode."""

    def test_dev_mode_allows_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """In dev mode (ENV not set), insecure defaults should be allowed."""
        monkeypatch.delenv("ENV", raising=False)
        from honeybadge.server.config import ServerConfig

        config = ServerConfig.from_env()
        # Should not raise — dev mode tolerates defaults
        assert config.jwt_secret == "change-me-in-production"

    def test_production_rejects_default_jwt_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production mode must abort if JWT_SECRET is the insecure default."""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("JWT_SECRET", "change-me-in-production")
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        monkeypatch.setenv("NEBULA_PASSWORD", "secure-random-password")
        from honeybadge.server.config import ServerConfig

        with pytest.raises(SystemExit):
            ServerConfig.from_env()

    def test_production_rejects_short_jwt_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production mode must abort if JWT_SECRET is too short (<32 chars)."""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("JWT_SECRET", "short")
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        monkeypatch.setenv("NEBULA_PASSWORD", "secure-random-password")
        from honeybadge.server.config import ServerConfig

        with pytest.raises(SystemExit):
            ServerConfig.from_env()

    def test_production_rejects_empty_llm_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production mode must abort if LLM_API_KEY is empty."""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("JWT_SECRET", "a" * 64)
        monkeypatch.setenv("LLM_API_KEY", "")
        monkeypatch.setenv("NEBULA_PASSWORD", "secure-random-password")
        from honeybadge.server.config import ServerConfig

        with pytest.raises(SystemExit):
            ServerConfig.from_env()

    def test_production_accepts_secure_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Production mode should accept properly configured secrets."""
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("JWT_SECRET", "a" * 64)
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        monkeypatch.setenv("NEBULA_PASSWORD", "secure-random-password")
        from honeybadge.server.config import ServerConfig

        config = ServerConfig.from_env()
        assert config.jwt_secret == "a" * 64
        assert config.llm_api_key == "sk-test-key"


# ---------------------------------------------------------------------------
# S9: JWT JTI generation
# ---------------------------------------------------------------------------

class TestJtiGeneration:
    """Verify that JWTs carry a JTI for revocation tracking."""

    def test_access_token_has_jti(self) -> None:
        token = create_access_token({"sub": "admin"}, "test-secret", 60)
        payload = decode_token(token, "test-secret")
        assert payload is not None
        assert "jti" in payload
        assert payload["jti"]  # non-empty

    def test_refresh_token_has_jti(self) -> None:
        from honeybadge.server.auth import create_refresh_token

        token = create_refresh_token({"sub": "admin"}, "test-secret", 7)
        payload = decode_token(token, "test-secret")
        assert payload is not None
        assert "jti" in payload

    def test_each_token_has_unique_jti(self) -> None:
        t1 = create_access_token({"sub": "admin"}, "test-secret", 60)
        t2 = create_access_token({"sub": "admin"}, "test-secret", 60)
        p1 = decode_token(t1, "test-secret")
        p2 = decode_token(t2, "test-secret")
        assert p1 and p2
        assert p1["jti"] != p2["jti"]

    def test_extract_jti_from_payload_without_jti(self) -> None:
        """Synthetic JTI should be derived when jti claim is absent."""
        payload: dict[str, Any] = {"sub": "admin", "iat": 1234567890}
        jti = extract_jti(payload)
        assert jti.startswith("synthetic:")
        assert "admin" in jti


# ---------------------------------------------------------------------------
# S9: TokenRevocationStore
# ---------------------------------------------------------------------------

class TestTokenRevocationStore:
    """Verify Redis-backed token blacklist behavior."""

    @pytest.mark.asyncio
    async def test_revoke_then_check(self) -> None:
        redis = MagicMock()
        redis.setex = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")
        store = TokenRevocationStore(redis)

        await store.revoke("test-jti", 3600)
        assert await store.is_revoked("test-jti") is True

    @pytest.mark.asyncio
    async def test_not_revoked_returns_false(self) -> None:
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        store = TokenRevocationStore(redis)

        assert await store.is_revoked("unknown-jti") is False

    @pytest.mark.asyncio
    async def test_no_redis_fails_open(self) -> None:
        """Without Redis, revocation is a no-op (fail-open)."""
        store = TokenRevocationStore(None)

        # revoke should not raise
        await store.revoke("test-jti", 3600)
        # is_revoked should return False (fail-open)
        assert await store.is_revoked("test-jti") is False

    @pytest.mark.asyncio
    async def test_redis_error_fails_open(self) -> None:
        """Redis errors should not lock users out."""
        redis = MagicMock()
        redis.get = AsyncMock(side_effect=Exception("connection lost"))
        store = TokenRevocationStore(redis)

        assert await store.is_revoked("test-jti") is False

    @pytest.mark.asyncio
    async def test_revoke_empty_jti_noop(self) -> None:
        redis = MagicMock()
        redis.setex = AsyncMock()
        store = TokenRevocationStore(redis)

        await store.revoke("", 3600)
        redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_zero_ttl_noop(self) -> None:
        redis = MagicMock()
        redis.setex = AsyncMock()
        store = TokenRevocationStore(redis)

        await store.revoke("test-jti", 0)
        redis.setex.assert_not_called()


# ---------------------------------------------------------------------------
# S4: Audit endpoint user isolation
# ---------------------------------------------------------------------------

class TestAuditIsolationHelpers:
    """Verify audit access control helper functions."""

    def test_admin_is_privileged(self) -> None:
        from honeybadge.server.audit import _is_privileged

        assert _is_privileged({"roles": ["admin"]}) is True

    def test_auditor_is_privileged(self) -> None:
        from honeybadge.server.audit import _is_privileged

        assert _is_privileged({"roles": ["auditor"]}) is True

    def test_analyst_not_privileged(self) -> None:
        from honeybadge.server.audit import _is_privileged

        assert _is_privileged({"roles": ["analyst"]}) is False

    def test_no_roles_not_privileged(self) -> None:
        from honeybadge.server.audit import _is_privileged

        assert _is_privileged({"roles": []}) is False
        assert _is_privileged({}) is False

    def test_user_identity_from_username(self) -> None:
        from honeybadge.server.audit import _user_identity

        assert _user_identity({"username": "alice"}) == "alice"

    def test_user_identity_fallback_to_sub(self) -> None:
        from honeybadge.server.audit import _user_identity

        assert _user_identity({"sub": "user-123"}) == "user-123"

    def test_user_identity_empty(self) -> None:
        from honeybadge.server.audit import _user_identity

        assert _user_identity({}) == ""
