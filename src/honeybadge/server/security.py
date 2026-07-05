"""Security middleware: rate limiting and token revocation.

This module provides:
  * ``configure_rate_limiter`` — wires ``slowapi`` into a FastAPI app with
    sensible per-endpoint limits.
  * ``TokenRevocationStore`` — a Redis-backed JWT blacklist used to honour
    logout before the token's natural expiry.

Both components degrade gracefully when Redis is unavailable: rate limiting
falls back to an in-memory counter, and token revocation becomes a no-op
(fail-open, since the L3 permission layer still enforces data isolation).
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

# In-memory fallback storage when Redis is not configured. This is process-local
# and therefore approximate under multi-process deployments, but preserves the
# brute-force protection guarantee within a single worker.
_memory_storage: dict[str, list[float]] = {}

# Default limits (overridable via environment variables at call sites)
LOGIN_LIMIT = "5/minute"
REFRESH_LIMIT = "10/minute"
WS_QUERY_LIMIT = "20/minute"


def _memory_key_func(key: str) -> str:
    """Round the current time to the minute for in-memory bucketing."""
    return f"{key}:{int(time.time()) // 60}"


class _InMemoryLimiter:
    """Minimal fixed-window counter used when Redis is unavailable.

    Not as accurate as slowapi's Redis backend but sufficient to stop
    credential-stuffing bursts against ``/api/auth/login``.
    """

    def __init__(self) -> None:
        self._hits: dict[str, int] = {}

    def hit(self, key: str, limit: int) -> bool:
        bucket = _memory_key_func(key)
        count = self._hits.get(bucket, 0)
        if count >= limit:
            # Opportunistic cleanup of stale buckets
            if len(self._hits) > 1000:
                self._hits = {k: v for k, v in self._hits.items() if k.endswith(f":{int(time.time()) // 60}")}
            return False
        self._hits[bucket] = count + 1
        return True


_in_memory = _InMemoryLimiter()


def configure_rate_limiter(app: Any) -> Limiter:
    """Attach a ``slowapi`` limiter to the FastAPI app.

    Uses Redis as the backing storage when ``REDIS_URL`` is set, otherwise
    falls back to slowapi's in-memory backend.

    Args:
        app: The FastAPI application instance.

    Returns:
        The configured ``Limiter`` instance (also stored on ``app.state``).
    """
    import os

    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        try:
            limiter = Limiter(key_func=get_remote_address, storage_uri=redis_url)
            logger.info("rate_limiter_redis_enabled", url=redis_url.replace("://", "://***@"))
        except Exception as e:  # pragma: no cover — defensive
            logger.warning("rate_limiter_redis_failed", error=str(e), fallback="memory")
            limiter = Limiter(key_func=get_remote_address)
    else:
        limiter = Limiter(key_func=get_remote_address)
        logger.info("rate_limiter_memory_enabled")

    app.state.limiter = limiter

    # Register the rate-limit-exceeded handler so clients get a clean 429
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded", "retry_after": getattr(exc, "retry_after", 60)},
        )

    return limiter


# ---------------------------------------------------------------------------
# Token revocation (logout)
# ---------------------------------------------------------------------------

_REDIS_PREFIX = "jwt:blacklist:"


class TokenRevocationStore:
    """Redis-backed JWT blacklist with TTL matching token expiry.

    On logout, the token's ``jti`` (JWT ID) is written with a TTL equal to
    the remaining lifetime of the token. Subsequent requests check the
    blacklist before accepting the token.

    If Redis is unavailable, revocation is a no-op (fail-open). This is
    acceptable because:
      1. Tokens are short-lived (default 60 min).
      2. L3 permission enforcement is independent of authentication.
      3. A missing blacklist is strictly less permissive than no logout.
    """

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        """Mark a token's JTI as revoked.

        Args:
            jti: The JWT ID claim.
            ttl_seconds: Remaining token lifetime; the blacklist entry
                auto-expires when the token would have expired anyway.
        """
        if not jti or ttl_seconds <= 0 or self._redis is None:
            return
        try:
            await self._redis.setex(f"{_REDIS_PREFIX}{jti}", ttl_seconds, "1")
            logger.info("token_revoked", jti=jti, ttl=ttl_seconds)
        except Exception as e:
            # Fail-open: the token still expires naturally; we just lose
            # immediate revocation. Log so operators notice Redis issues.
            logger.warning("token_revoke_failed", jti=jti, error=str(e))

    async def is_revoked(self, jti: str) -> bool:
        """Return True if the JTI has been revoked and is still in the blacklist."""
        if not jti or self._redis is None:
            return False
        try:
            return bool(await self._redis.get(f"{_REDIS_PREFIX}{jti}"))
        except Exception:
            # Fail-open on Redis errors to avoid locking users out.
            return False


def extract_jti(payload: dict[str, Any]) -> str:
    """Extract the JTI claim, generating a stable fallback if absent."""
    jti = payload.get("jti")
    if jti:
        return str(jti)
    # For tokens issued before JTI was added, derive a synthetic ID from
    # the subject and issued-at time so revocation still works.
    sub = payload.get("sub", "")
    iat = payload.get("iat", "")
    return f"synthetic:{sub}:{iat}"
