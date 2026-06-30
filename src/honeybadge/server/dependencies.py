"""FastAPI dependency injection for DB clients and orchestrator."""


from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from honeybadge.server.auth import decode_token

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
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


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Verify the authenticated user has the 'admin' role.

    Use as a route dependency to enforce admin-only access at the REST API
    boundary. Returns 401 if unauthenticated, 403 if authenticated but non-admin.
    """
    roles = user.get("roles") or []
    if "admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def get_pg(request: Request) -> Any:
    return request.app.state.pg


def get_redis(request: Request) -> Any:
    return request.app.state.redis


def get_nebula(request: Request) -> Any:
    return request.app.state.nebula


def get_orchestrator(request: Request) -> Any:
    return request.app.state.orchestrator
