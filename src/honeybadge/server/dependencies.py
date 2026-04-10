"""FastAPI dependency injection for DB clients and orchestrator."""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from honeybadge.server.auth import decode_token

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Extract and validate JWT from Authorization header."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    config = request.app.state.config
    payload = decode_token(credentials.credentials, config.jwt_secret)

    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    # Accept both server-issued tokens (type="access") and auth-service tokens (iss="honeybadge-auth")
    if payload.get("type") != "access" and payload.get("iss") != "honeybadge-auth":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    return payload


def get_pg(request: Request):
    return request.app.state.pg


def get_redis(request: Request):
    return request.app.state.redis


def get_nebula(request: Request):
    return request.app.state.nebula


def get_orchestrator(request: Request):
    return request.app.state.orchestrator
