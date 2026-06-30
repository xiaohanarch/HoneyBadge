"""FastAPI application factory for HoneyBadge backend server."""

import json
import time
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
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

logger = structlog.get_logger()


def create_app(config: ServerConfig | None = None) -> FastAPI:
    if config is None:
        config = ServerConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
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
            ready.append("redis")
        except Exception as e:
            logger.error("redis_init_failed", error=str(e))

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
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
    from honeybadge.server.admin import router as admin_router
    from honeybadge.server.audit import router as audit_router
    from honeybadge.server.health import router as health_router
    from honeybadge.server.sessions import router as sessions_router

    app.include_router(health_router)
    app.include_router(sessions_router)
    app.include_router(audit_router)
    app.include_router(admin_router)

    # --- WebSocket endpoint ---
    from fastapi import WebSocket, WebSocketDisconnect

    from honeybadge.server.websocket import build_query_response, process_query

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for query processing with full metadata."""
        from honeybadge.server.auth import decode_token

        # Extract token from query params
        token = websocket.query_params.get("token", "")
        user_id = "anonymous"
        if token:
            payload = decode_token(token, config.jwt_secret)
            if payload:
                user_id = payload.get("username", payload.get("sub", "anonymous"))

        await websocket.accept()

        try:
            while True:
                # Receive message
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"type": "error", "payload": {"message": "Invalid JSON"}}))
                    continue

                msg_type = msg.get("type")
                payload = msg.get("payload", {})

                if msg_type == "query":
                    question = payload.get("question", "")
                    session_id = payload.get("session_id", "")

                    # Get clients from app state
                    nebula = websocket.app.state.nebula
                    pg = websocket.app.state.pg
                    llm = getattr(websocket.app.state, "llm", None)

                    if not nebula or not pg:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "payload": {"message": "Server not fully initialized"},
                        }))
                        continue

                    if not llm:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "payload": {"message": "LLM not configured"},
                        }))
                        continue

                    # Process query
                    result = await process_query(
                        question=question,
                        session_id=session_id,
                        nebula=nebula,
                        pg=pg,
                        llm_adapter=llm,
                        user_id=user_id,
                    )

                    # Send response
                    response = build_query_response(result)
                    await websocket.send_text(json.dumps(response))

                elif msg_type == "heartbeat":
                    await websocket.send_text(json.dumps({"type": "heartbeat", "timestamp": int(time.time() * 1000)}))

        except WebSocketDisconnect:
            logger.info("ws_client_disconnected")
        except Exception as e:
            logger.error("ws_error", error=str(e))
            try:
                await websocket.send_text(json.dumps({"type": "error", "payload": {"message": str(e)}}))
            except Exception:
                pass

    return app


def main():
    config = ServerConfig.from_env()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
