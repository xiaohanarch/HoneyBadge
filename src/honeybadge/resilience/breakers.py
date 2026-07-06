"""Named circuit breakers for external service calls.

Each external dependency (NebulaGraph, LLM API, Redis) has a dedicated
CircuitBreaker instance. Wire these into client methods to fail fast
when a downstream service is unhealthy.

Usage::

    from honeybadge.resilience.breakers import nebula_breaker

    async with nebula_breaker:
        result = await nebula.execute(ngql)

When the breaker is OPEN, ``CircuitBreakerOpenError`` is raised immediately.
Callers should catch it and return a graceful degradation response.

Breaker state is exported to Prometheus via ``RESILIENCE_METRICS``. Call
``sync_breaker_metrics()`` after any breaker operation to refresh gauges,
or call it from a periodic health check.
"""
from __future__ import annotations

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState

# =============================================================================
# Named circuit breakers
# =============================================================================
# Tuning rationale:
#   - nebula: 5 failures / 30s recovery — graph DB is critical, moderate cooldown
#   - llm:    3 failures / 60s recovery — LLM APIs are flaky, longer cooldown
#   - redis:  5 failures / 15s recovery — cache is non-critical, fast retry

nebula_breaker = CircuitBreaker(
    name="nebula",
    failure_threshold=5,
    recovery_timeout=30.0,
)

llm_breaker = CircuitBreaker(
    name="llm",
    failure_threshold=3,
    recovery_timeout=60.0,
)

redis_breaker = CircuitBreaker(
    name="redis",
    failure_threshold=5,
    recovery_timeout=15.0,
)

# Registry for iteration (health checks, metrics sync)
BREAKERS: dict[str, CircuitBreaker] = {
    "nebula": nebula_breaker,
    "llm": llm_breaker,
    "redis": redis_breaker,
}


def sync_breaker_metrics() -> None:
    """Push current breaker states into Prometheus metrics.

    Call this after breaker operations or from a periodic health check
    to keep the ``honeybadge_circuit_breaker_*`` gauges up to date.
    """
    from honeybadge.metrics.collectors import RESILIENCE_METRICS

    for name, breaker in BREAKERS.items():
        RESILIENCE_METRICS.update_breaker(
            name=name,
            state=breaker.state.value,
            failure_count=breaker.failure_count,
        )


def get_breaker_states() -> dict[str, dict[str, object]]:
    """Return a snapshot of all breaker states for health checks.

    Returns:
        Dict mapping breaker name to ``{state, failure_count, last_error}``.
    """
    return {
        name: {
            "state": breaker.state.value,
            "failure_count": breaker.failure_count,
            "last_error": breaker.last_error,
        }
        for name, breaker in BREAKERS.items()
    }


__all__ = [
    "BREAKERS",
    "CircuitBreakerOpenError",
    "CircuitState",
    "get_breaker_states",
    "llm_breaker",
    "nebula_breaker",
    "redis_breaker",
    "sync_breaker_metrics",
]
