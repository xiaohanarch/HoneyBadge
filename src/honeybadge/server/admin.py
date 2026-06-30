"""Admin-only API routes.

Role-enforced endpoints that sit at the REST API boundary (distinct from the
L3 permission injection that happens in the Cypher/worker path). All routes
require the ``admin`` role via :func:`require_admin`.
"""

from typing import Any

from fastapi import APIRouter, Depends

from honeybadge.server.auth import DEMO_USERS, user_to_response
from honeybadge.server.dependencies import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def list_users(_admin: dict[str, Any] = Depends(require_admin)) -> list[dict[str, Any]]:
    """List all users (admin only).

    Returns the demo user store without password hashes.
    """
    return [user_to_response(u) for u in DEMO_USERS.values()]
