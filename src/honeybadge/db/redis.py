"""Redis client for HoneyBadge session and cache management."""

import json
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
import structlog

from honeybadge.core.exceptions import RedisError

logger = structlog.get_logger()


class RedisClient:
    """
    Async client for Redis operations.

    Handles session state and query result caching.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        session_prefix: str = "session",
        cache_prefix: str = "cache",
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.session_prefix = session_prefix
        self.cache_prefix = cache_prefix
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis."""
        try:
            self._client = aioredis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True,
            )
            await self._client.ping()
            logger.info("redis_connected", host=self.host, port=self.port, db=self.db)
        except Exception as e:
            raise RedisError(f"Failed to connect to Redis: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("redis_disconnected")

    @property
    def client(self) -> aioredis.Redis:
        """Get the raw Redis client for direct operations (e.g., token metering)."""
        if not self._client:
            raise RedisError("Not connected to Redis")
        return self._client

    # =========================================================================
    # Session Operations
    # =========================================================================

    async def get_session(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        """Get session data."""
        if not self._client:
            raise RedisError("Not connected to Redis")

        key = f"{self.session_prefix}:{user_id}:{session_id}"
        data = await self._client.hgetall(key)
        if not data:
            return None
        # decode_responses=True ensures str keys/values, but the redis-py
        # type stubs still report bytes|str. Cast to the runtime type.
        return self._deserialize_session(dict(data))  # type: ignore[arg-type]

    async def set_session(
        self,
        user_id: str,
        session_id: str,
        data: dict[str, Any],
        ttl: int = 1800,
    ) -> bool:
        """Set session data."""
        if not self._client:
            raise RedisError("Not connected to Redis")

        key = f"{self.session_prefix}:{user_id}:{session_id}"
        serialized = self._serialize_session(data)
        await self._client.hset(key, mapping=serialized)  # type: ignore[arg-type]
        await self._client.expire(key, ttl)
        return True

    async def delete_session(self, user_id: str, session_id: str) -> bool:
        """Delete session."""
        if not self._client:
            raise RedisError("Not connected to Redis")

        key = f"{self.session_prefix}:{user_id}:{session_id}"
        result = await self._client.delete(key)
        return result > 0

    # =========================================================================
    # Cache Operations
    # =========================================================================

    async def get_cache(self, key: str) -> Any | None:
        """Get cached value."""
        if not self._client:
            raise RedisError("Not connected to Redis")

        full_key = f"{self.cache_prefix}:{key}"
        data = await self._client.get(full_key)
        if data:
            return json.loads(data)
        return None

    async def set_cache(
        self,
        key: str,
        value: Any,
        ttl: int = 300,
    ) -> bool:
        """Set cached value."""
        if not self._client:
            raise RedisError("Not connected to Redis")

        full_key = f"{self.cache_prefix}:{key}"
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        await self._client.setex(full_key, ttl, serialized)
        return True

    async def invalidate_cache(self, pattern: str) -> int:
        """Invalidate cache keys matching pattern."""
        if not self._client:
            raise RedisError("Not connected to Redis")

        full_pattern = f"{self.cache_prefix}:{pattern}"
        count = 0
        async for key in self._client.scan_iter(match=full_pattern, count=100):
            await self._client.delete(key)
            count += 1
        return count

    # =========================================================================
    # Serialization Helpers
    # =========================================================================

    def _serialize_session(self, data: dict[str, Any]) -> dict[str, str]:
        """Serialize session data for Redis hash."""
        result = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, (list, dict)):
                result[key] = json.dumps(value, ensure_ascii=False, default=str)
            else:
                result[key] = str(value) if value is not None else ""
        return result

    def _deserialize_session(self, data: dict[str, str]) -> dict[str, Any]:
        """Deserialize session data from Redis hash."""
        result: dict[str, Any] = {}
        for key, value in data.items():
            if key in ("created_at", "last_active"):
                try:
                    result[key] = datetime.fromisoformat(value)
                except (ValueError, TypeError):
                    result[key] = value
            else:
                # Try to parse JSON values
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, (list, dict)):
                        result[key] = parsed
                    else:
                        result[key] = value
                except (json.JSONDecodeError, TypeError):
                    result[key] = value
        return result
