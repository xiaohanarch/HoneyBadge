"""HoneyBadge Cache MCP Server.

Query result caching via Redis. Uses FastMCP and the existing RedisClient.
"""

import os
import sys
from typing import Any, Optional

# Add src/ to path so we can import honeybadge modules
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_project_root, "src"))

import structlog
from fastmcp import FastMCP

from honeybadge.db.redis import RedisClient

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# FastMCP app
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "honeybadge-cache-mcp",
    instructions="Cache MCP Server for HoneyBadge — query result caching via Redis. "
    "Provides cache check and cache store operations for query results.",
)

# ---------------------------------------------------------------------------
# Lazy singleton (initialized from env vars on first use)
# ---------------------------------------------------------------------------

_redis_client: Optional[RedisClient] = None


async def _get_redis() -> RedisClient:
    """Return a connected RedisClient singleton, initialized from env vars."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD", None),
        )
        await _redis_client.connect()
        logger.info("redis_client_initialized")
    return _redis_client


# ---------------------------------------------------------------------------
# Implementation functions (accept explicit dependencies for testability)
# ---------------------------------------------------------------------------


def _tenant_key(key: str, org_id: int | None) -> str:
    """Prefix a cache key with the tenant namespace when org_id is provided.

    Without org_id, the key is returned as-is (backward compatible with
    existing callers that don't pass org_id). When org_id is provided, the
    key becomes ``org:{org_id}:{key}`` so one tenant cannot read another's
    cached query results even if they guess the key.
    """
    if org_id is None:
        return key
    return f"org:{org_id}:{key}"


async def check_cache_impl(
    redis: RedisClient, key: str, org_id: int | None = None
) -> dict:
    """Check if a cached result exists for the given key.

    When ``org_id`` is provided, the key is namespaced under ``org:{org_id}:``
    to enforce tenant isolation.
    """
    namespaced = _tenant_key(key, org_id)
    data = await redis.get_cache(namespaced)
    if data is not None:
        return {"hit": True, "data": data}
    return {"hit": False, "data": None}


async def cache_result_impl(
    redis: RedisClient,
    key: str,
    value: Any,
    ttl: int = 300,
    org_id: int | None = None,
) -> dict:
    """Cache a query result under the given key with the specified TTL.

    When ``org_id`` is provided, the key is namespaced under ``org:{org_id}:``
    to enforce tenant isolation.
    """
    namespaced = _tenant_key(key, org_id)
    await redis.set_cache(namespaced, value, ttl)
    return {"success": True, "key": namespaced, "ttl": ttl}


# ---------------------------------------------------------------------------
# MCP Tool wrappers (use lazy singleton)
# ---------------------------------------------------------------------------


@mcp.tool()
async def check_cache(key: str, org_id: int | None = None) -> dict:
    """Check if a cached result exists for the given key.

    Returns a hit/miss response. On a cache hit the cached data is included.

    Args:
        key: Cache key to look up.
        org_id: Optional tenant org_id. When provided, the key is namespaced
            under ``org:{org_id}:`` to enforce tenant isolation.
    """
    redis = await _get_redis()
    return await check_cache_impl(redis, key=key, org_id=org_id)


@mcp.tool()
async def cache_result(
    key: str, value: Any, ttl: int = 300, org_id: int | None = None
) -> dict:
    """Cache a query result under the given key.

    Stores the value in Redis with the specified TTL in seconds.

    Args:
        key: Cache key to store the result under.
        value: The value to cache (must be JSON-serializable).
        ttl: Time-to-live in seconds (default: 300).
        org_id: Optional tenant org_id. When provided, the key is namespaced
            under ``org:{org_id}:`` to enforce tenant isolation.
    """
    redis = await _get_redis()
    return await cache_result_impl(redis, key=key, value=value, ttl=ttl, org_id=org_id)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
