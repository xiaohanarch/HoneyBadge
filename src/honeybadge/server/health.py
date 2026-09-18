"""Health check router."""

import asyncio
import time
from typing import Any

import structlog
from fastapi import APIRouter, Request

from honeybadge.core.constants import VERSION
from honeybadge.resilience.breakers import get_breaker_states, sync_breaker_metrics

router = APIRouter(prefix="/api", tags=["system"])

logger = structlog.get_logger()

# Lazy Nebula reconnect (guards against the startup race where graphd was not
# ready yet): retry at most once per cooldown window so Prometheus scrapes
# cannot hammer a down graphd, and cap each attempt so health stays responsive.
NEBULA_RECONNECT_COOLDOWN_S = 30.0
NEBULA_RECONNECT_TIMEOUT_S = 15.0


# NOTE: /api/health is intentionally exempt from the unified response envelope.
# Monitoring tools (Prometheus, k8s liveness probes, etc.) expect the raw
# {"status", "version", "services"} shape and would break if it were wrapped
# in {success, data, ...}. Do not wrap health responses.


async def _ensure_nebula(app: Any) -> Any:
    """Return a connected Nebula client, lazily reconnecting after startup races.

    Lifespan connects exactly once; if graphd was not up yet, ``app.state.nebula``
    stays None forever and health would report "down" until a manual container
    restart (observed as E2E tc601). Retry from the health path instead, at
    most once per cooldown window.
    """
    nebula = getattr(app.state, "nebula", None)
    if nebula is not None and getattr(nebula, "_pool", None) is not None:
        return nebula

    now = time.monotonic()
    if now < getattr(app.state, "nebula_next_reconnect", 0.0):
        return nebula

    app.state.nebula_next_reconnect = now + NEBULA_RECONNECT_COOLDOWN_S
    config = getattr(app.state, "config", None)
    if config is None:
        return nebula

    from honeybadge.db.nebula import NebulaGraphClient

    try:
        client = NebulaGraphClient(
            host=config.nebula_host, port=config.nebula_port,
            user=config.nebula_user, password=config.nebula_password,
        )
        await asyncio.wait_for(client.connect(), timeout=NEBULA_RECONNECT_TIMEOUT_S)
        app.state.nebula = client
        logger.info(
            "nebula_health_reconnect_ok",
            host=config.nebula_host, port=config.nebula_port,
        )
        return client
    except Exception as e:
        logger.warning("nebula_health_reconnect_failed", error=str(e))
        return nebula


@router.get("/health")
async def health_check(request: Request) -> dict[str, Any]:
    services: dict[str, Any] = {}

    # Check Redis
    try:
        redis = request.app.state.redis
        if redis and hasattr(redis, '_client') and redis._client:
            await redis._client.ping()
            services["redis"] = {"status": "up"}
        else:
            services["redis"] = {"status": "down", "error": "not connected"}
    except Exception as e:
        services["redis"] = {"status": "down", "error": str(e)}

    # Check PostgreSQL
    try:
        pg = request.app.state.pg
        if pg and hasattr(pg, '_pool') and pg._pool:
            async with pg._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            services["postgres"] = {"status": "up"}
        else:
            services["postgres"] = {"status": "down", "error": "not connected"}
    except Exception as e:
        services["postgres"] = {"status": "down", "error": str(e)}

    # Check NebulaGraph (with lazy reconnect for the startup race)
    try:
        nebula = await _ensure_nebula(request.app)
        if nebula and hasattr(nebula, '_pool') and nebula._pool:
            services["nebula"] = {"status": "up"}
        else:
            services["nebula"] = {"status": "down", "error": "not connected"}
    except Exception as e:
        services["nebula"] = {"status": "down", "error": str(e)}

    # Sync and report circuit breaker states
    sync_breaker_metrics()
    breaker_states = get_breaker_states()
    circuit_breakers: dict[str, Any] = {}
    any_breaker_open = False
    for name, info in breaker_states.items():
        state = info["state"]
        if state == "open":
            any_breaker_open = True
        circuit_breakers[name] = {
            "state": state,
            "failure_count": info["failure_count"],
            "last_error": info["last_error"],
        }

    all_up = all(s.get("status") == "up" for s in services.values())
    overall = "healthy" if (all_up and not any_breaker_open) else "degraded"

    return {
        "status": overall,
        "version": VERSION,
        "services": services,
        "circuit_breakers": circuit_breakers,
    }
