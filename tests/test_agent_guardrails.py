"""Tests for agent orchestration guardrails (tool-layer hard constraints).

Covers:
  - A1a: validate_and_execute fail-closed on missing/invalid user_context
  - A1b: L4 numeric fidelity enforce mode
  - A1c: Investigation round counter
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from honeybadge.llm.numeric_fidelity import (
    NumericFidelityViolation,
    check_and_log_fidelity,
    validate_numeric_fidelity,
)
from honeybadge.protocols.guardrails import (
    check_investigation_round,
    get_investigation_rounds,
    reset_investigation_counter,
)


# ---------------------------------------------------------------------------
# A1b: L4 Numeric Fidelity — enforce mode
# ---------------------------------------------------------------------------

class TestL4EnforceMode:
    """Verify L4 can block (not just log) when enforce mode is active."""

    def test_log_only_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default behavior: mismatch logs but does not raise."""
        monkeypatch.delenv("HONEYBADGE_L4_ENFORCE", raising=False)
        # Should NOT raise
        check_and_log_fidelity(
            summary="结果有 999 个供应商",
            raw_results=[{"count": 42}],
            columns=["count"],
            trace_id="test-trace",
        )

    def test_enforce_mode_raises_on_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Enforce mode: mismatch raises NumericFidelityViolation."""
        monkeypatch.setenv("HONEYBADGE_L4_ENFORCE", "1")
        with pytest.raises(NumericFidelityViolation):
            check_and_log_fidelity(
                summary="结果有 999 个供应商",
                raw_results=[{"count": 42}],
                columns=["count"],
                trace_id="test-trace",
            )

    def test_enforce_mode_passes_when_correct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Enforce mode: no raise when numbers match."""
        monkeypatch.setenv("HONEYBADGE_L4_ENFORCE", "1")
        # Should NOT raise — 42 appears in both raw and summary
        check_and_log_fidelity(
            summary="共有 42 个供应商",
            raw_results=[{"count": 42}],
            columns=["count"],
            trace_id="test-trace",
        )

    def test_validate_returns_correct_result(self) -> None:
        """The underlying validator correctly detects mismatches."""
        result = validate_numeric_fidelity(
            summary="总数 100",
            raw_results=[{"total": 200}],
            columns=["total"],
        )
        assert not result.passed
        assert "200" in result.detail

    def test_validate_passes_on_match(self) -> None:
        result = validate_numeric_fidelity(
            summary="总数 200",
            raw_results=[{"total": 200}],
            columns=["total"],
        )
        assert result.passed


# ---------------------------------------------------------------------------
# A1c: Investigation round counter
# ---------------------------------------------------------------------------

