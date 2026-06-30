"""Health check router."""

from typing import Any

from fastapi import APIRouter, Request

from honeybadge.core.constants import VERSION

router = APIRouter(prefix="/api", tags=["system"])


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

    all_up = all(s.get("status") == "up" for s in services.values())
    return {
        "status": "healthy" if all_up else "degraded",
        "version": VERSION,
        "services": services,
    }
