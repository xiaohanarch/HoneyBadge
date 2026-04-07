"""FastAPI application factory for HoneyBadge backend server."""

import asyncio
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
            from honeybadge.llm.adapter import OpenAICompatibleAdapter
            from honeybadge.protocols.validator import NgqlValidator
            from honeybadge.server.orchestrator import create_orchestrator

            nebula = NebulaGraphClient(host=config.nebula_host, port=config.nebula_port, user=config.nebula_user, password=config.nebula_password)
            await nebula.connect()
            app.state.nebula = nebula

            pg = PostgreSQLClient(host=config.pg_host, port=config.pg_port, user=config.pg_user, password=config.pg_password, database=config.pg_database)
            await pg.connect()
            await pg.init_schema()
            app.state.pg = pg

            redis = RedisClient(host=config.redis_host, port=config.redis_port, password=config.redis_password)
            await redis.connect()
            app.state.redis = redis

            llm = OpenAICompatibleAdapter(config={"endpoint": config.llm_endpoint, "api_key": config.llm_api_key, "model": config.llm_model})
            app.state.llm = llm

            validator = NgqlValidator()
            app.state.validator = validator

            orchestrator = create_orchestrator(config, nebula, llm, pg, redis, validator)
            app.state.orchestrator = orchestrator

            # Import gateway modules
            from honeybadge.gateway import MatrixClient, SchemaCache, RoomManager
            from honeybadge.protocols.messages import ErrorCode, ErrorMessage, ErrorPayload, ResponseMessage, ResponsePayload, serialize_message

            # Create gateway components
            schema_cache = SchemaCache()
            room_manager = RoomManager()

            # Create Matrix client with callbacks
            async def on_matrix_result(msg):
                # Route result to the appropriate WebSocket via session_id
                session_id = room_manager.get_session_id_by_trace(msg.trace_id)
                if session_id:
                    ws = app.state.active_ws_sessions.get(session_id)
                    if ws:
                        response = ResponseMessage(
                            payload=ResponsePayload(
                                summary=msg.summary,
                                raw_data=msg.data.get("rows", []) if msg.data else [],
                                columns=msg.data.get("columns", []) if msg.data else [],
                                cypher="",
                                trace_id=msg.trace_id,
                                execution_time_ms=0,
                                row_count=0,
                            ),
                        )
                        await ws.send_json(serialize_message(response))

            async def on_matrix_error(msg):
                session_id = room_manager.get_session_id_by_trace(msg.trace_id)
                if session_id:
                    ws = app.state.active_ws_sessions.get(session_id)
                    if ws:
                        error = ErrorMessage(
                            payload=ErrorPayload(
                                code=ErrorCode.EXECUTION_ERROR,
                                message=msg.error_message,
                                trace_id=msg.trace_id,
                            ),
                        )
                        await ws.send_json(serialize_message(error))

            matrix_client = MatrixClient(
                homeserver_url=config.matrix_homeserver_url,
                user_id=config.matrix_user_id,
                password=config.matrix_user_password,
                room_manager=room_manager,
                on_result=on_matrix_result,
                on_error=on_matrix_error,
            )

            app.state.matrix_client = matrix_client
            app.state.schema_cache = schema_cache
            app.state.room_manager = room_manager
            app.state.active_ws_sessions = {}  # session_id -> WebSocket

            # Bootstrap schema from Worker via Matrix
            try:
                await matrix_client.connect()
                await matrix_client.bootstrap_schema(schema_cache)
            except Exception as exc:
                logger.warning("matrix_bootstrap_failed", error=str(exc))

            logger.info("gateway_ready", schema_tags=len(schema_cache.get_tags()), schema_edges=len(schema_cache.get_edges()))
            logger.info("server_ready", services="nebula,pg,redis,llm")
        except Exception as e:
            logger.error("startup_failed", error=str(e))
            for attr in ("nebula", "pg", "redis", "llm", "orchestrator", "validator", "matrix_client", "schema_cache", "room_manager"):
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
        if hasattr(app.state, "llm") and app.state.llm:
            await app.state.llm.close()
        if hasattr(app.state, "matrix_client") and app.state.matrix_client:
            await app.state.matrix_client.disconnect()

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
    from honeybadge.server.websocket import router as ws_router

    app.include_router(health_router)
    app.include_router(sessions_router)
    app.include_router(ws_router)

    return app


def main():
    config = ServerConfig.from_env()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
