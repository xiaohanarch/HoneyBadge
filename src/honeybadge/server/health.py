"""Health check router."""

from typing import Any

from fastapi import APIRouter, Request

from honeybadge.core.constants import VERSION
from honeybadge.resilience.breakers import get_breaker_states, sync_breaker_metrics

router = APIRouter(prefix="/api", tags=["system"])


# NOTE: /api/health is intentionally exempt from the unified response envelope.
# Monitoring tools (Prometheus, k8s liveness probes, etc.) expect the raw
# {"status", "version", "services"} shape and would break if it were wrapped
# in {success, data, ...}. Do not wrap health responses.


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

    # Check NebulaGraph
    try:
        nebula = request.app.state.nebula
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
