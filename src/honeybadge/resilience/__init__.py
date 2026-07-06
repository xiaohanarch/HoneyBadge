"""Resilience engineering primitives for HoneyBadge.

Provides circuit breaker and graceful degradation patterns to prevent
cascading failures when downstream services (LLM API, NebulaGraph,
PostgreSQL, Redis) become unhealthy.

Wiring:
    The circuit breaker is a reusable decorator/context manager. Apply it
    to any async call that hits an external service::

        from honeybadge.resilience import CircuitBreaker, CircuitBreakerOpenError

        llm_cb = CircuitBreaker(name="llm", failure_threshold=5, recovery_timeout=30)

        @llm_cb
        async def call_llm(prompt: str) -> str:
            ...

    When the breaker is OPEN, calls fail immediately with
    ``CircuitBreakerOpenError`` instead of waiting for a timeout — this
    frees up worker capacity and prevents request pile-up.
"""

from honeybadge.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitState",
]
