"""FastAPI application factory for HoneyBadge backend server."""

from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from honeybadge.core.constants import VERSION
from honeybadge.server.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    user_to_response,
    DEMO_USERS,
)
from honeybadge.server.config import ServerConfig
from honeybadge.server.dependencies import get_current_user

logger = structlog.get_logger()


def create_app(config: ServerConfig | None = None) -> FastAPI:
    if config is None:
        config = ServerConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("server_starting", port=config.port)
        try:
            from honeybadge.db.nebula import NebulaGraphClient
            from honeybadge.db.postgres import PostgreSQLClient
            from honeybadge.db.redis import RedisClient

            nebula = NebulaGraphClient(
                host=config.nebula_host, port=config.nebula_port,
                user=config.nebula_user, password=config.nebula_password,
            )
            await nebula.connect()
            app.state.nebula = nebula

            pg = PostgreSQLClient(
                host=config.pg_host, port=config.pg_port,
                user=config.pg_user, password=config.pg_password,
                database=config.pg_database,
            )
            await pg.connect()
            await pg.init_schema()
            app.state.pg = pg

            redis = RedisClient(
                host=config.redis_host, port=config.redis_port,
                password=config.redis_password,
            )
            await redis.connect()
            app.state.redis = redis

            logger.info("server_ready", services="nebula,pg,redis")
        except Exception as e:
            logger.error("startup_failed", error=str(e))
            for attr in ("nebula", "pg", "redis"):
                if not hasattr(app.state, attr):
                    setattr(app.state, attr, None)

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Auth routes (inline) ---
    from fastapi import Depends, HTTPException, status

    class LoginRequest(BaseModel):
        username: str
        password: str

    class RefreshRequest(BaseModel):
        refresh_token: str

    @app.post("/api/auth/login")
    async def login(body: LoginRequest):
        user = authenticate_user(body.username, body.password)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        token_data = {"sub": user["id"], "username": user["username"], "roles": user["roles"], "org_id": user["org_id"]}
        access_token = create_access_token(token_data, config.jwt_secret, config.jwt_access_expire_minutes)
        refresh_token = create_refresh_token({"sub": user["id"]}, config.jwt_secret, config.jwt_refresh_expire_days)
        return {"token": access_token, "refresh_token": refresh_token, "user": user_to_response(user)}

    @app.get("/api/auth/me")
    async def me(user=Depends(get_current_user)):
        return {"id": user["sub"], "username": user["username"], "display_name": user.get("display_name", user["username"]), "roles": user["roles"], "org_id": user.get("org_id")}

    @app.post("/api/auth/logout")
    async def logout(user=Depends(get_current_user)):
        return {"message": "Logged out"}

    @app.post("/api/auth/refresh")
    async def refresh(body: RefreshRequest):
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
        return {"token": access_token, "refresh_token": new_refresh, "user": user_to_response(user)}

    # --- Mount routers ---
    from honeybadge.server.health import router as health_router
    from honeybadge.server.sessions import router as sessions_router

    app.include_router(health_router)
    app.include_router(sessions_router)

    return app


def main():
    config = ServerConfig.from_env()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