class TestInvestigationRoundGuard:
    """Verify the investigation round hard limit."""

    @pytest.mark.asyncio
    async def test_allows_first_n_rounds(self) -> None:
        reset_investigation_counter("test-trace-1")
        for i in range(1, 6):  # default max is 5
            allowed, count = await check_investigation_round("test-trace-1", redis=None, max_rounds=5)
            assert allowed, f"Round {i} should be allowed"
            assert count == i

    @pytest.mark.asyncio
    async def test_blocks_after_max(self) -> None:
        reset_investigation_counter("test-trace-2")
        max_rounds = 3
        for _ in range(max_rounds):
            await check_investigation_round("test-trace-2", redis=None, max_rounds=max_rounds)

        allowed, count = await check_investigation_round("test-trace-2", redis=None, max_rounds=max_rounds)
        assert not allowed
        assert count == max_rounds + 1

    @pytest.mark.asyncio
    async def test_empty_trace_id_always_allowed(self) -> None:
        allowed, count = await check_investigation_round("", redis=None)
        assert allowed
        assert count == 0

    @pytest.mark.asyncio
    async def test_redis_increments(self) -> None:
        redis = MagicMock()
        redis.incr = AsyncMock(side_effect=[1, 2, 3])
        redis.expire = AsyncMock()

        allowed1, count1 = await check_investigation_round("redis-trace", redis=redis, max_rounds=5)
        assert allowed1 and count1 == 1

        allowed2, count2 = await check_investigation_round("redis-trace", redis=redis, max_rounds=5)
        assert allowed2 and count2 == 2

        # Redis calls verified
        assert redis.incr.call_count == 2

    @pytest.mark.asyncio
    async def test_redis_blocks_when_exceeded(self) -> None:
        redis = MagicMock()
        redis.incr = AsyncMock(return_value=6)  # exceeds max of 5
        redis.expire = AsyncMock()

        allowed, count = await check_investigation_round("redis-trace-blocked", redis=redis, max_rounds=5)
        assert not allowed
        assert count == 6

    @pytest.mark.asyncio
    async def test_redis_error_falls_back_to_memory(self) -> None:
        redis = MagicMock()
        redis.incr = AsyncMock(side_effect=Exception("connection lost"))

        # Should fall back to in-memory and still work
        allowed, count = await check_investigation_round("fallback-trace", redis=redis, max_rounds=5)
        assert allowed
        assert count == 1

    @pytest.mark.asyncio
    async def test_reset_clears_counter(self) -> None:
        reset_investigation_counter("reset-trace")
        await check_investigation_round("reset-trace", redis=None, max_rounds=5)
        assert get_investigation_rounds("reset-trace") == 1

        reset_investigation_counter("reset-trace")
        assert get_investigation_rounds("reset-trace") == 0

    @pytest.mark.asyncio
    async def test_env_var_sets_default_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The default max_rounds should respect the env var."""
        import importlib

        monkeypatch.setenv("HONEYBADGE_MAX_INVESTIGATION_ROUNDS", "3")
        # Re-import to pick up the env var
        import honeybadge.protocols.guardrails as g
        importlib.reload(g)
        assert g._MAX_INVESTIGATION_ROUNDS == 3

        # Restore
        monkeypatch.delenv("HONEYBADGE_MAX_INVESTIGATION_ROUNDS", raising=False)
        importlib.reload(g)


# ---------------------------------------------------------------------------
# A1a: validate_and_execute fail-closed
# ---------------------------------------------------------------------------

class TestL3FailClosed:
    """Verify L3 enforcement is fail-closed by default."""

    def _make_impl(self) -> Any:
        """Import validate_and_execute_impl after sys.path setup."""
        import sys

        mcp_path = os.path.join(os.path.dirname(__file__), "..", "mcp-servers", "honeybadge-nebula-mcp")
        if mcp_path not in sys.path:
            sys.path.insert(0, mcp_path)
        from server import validate_and_execute_impl

        return validate_and_execute_impl

    @pytest.mark.asyncio
    async def test_rejects_none_user_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When user_context is None and fail-open is off, query is rejected."""
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)
        impl = self._make_impl()

        result = await impl(
            nebula=MagicMock(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context=None,
        )
        assert result["success"] is False
        assert result["error"] == "L3_NO_USER_CONTEXT"

    @pytest.mark.asyncio
    async def test_rejects_manager_user_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """user_id='manager' should be rejected."""
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)
        impl = self._make_impl()

        result = await impl(
            nebula=MagicMock(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context={"user_id": "manager"},
        )
        assert result["success"] is False
        assert result["error"] == "L3_INVALID_USER_ID"

    @pytest.mark.asyncio
    async def test_rejects_anonymous_user_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """user_id='anonymous' should be rejected."""
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)
        impl = self._make_impl()

        result = await impl(
            nebula=MagicMock(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context={"user_id": "anonymous"},
        )
        assert result["success"] is False
        assert result["error"] == "L3_INVALID_USER_ID"

    @pytest.mark.asyncio
    async def test_rejects_empty_user_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty user_id should be rejected."""
        monkeypatch.delenv("HONEYBADGE_L3_FAIL_OPEN", raising=False)
        impl = self._make_impl()

        result = await impl(
            nebula=MagicMock(),
            validator=MagicMock(),
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context={"user_id": ""},
        )
        assert result["success"] is False
        assert result["error"] == "L3_INVALID_USER_ID"

    @pytest.mark.asyncio
    async def test_fail_open_allows_none_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When HONEYBADGE_L3_FAIL_OPEN=1, None user_context is allowed (dev/test)."""
        monkeypatch.setenv("HONEYBADGE_L3_FAIL_OPEN", "1")
        impl = self._make_impl()

        # This should proceed past the L0 check (will fail later at L1
        # because the mock validator returns valid=True, but we just
        # need to verify it doesn't return L3_NO_USER_CONTEXT)
        mock_validator = MagicMock()
        mock_validator.validate_syntax.return_value = MagicMock(valid=True, errors=[])
        mock_validator.validate_schema.return_value = MagicMock(valid=True, errors=[])

        # Mock the rest of the pipeline to avoid actual Nebula execution.
        # nebula.execute is awaited, so AsyncMock is required.
        mock_nebula = MagicMock()
        mock_nebula.execute = AsyncMock(return_value=MagicMock(columns=[], rows=[]))

        # The key assertion is that the error is NOT L3_NO_USER_CONTEXT
        result = await impl(
            nebula=mock_nebula,
            validator=mock_validator,
            ngql="MATCH (n:Supplier) RETURN n.Supplier.name AS name",
            user_context=None,
        )
        # It should proceed past L0 (might fail later, but not with L3_NO_USER_CONTEXT)
        assert result.get("error") != "L3_NO_USER_CONTEXT"
