# src/honeybadge/permission_service/main.py
"""HoneyBadge Permission Service.

Stateless microservice that:
1. Returns PermissionContext for a given user_id from PERMISSION_CONFIG
2. Validates user exists before returning permissions
"""

from __future__ import annotations
from dataclasses import asdict

from fastapi import FastAPI, HTTPException

from .config import PERMISSION_CONFIG

app = FastAPI(
    title="HoneyBadge Permission Service",
    description="Returns PermissionContext for a given user_id.",
    version="1.0.0",
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "honeybadge-permissions"}


@app.get("/permissions/{user_id}")
async def get_permissions(user_id: str):
    """Get permission context for a given user_id.

    Args:
        user_id: The user identifier

    Returns:
        PermissionContext as a dict containing:
        - user_id: The user identifier
        - allowed_processes: List of allowed processes (["PTP"], ["OTC"], ["PTP", "OTC"])
        - org_ids: Allowed organization IDs (None = all orgs; [2] = org_id=2 only)
        - dept_ids: Allowed department IDs (None for now)
        - data_scope: Data scope level ("ALL" / "ORG" / "DEPT")

    Raises:
        HTTPException 404 if user_id not found in PERMISSION_CONFIG
    """
    ctx = PERMISSION_CONFIG.get(user_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
    return asdict(ctx)
