from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import PERMISSION_CONFIG

app = FastAPI(
    title="HoneyBadge Permission Service",
    description="Returns PermissionContext for a given user_id.",
    version="1.0.0",
)


class HealthResponse(BaseModel):
    status: str
    service: str


class PermissionContextResponse(BaseModel):
    user_id: str
    allowed_processes: list[str]
    org_ids: list[int] | None
    dept_ids: list[int] | None
    data_scope: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", service="honeybadge-permissions")


@app.get("/permissions/{user_id}", response_model=PermissionContextResponse)
async def get_permissions(user_id: str) -> PermissionContextResponse:
    """Get permission context for a given user_id.

    Args:
        user_id: Plain username (e.g. 'admin', 'subsidiary_lead').

    Returns:
        PermissionContext with allowed_processes, org_ids, data_scope.

    Raises:
        HTTPException 404: If user_id not found in configuration.
    """
    ctx = PERMISSION_CONFIG.get(user_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
    return PermissionContextResponse(**asdict(ctx))
