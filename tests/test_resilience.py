"""Tests for resilience engineering: circuit breaker and health checks.

Covers:
  - R1: Circuit breaker state machine (CLOSED → OPEN → HALF_OPEN → CLOSED)
  - R2: Circuit breaker as decorator and context manager
  - R3: Circuit breaker with expected_exception filtering
  - R4: Health endpoint returns 503 when degraded
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from honeybadge.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)


# ---------------------------------------------------------------------------
# R1: Circuit breaker state machine
# ---------------------------------------------------------------------------

class TestCircuitBreakerStateMachine:
    """Verify the CLOSED → OPEN → HALF_OPEN → CLOSED transitions."""

    @pytest.mark.asyncio
    async def test_starts_closed(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self) -> None:
        """After `failure_threshold` consecutive failures, breaker opens."""
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=60)

        async def failing_call() -> None:
            raise ConnectionError("service down")

        for _ in range(3):
            with pytest.raises(ConnectionError):
                await cb.call(failing_call)

        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_open_blocks_calls(self) -> None:
        """When OPEN, calls raise CircuitBreakerOpenError immediately."""
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=60)

        async def failing_call() -> None:
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            await cb.call(failing_call)
        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(failing_call)

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self) -> None:
        """After recovery_timeout, OPEN transitions to HALF_OPEN on next call."""
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.1)

        async def failing_call() -> None:
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            await cb.call(failing_call)
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        async def succeeding_call() -> str:
            return "ok"

        # This call should transition to HALF_OPEN and succeed
        result = await cb.call(succeeding_call)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self) -> None:
        """A failure in HALF_OPEN sends the breaker back to OPEN."""
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.1)

        async def failing_call() -> None:
            raise ConnectionError("down")

        # Open the breaker
        with pytest.raises(ConnectionError):
            await cb.call(failing_call)

        await asyncio.sleep(0.15)

        # Next call transitions to HALF_OPEN, then fails
        with pytest.raises(ConnectionError):
            await cb.call(failing_call)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self) -> None:
        """A success in CLOSED resets the failure counter."""
        cb = CircuitBreaker(name="test", failure_threshold=3)

        async def failing_call() -> None:
            raise ConnectionError("down")

        async def succeeding_call() -> str:
            return "ok"

        # Two failures (below threshold)
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(failing_call)
        assert cb.failure_count == 2

        # Success resets
        result = await cb.call(succeeding_call)
        assert result == "ok"
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# R2: Decorator and context manager usage
# ---------------------------------------------------------------------------

class TestCircuitBreakerDecorator:
    """Verify the breaker works as a decorator."""

    @pytest.mark.asyncio
    async def test_decorator_wraps_async_function(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=3)

        @cb
        async def fetch_data() -> str:
            return "data"

        result = await fetch_data()
        assert result == "data"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_decorator_records_failures(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=2)

        @cb
        async def fetch_data() -> str:
            raise ConnectionError("timeout")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                await fetch_data()

        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerContextManager:
    """Verify the breaker works as an async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_success(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=3)

        async with cb:
            # Simulate work
            pass

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_context_manager_failure(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=1)

        with pytest.raises(ConnectionError):
            async with cb:
                raise ConnectionError("boom")

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_context_manager_open_blocks(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=60)

        with pytest.raises(ConnectionError):
            async with cb:
                raise ConnectionError("first failure")

        with pytest.raises(CircuitBreakerOpenError):
            async with cb:
                pass


# ---------------------------------------------------------------------------
# R3: Expected exception filtering
# ---------------------------------------------------------------------------

class TestCircuitBreakerExceptionFiltering:
    """Verify only expected_exception counts as a failure."""

    @pytest.mark.asyncio
    async def test_unexpected_exception_does_not_open(self) -> None:
        """ValueError is not expected_exception — should not count."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            expected_exception=ConnectionError,
        )

        async def bad_call() -> None:
            raise ValueError("programmer error")

        with pytest.raises(ValueError):
            await cb.call(bad_call)

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_expected_exception_opens(self) -> None:
        """ConnectionError is expected_exception — should count."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            expected_exception=ConnectionError,
        )

        async def bad_call() -> None:
            raise ConnectionError("network down")

        with pytest.raises(ConnectionError):
            await cb.call(bad_call)

        assert cb.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# R4: Health endpoint returns 503 when degraded
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """Verify the health endpoint returns appropriate status info."""

    @pytest.mark.asyncio
    async def test_healthy_returns_healthy_status(self) -> None:
        from honeybadge.server.health import health_check

        # Mock Request with healthy services on app.state
        mock_request = MagicMock()
        mock_app = MagicMock()

        mock_redis = MagicMock()
        mock_redis._client = MagicMock()
        mock_redis._client.ping = AsyncMock()

        mock_pg = MagicMock()
        mock_pg._pool = MagicMock()
        # asyncpg pool.acquire() is an async context manager
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pg._pool.acquire = MagicMock(return_value=mock_cm)

        mock_nebula = MagicMock()
        mock_nebula._pool = MagicMock()

        mock_app.state.redis = mock_redis
        mock_app.state.pg = mock_pg
        mock_app.state.nebula = mock_nebula
        mock_request.app = mock_app

        result = await health_check(mock_request)

        assert result["status"] == "healthy"
        assert "version" in result
        assert "services" in result
        assert result["services"]["redis"]["status"] == "up"

    @pytest.mark.asyncio
    async def test_degraded_status_when_redis_down(self) -> None:
        """When Redis is down, health status should be 'degraded'."""
        from honeybadge.server.health import health_check

        mock_request = MagicMock()
        mock_app = MagicMock()

        mock_redis = MagicMock()
        mock_redis._client = None  # not connected

        mock_app.state.redis = mock_redis
        mock_app.state.pg = None
        mock_app.state.nebula = None
        mock_request.app = mock_app

        result = await health_check(mock_request)

        assert result["status"] == "degraded"
        assert result["services"]["redis"]["status"] == "down"

    @pytest.mark.asyncio
    async def test_degraded_status_when_pg_down(self) -> None:
        """When PostgreSQL is down, health status should be 'degraded'."""
        from honeybadge.server.health import health_check

        mock_request = MagicMock()
        mock_app = MagicMock()

        # Redis is up
        mock_redis = MagicMock()
        mock_redis._client = MagicMock()
        mock_redis._client.ping = AsyncMock()
        mock_app.state.redis = mock_redis

        # PG is not connected
        mock_app.state.pg = None
        mock_app.state.nebula = None
        mock_request.app = mock_app

        result = await health_check(mock_request)

        assert result["status"] == "degraded"
        assert result["services"]["postgres"]["status"] == "down"


# ---------------------------------------------------------------------------
# Observability: breaker state is inspectable
# ---------------------------------------------------------------------------

class TestCircuitBreakerObservability:
    """Verify the breaker exposes state for metrics/monitoring."""

    @pytest.mark.asyncio
    async def test_last_error_recorded(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=1)

        async def failing_call() -> None:
            raise ConnectionError("specific error message")

        with pytest.raises(ConnectionError):
            await cb.call(failing_call)

        assert cb.last_error is not None
        assert "specific error message" in cb.last_error

    @pytest.mark.asyncio
    async def test_reset_clears_state(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=1)

        async def failing_call() -> None:
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            await cb.call(failing_call)
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.last_error is None

    def test_state_is_enum(self) -> None:
        cb = CircuitBreaker(name="test")
        assert isinstance(cb.state, CircuitState)
        assert cb.state.value == "closed"
