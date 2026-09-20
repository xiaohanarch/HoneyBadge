"""FastAPI application factory for HoneyBadge backend server."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from honeybadge.core.constants import VERSION
from honeybadge.server.auth import (
    DEMO_USERS,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    user_to_response,
)
from honeybadge.server.config import ServerConfig
from honeybadge.server.dependencies import get_current_user
from honeybadge.server.envelope import success
from honeybadge.server.exception_handlers import register_exception_handlers
from honeybadge.server.middleware import TraceIdMiddleware, get_trace_id
from honeybadge.server.security import (
    LOGIN_LIMIT,
    TokenRevocationStore,
    configure_rate_limiter,
    extract_jti,
)
from honeybadge.server.tickets import TicketStore

logger = structlog.get_logger()


def create_app(config: ServerConfig | None = None) -> FastAPI:
    if config is None:
        config = ServerConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("server_starting", port=config.port)
        # Initialize all to None so error handling can distinguish
        # "initialized but failed later" from "never reached"
        app.state.nebula = None
        app.state.pg = None
        app.state.redis = None
        app.state.llm = None
        from honeybadge.db.nebula import NebulaGraphClient
        from honeybadge.db.postgres import PostgreSQLClient
        from honeybadge.db.redis import RedisClient
        from honeybadge.llm.adapter import OpenAICompatibleAdapter

        ready = []

        try:
            nebula = NebulaGraphClient(
                host=config.nebula_host, port=config.nebula_port,
                user=config.nebula_user, password=config.nebula_password,
            )
            await nebula.connect()
            app.state.nebula = nebula
            ready.append("nebula")
        except Exception as e:
            logger.error("nebula_init_failed", error=str(e))

        try:
            pg = PostgreSQLClient(
                host=config.pg_host, port=config.pg_port,
                user=config.pg_user, password=config.pg_password,
                database=config.pg_database,
            )
            await pg.connect()
            await pg.init_schema()
            app.state.pg = pg
            ready.append("pg")
        except Exception as e:
            logger.error("pg_init_failed", error=str(e))

        try:
            redis = RedisClient(
                host=config.redis_host, port=config.redis_port,
                password=config.redis_password,
            )
            await redis.connect()
            app.state.redis = redis
            app.state.token_revocation = TokenRevocationStore(redis._client if hasattr(redis, "_client") else None)
            ready.append("redis")
        except Exception as e:
            logger.error("redis_init_failed", error=str(e))
            app.state.token_revocation = TokenRevocationStore(None)

        try:
            llm_config = {
                "endpoint": config.llm_endpoint,
                "api_key": config.llm_api_key,
                "model": config.llm_model,
                "timeout": 300,
            }
            app.state.llm = OpenAICompatibleAdapter(llm_config, None)
            ready.append("llm")
        except Exception as e:
            logger.error("llm_init_failed", error=str(e))

        logger.info("server_ready", services=",".join(ready))

        yield

        logger.info("server_shutting_down")
        if hasattr(app.state, "nebula") and app.state.nebula:
            await app.state.nebula.disconnect()
        if hasattr(app.state, "pg") and app.state.pg:
            await app.state.pg.disconnect()
        if hasattr(app.state, "redis") and app.state.redis:
            await app.state.redis.disconnect()

    app = FastAPI(title="HoneyBadge", version=VERSION, lifespan=lifespan)
    app.state.config = config
    app.state.ticket_store = TicketStore()

    # --- Rate limiter (slowapi) ---
    limiter = configure_rate_limiter(app)

    # TraceIdMiddleware is added BEFORE CORSMiddleware so CORS stays the
    # outermost layer and handles preflight without trace-id headers leaking
    # into browser-side CORS errors.
    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*", "X-Trace-Id"],
    )

    # --- Global exception handlers (unified envelope) ---
    register_exception_handlers(app)

    # --- Prometheus /metrics endpoint ---
    # Exposes all honeybadge_* metrics collected by collectors.py. Scraped by
    # Prometheus on the :8090 port. Mounted before auth routes so it needs no
    # authentication (Prometheus scrapers use network-level ACLs, not JWTs).
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())

    # --- Auth routes (inline) ---

    class LoginRequest(BaseModel):
        username: str
        password: str

    class RefreshRequest(BaseModel):
        refresh_token: str

    @app.post("/api/auth/login")
    @limiter.limit(LOGIN_LIMIT)
    async def login(body: LoginRequest, request: Request) -> dict[str, Any]:
        user = authenticate_user(body.username, body.password)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        token_data = {"sub": user["id"], "username": user["username"], "roles": user["roles"], "org_id": user["org_id"]}
        access_token = create_access_token(token_data, config.jwt_secret, config.jwt_access_expire_minutes)
        refresh_token = create_refresh_token({"sub": user["id"]}, config.jwt_secret, config.jwt_refresh_expire_days)
        return success({"token": access_token, "refresh_token": refresh_token, "user": user_to_response(user)}, trace_id=get_trace_id())

    @app.get("/api/auth/me")
    async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        return success({"id": user["sub"], "username": user["username"], "display_name": user.get("display_name", user["username"]), "roles": user["roles"], "org_id": user.get("org_id")}, trace_id=get_trace_id())

    @app.post("/api/auth/logout")
    async def logout(
        request: Request,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Revoke the current access token via Redis blacklist.

        The token's JTI is added to a blacklist with TTL equal to the
        token's remaining lifetime, so it expires naturally. Subsequent
        requests carrying the same token are rejected in
        ``get_current_user``.
        """
        revocation: TokenRevocationStore | None = getattr(request.app.state, "token_revocation", None)
        if revocation is not None:
            jti = extract_jti(user)
            exp = user.get("exp")
            now = int(datetime.now(tz=timezone.utc).timestamp())
            ttl = max(0, int(exp) - now) if exp else config.jwt_access_expire_minutes * 60
            await revocation.revoke(jti, ttl)
        return success({"message": "Logged out"}, trace_id=get_trace_id())

    @app.post("/api/auth/refresh")
    async def refresh(body: RefreshRequest) -> dict[str, Any]:
        payload = decode_token(body.refresh_token, config.jwt_secret)
        if payload is None or payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
        user = None
        for u in DEMO_USERS.values():
            if u["id"] == payload["sub"]:
                user = u
                break
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        token_data = {"sub": user["id"], "username": user["username"], "roles": user["roles"], "org_id": user["org_id"]}
        access_token = create_access_token(token_data, config.jwt_secret, config.jwt_access_expire_minutes)
        new_refresh = create_refresh_token({"sub": user["id"]}, config.jwt_secret, config.jwt_refresh_expire_days)
        return success({"token": access_token, "refresh_token": new_refresh, "user": user_to_response(user)}, trace_id=get_trace_id())

    # --- Mount routers ---
    from honeybadge.server.admin import router as admin_router
    from honeybadge.server.audit import router as audit_router
    from honeybadge.server.health import router as health_router
    from honeybadge.server.sessions import router as sessions_router
    from honeybadge.server.tickets import router as tickets_router

    app.include_router(health_router)
    app.include_router(sessions_router)
    app.include_router(audit_router)
    app.include_router(admin_router)
    app.include_router(tickets_router)

    return app


def main() -> None:
    config = ServerConfig.from_env()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
