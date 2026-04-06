"""Tests for honeybadge-cache-mcp server."""

import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

# Add MCP server and src to path for imports
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "mcp-servers", "honeybadge-cache-mcp"),
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Mock redis if not available (e.g. Python 3.14 where redis may not be installed)
if "redis" not in sys.modules:
    _redis_mock = types.ModuleType("redis")
    _redis_asyncio_mock = types.ModuleType("redis.asyncio")
    _redis_asyncio_mock.Redis = MagicMock()  # type: ignore[attr-defined]
    _redis_mock.asyncio = _redis_asyncio_mock  # type: ignore[attr-defined]
    sys.modules["redis"] = _redis_mock
    sys.modules["redis.asyncio"] = _redis_asyncio_mock

import pytest

from server import check_cache_impl, cache_result_impl


@pytest.fixture
def mock_redis_client():
    client = AsyncMock()
    client.get_cache = AsyncMock(return_value=None)
    client.set_cache = AsyncMock(return_value=True)
    return client


@pytest.mark.asyncio
async def test_check_cache_miss(mock_redis_client):
    """Test that check_cache_impl returns hit=False when get_cache returns None."""
    result = await check_cache_impl(mock_redis_client, key="query:abc123")

    assert result["hit"] is False
    assert result["data"] is None
    mock_redis_client.get_cache.assert_called_once_with("query:abc123")


@pytest.mark.asyncio
async def test_cache_result_and_hit(mock_redis_client):
    """Test cache_result_impl stores value, then check_cache_impl returns hit=True."""
    cached_data = {"rows": [{"supplier": "SupplierA", "amount": 1000000}], "count": 1}

    # Cache the result
    store_result = await cache_result_impl(
        mock_redis_client,
        key="query:xyz789",
        value=cached_data,
        ttl=600,
    )

    assert store_result["success"] is True
    assert store_result["key"] == "query:xyz789"
    assert store_result["ttl"] == 600
    mock_redis_client.set_cache.assert_called_once_with("query:xyz789", cached_data, 600)

    # Now simulate a cache hit by making get_cache return the data
    mock_redis_client.get_cache = AsyncMock(return_value=cached_data)

    hit_result = await check_cache_impl(mock_redis_client, key="query:xyz789")

    assert hit_result["hit"] is True
    assert hit_result["data"] == cached_data
    mock_redis_client.get_cache.assert_called_once_with("query:xyz789")
