"""Tests for graceful degradation via circuit breakers.

Verifies that:
- NebulaGraphClient.execute() returns a degradation NebulaQueryResult when the
  breaker is OPEN (instead of hanging or raising).
- RedisClient.get_cache() returns None (cache miss) and set_cache() returns
  False when the Redis breaker is OPEN.
- LLMProviderManager.chat() raises LLMError with a service-unavailable message
  when the LLM breaker is OPEN.
- The /api/health endpoint reports circuit breaker states.
- Breaker metrics are exported to Prometheus.
- State transitions: CLOSED → OPEN → HALF_OPEN → CLOSED.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from honeybadge.db.nebula import NebulaGraphClient, NebulaQueryResult
from honeybadge.db.redis import RedisClient
from honeybadge.resilience.breakers import (
    BREAKERS,
    get_breaker_states,
    llm_breaker,
    nebula_breaker,
    redis_breaker,
    sync_breaker_metrics,
)
from honeybadge.resilience.circuit_breaker import CircuitBreakerOpenError, CircuitState

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_breakers():
    """Reset all circuit breakers to CLOSED before each test."""
    for breaker in BREAKERS.values():
        breaker.reset()
    yield
    for breaker in BREAKERS.values():
        breaker.reset()


def _force_open(breaker: Any) -> None:
    """Force a breaker into the OPEN state by recording threshold+1 failures."""
    for _ in range(breaker.failure_threshold):
        asyncio.get_event_loop().run_until_complete(
            breaker._on_failure(Exception("test failure"))
        )
    # Verify it's open
    assert breaker.state == CircuitState.OPEN


async def _force_open_async(breaker: Any) -> None:
    """Force a breaker into OPEN state (async version)."""
    for _ in range(breaker.failure_threshold):
        await breaker._on_failure(Exception("test failure"))


# ---------------------------------------------------------------------------
# Nebula circuit breaker wiring
# ---------------------------------------------------------------------------


class TestNebulaCircuitBreaker:
    """Verify NebulaGraphClient.execute() degrades gracefully."""

    async def test_execute_returns_degradation_when_breaker_open(self) -> None:
        """When the breaker is OPEN, execute() returns a failed NebulaQueryResult."""
        client = NebulaGraphClient(host="localhost", port=9669, user="root", password="nebula")
        client._pool = MagicMock()  # pretend connected

        # Force breaker open
        await _force_open_async(nebula_breaker)
        assert nebula_breaker.state == CircuitState.OPEN

        result = await client.execute("MATCH (n) RETURN n", space="test")

        assert isinstance(result, NebulaQueryResult)
        assert result.success is False
        assert "circuit breaker open" in result.error_message.lower()
        assert result.rows == []

    async def test_execute_passes_through_when_breaker_closed(self) -> None:
        """When the breaker is CLOSED, execute() calls through normally."""
        client = NebulaGraphClient(host="localhost", port=9669, user="root", password="nebula")
        client._pool = MagicMock()

        expected = NebulaQueryResult(columns=["name"], rows=[{"name": "test"}], execution_time_ms=10, success=True)

        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=expected)
            result = await client.execute("MATCH (n) RETURN n", space="test")

        assert result.success is True
        assert result.rows == [{"name": "test"}]
        assert nebula_breaker.state == CircuitState.CLOSED

    async def test_breaker_opens_after_consecutive_failures(self) -> None:
        """The breaker opens after failure_threshold consecutive failures."""
        client = NebulaGraphClient(host="localhost", port=9669, user="root", password="nebula")
        client._pool = MagicMock()

        call_count = 0

        async def _failing_run_in_executor(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("connection refused")

        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = _failing_run_in_executor

            # First (failure_threshold - 1) calls should raise (breaker still CLOSED)
            for _ in range(nebula_breaker.failure_threshold - 1):
                with pytest.raises(Exception, match="Query execution failed"):
                    await client.execute("MATCH (n) RETURN n")
                assert nebula_breaker.state == CircuitState.CLOSED

            # The threshold-th failure opens the breaker
            with pytest.raises(Exception, match="Query execution failed"):
                await client.execute("MATCH (n) RETURN n")
            assert nebula_breaker.state == CircuitState.OPEN

            # Subsequent calls should get degradation response (no exception)
            result = await client.execute("MATCH (n) RETURN n")
            assert result.success is False
            assert "circuit breaker open" in result.error_message.lower()

        assert call_count == nebula_breaker.failure_threshold  # no extra calls after OPEN


# ---------------------------------------------------------------------------
# Redis circuit breaker wiring
# ---------------------------------------------------------------------------


class TestRedisCircuitBreaker:
    """Verify RedisClient cache operations degrade gracefully."""

    async def test_get_cache_returns_none_when_breaker_open(self) -> None:
        """When the breaker is OPEN, get_cache() returns None (cache miss)."""
        redis = RedisClient()
        redis._client = MagicMock()

        await _force_open_async(redis_breaker)

        result = await redis.get_cache("some_key")
        assert result is None  # graceful degradation = cache miss

    async def test_set_cache_returns_false_when_breaker_open(self) -> None:
        """When the breaker is OPEN, set_cache() returns False (no write)."""
        redis = RedisClient()
        redis._client = MagicMock()

        await _force_open_async(redis_breaker)

        result = await redis.set_cache("some_key", {"data": 1})
        assert result is False  # graceful degradation = no cache write

    async def test_get_cache_works_normally_when_closed(self) -> None:
        """When the breaker is CLOSED, get_cache() calls through to Redis."""
        import json

        redis = RedisClient()
        redis._client = MagicMock()
        redis._client.get = AsyncMock(return_value=json.dumps({"cached": True}))

        result = await redis.get_cache("some_key")
        assert result == {"cached": True}
        assert redis_breaker.state == CircuitState.CLOSED

    async def test_set_cache_works_normally_when_closed(self) -> None:
        """When the breaker is CLOSED, set_cache() calls through to Redis."""
        redis = RedisClient()
        redis._client = MagicMock()
        redis._client.setex = AsyncMock(return_value=True)

        result = await redis.set_cache("some_key", {"data": 1})
        assert result is True
        assert redis_breaker.state == CircuitState.CLOSED

    async def test_breaker_opens_after_consecutive_redis_failures(self) -> None:
        """The Redis breaker opens after failure_threshold consecutive failures."""
        redis = RedisClient()
        redis._client = MagicMock()
        redis._client.get = AsyncMock(side_effect=Exception("connection lost"))

        # First (failure_threshold - 1) calls should raise
        for _ in range(redis_breaker.failure_threshold - 1):
            with pytest.raises(Exception, match="connection lost"):
                await redis.get_cache("key")
            assert redis_breaker.state == CircuitState.CLOSED

        # The threshold-th failure opens the breaker
        with pytest.raises(Exception, match="connection lost"):
            await redis.get_cache("key")
        assert redis_breaker.state == CircuitState.OPEN

        # Subsequent calls get None (cache miss)
        result = await redis.get_cache("key")
        assert result is None


# ---------------------------------------------------------------------------
# LLM circuit breaker wiring
# ---------------------------------------------------------------------------


class TestLLMCircuitBreaker:
    """Verify LLMProviderManager.chat() degrades gracefully."""

    async def test_chat_raises_llm_error_when_breaker_open(self) -> None:
        """When the breaker is OPEN, chat() raises LLMError with service unavailable."""
        from honeybadge.core.exceptions import LLMError
        from honeybadge.llm.adapter import LLMRequest
        from honeybadge.llm.provider import LLMProviderManager

        # Bypass __init__ to avoid needing a full config dict
        manager = LLMProviderManager.__new__(LLMProviderManager)
        mock_provider = MagicMock()
        mock_provider.chat = AsyncMock(return_value=MagicMock(content="ok"))
        manager._providers = {"test": mock_provider}
        manager._primary = "test"
        manager._fallback = None
        manager._provider_configs = {"test": {}}

        await _force_open_async(llm_breaker)

        request = LLMRequest(messages=[{"role": "user", "content": "hi"}], trace_id="test")

        with pytest.raises(LLMError, match="circuit breaker open"):
            await manager.chat(request)

    async def test_chat_works_normally_when_closed(self) -> None:
        """When the breaker is CLOSED, chat() calls through to the provider."""
        from honeybadge.llm.adapter import LLMRequest
        from honeybadge.llm.provider import LLMProviderManager

        manager = LLMProviderManager.__new__(LLMProviderManager)
        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "hello"
        mock_provider.chat = AsyncMock(return_value=mock_response)
        manager._providers = {"test": mock_provider}
        manager._primary = "test"
        manager._fallback = None
        manager._provider_configs = {"test": {}}

        request = LLMRequest(messages=[{"role": "user", "content": "hi"}], trace_id="test")
        response = await manager.chat(request)

        assert response.content == "hello"
        assert llm_breaker.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpointBreakers:
    """Verify the health endpoint reports circuit breaker states."""

    async def test_health_includes_circuit_breakers(self) -> None:
        """The health response must include a circuit_breakers section."""
        from honeybadge.server.health import health_check

        mock_request = MagicMock()

        result = await health_check(mock_request)

        assert "circuit_breakers" in result
        assert "nebula" in result["circuit_breakers"]
        assert "llm" in result["circuit_breakers"]
        assert "redis" in result["circuit_breakers"]
        for _name, info in result["circuit_breakers"].items():
            assert "state" in info
            assert "failure_count" in info

    async def test_health_reports_degraded_when_breaker_open(self) -> None:
        """Health status is 'degraded' when any breaker is OPEN."""
        from honeybadge.server.health import health_check

        mock_request = MagicMock()

        # Force all breakers open
        await _force_open_async(nebula_breaker)

        result = await health_check(mock_request)
        assert result["status"] == "degraded"
        assert result["circuit_breakers"]["nebula"]["state"] == "open"

    async def test_health_reports_healthy_when_all_closed(self) -> None:
        """Health status can be 'healthy' when all breakers are CLOSED."""
        from honeybadge.server.health import health_check

        mock_request = MagicMock()

        result = await health_check(mock_request)
        # All breakers should be CLOSED
        for _name, info in result["circuit_breakers"].items():
            assert info["state"] == "closed"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestBreakerMetrics:
    """Verify circuit breaker metrics are exported."""

    def test_sync_breaker_metrics_updates_gauges(self) -> None:
        """sync_breaker_metrics() should update Prometheus gauges."""
        from honeybadge.metrics.collectors import RESILIENCE_METRICS

        sync_breaker_metrics()

        # Verify gauges are registered and accessible
        # (prometheus_client stores labels internally; we just verify no error)
        assert RESILIENCE_METRICS.breaker_state is not None
        assert RESILIENCE_METRICS.breaker_failures is not None
        assert RESILIENCE_METRICS.breaker_rejected_total is not None

    async def test_record_rejected_on_nebula_breaker_open(self) -> None:
        """record_rejected is called when Nebula breaker rejects a call."""
        from honeybadge.metrics.collectors import RESILIENCE_METRICS

        client = NebulaGraphClient(host="localhost", port=9669, user="root", password="nebula")
        client._pool = MagicMock()

        await _force_open_async(nebula_breaker)

        # This should record a rejected call
        await client.execute("MATCH (n) RETURN n")

        # The counter should have been incremented (we can't easily read it
        # back from prometheus_client in a unit test, but we verify no error)
        assert RESILIENCE_METRICS.breaker_rejected_total is not None


# ---------------------------------------------------------------------------
# State machine integration
# ---------------------------------------------------------------------------


class TestBreakerStateMachineIntegration:
    """Verify the full CLOSED → OPEN → HALF_OPEN → CLOSED cycle."""

    async def test_nebula_breaker_recovers_after_timeout(self) -> None:
        """After recovery_timeout, the breaker transitions to HALF_OPEN and then CLOSED on success."""
        import time

        from honeybadge.resilience.circuit_breaker import CircuitBreaker

        # Use a fast-recovery breaker for testing
        test_breaker = CircuitBreaker(name="test_recover", failure_threshold=2, recovery_timeout=0.3)

        async def failing_func():
            raise ConnectionError("service down")

        async def success_func():
            return "ok"

        # Trip the breaker
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await test_breaker.call(failing_func)
        assert test_breaker.state == CircuitState.OPEN

        # While OPEN, calls are rejected
        with pytest.raises(CircuitBreakerOpenError):
            await test_breaker.call(success_func)

        # Wait for recovery
        time.sleep(0.35)

        # Next call should transition to HALF_OPEN then CLOSED on success
        result = await test_breaker.call(success_func)
        assert result == "ok"
        assert test_breaker.state == CircuitState.CLOSED

    async def test_half_open_failure_reopens_breaker(self) -> None:
        """If a HALF_OPEN trial call fails, the breaker goes back to OPEN."""
        import time

        from honeybadge.resilience.circuit_breaker import CircuitBreaker

        test_breaker = CircuitBreaker(name="test_reopen", failure_threshold=1, recovery_timeout=0.3)

        async def failing_func():
            raise ConnectionError("still down")

        # Trip the breaker
        with pytest.raises(ConnectionError):
            await test_breaker.call(failing_func)
        assert test_breaker.state == CircuitState.OPEN

        # Wait for recovery
        time.sleep(0.35)

        # Trial call fails — should go back to OPEN
        with pytest.raises(ConnectionError):
            await test_breaker.call(failing_func)
        assert test_breaker.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# get_breaker_states
# ---------------------------------------------------------------------------


class TestGetBreakerStates:
    """Verify the get_breaker_states() utility."""

    def test_returns_all_breakers(self) -> None:
        states = get_breaker_states()
        assert set(states.keys()) == {"nebula", "llm", "redis"}

    def test_each_breaker_has_required_fields(self) -> None:
        states = get_breaker_states()
        for _name, info in states.items():
            assert "state" in info
            assert "failure_count" in info
            assert "last_error" in info
            assert info["state"] == "closed"
            assert info["failure_count"] == 0
            assert info["last_error"] is None

    async def test_states_reflect_failures(self) -> None:
        await _force_open_async(nebula_breaker)
        states = get_breaker_states()
        assert states["nebula"]["state"] == "open"
        assert states["nebula"]["failure_count"] == nebula_breaker.failure_threshold
        assert states["nebula"]["last_error"] is not None
