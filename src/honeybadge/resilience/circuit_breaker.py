"""Async circuit breaker for external service calls.

Prevents cascading failures by failing fast when a downstream service is
unhealthy. When the breaker is OPEN, calls raise ``CircuitBreakerOpenError``
immediately — no network wait, no timeout, no pile-up.

State machine::

    CLOSED  --[failure_threshold reached]-->  OPEN
    OPEN    --[recovery_timeout elapsed]---->  HALF_OPEN
    HALF_OPEN --[success]-->  CLOSED
    HALF_OPEN --[failure]-->  OPEN (cooldown restarts)

Usage as a decorator::

    cb = CircuitBreaker(name="llm", failure_threshold=5, recovery_timeout=30)

    @cb
    async def call_llm(prompt: str) -> str:
        ...

Usage as a context manager::

    async with cb:
        result = await llm_client.generate(prompt)

The breaker is safe for concurrent use (protected by ``asyncio.Lock``).
Each breaker records its state, failure count, and last error for
observability — wire these into metrics collectors.
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when a call is attempted while the breaker is OPEN.

    The caller should catch this and return a graceful degradation response
    rather than retrying — the breaker will transition to HALF_OPEN after
    the recovery timeout.
    """

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{name}' is OPEN. Retry after {retry_after:.1f}s."
        )


class CircuitBreaker:
    """Async circuit breaker with CLOSED/OPEN/HALF_OPEN state machine.

    Args:
        name: Human-readable identifier for logging and metrics.
        failure_threshold: Consecutive failures before opening (default 5).
        recovery_timeout: Seconds in OPEN before transitioning to HALF_OPEN (default 30).
        half_open_max_calls: Max concurrent trial calls in HALF_OPEN (default 1).
        expected_exception: Exception type that counts as a failure.
            Other exceptions are re-raised without affecting the breaker state.
            Defaults to ``Exception`` (any error counts).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        expected_exception: type[Exception] = Exception,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.expected_exception = expected_exception

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        self._last_error: str | None = None

    @property
    def state(self) -> CircuitState:
        """Current breaker state (read-only)."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        return self._failure_count

    @property
    def last_error(self) -> str | None:
        """Last error message that triggered a failure, if any."""
        return self._last_error

    def _should_transition_to_half_open(self) -> bool:
        """Check if enough time has passed to try HALF_OPEN."""
        return (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._last_failure_time >= self.recovery_timeout
        )

    async def _before_call(self) -> None:
        """Check and update state before allowing a call through."""
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_transition_to_half_open():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info(
                        "circuit_breaker_half_open",
                        name=self.name,
                        recovery_timeout=self.recovery_timeout,
                    )
                else:
                    retry_after = self.recovery_timeout - (
                        time.monotonic() - self._last_failure_time
                    )
                    raise CircuitBreakerOpenError(self.name, max(retry_after, 0))

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        self.name, self.recovery_timeout
                    )
                self._half_open_calls += 1

    async def _on_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("circuit_breaker_recovered", name=self.name)
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0
            self._last_error = None

    async def _on_failure(self, exc: Exception) -> None:
        """Record a failed call."""
        async with self._lock:
            self._last_failure_time = time.monotonic()
            self._last_error = str(exc)
            self._failure_count += 1

            if self._state == CircuitState.HALF_OPEN:
                # Trial call failed — go back to OPEN
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_reopened",
                    name=self.name,
                    error=str(exc),
                )
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_opened",
                    name=self.name,
                    failure_count=self._failure_count,
                    threshold=self.failure_threshold,
                    error=str(exc),
                )

    async def call(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """Execute ``func`` through the circuit breaker.

        Raises:
            CircuitBreakerOpenError: If the breaker is OPEN.
            Any exception raised by ``func`` (re-raised after recording).
        """
        await self._before_call()
        try:
            result = await func(*args, **kwargs)
        except self.expected_exception as exc:
            await self._on_failure(exc)
            raise
        except Exception:
            # Unexpected exceptions don't count as failures — re-raise as-is.
            # This prevents the breaker from opening on programmer errors
            # (e.g., TypeError, ValueError) that aren't service health signals.
            raise
        await self._on_success()
        return result

    def __call__(self, func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        """Decorator: wrap an async function with the circuit breaker."""

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await self.call(func, *args, **kwargs)

        return wrapper

    async def __aenter__(self) -> CircuitBreaker:
        await self._before_call()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if exc_type is None:
            await self._on_success()
        elif issubclass(exc_type, self.expected_exception):
            await self._on_failure(exc_val)
            # Don't suppress — let the exception propagate
        # Unexpected exceptions: don't count as failure, let them propagate
        return False

    def reset(self) -> None:
        """Force-reset the breaker to CLOSED (for testing/manual recovery)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        self._last_error = None
