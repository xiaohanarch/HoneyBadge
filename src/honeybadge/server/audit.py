"""Audit trail API router.

Security:
  - Non-privileged users can only retrieve their own audit records.
  - Privileged users (admin/auditor) can view records within their own
    organization (``org_id`` match). A superadmin with ``org_id IS NULL``
    in the JWT (or the ``"superadmin"`` role) can view records across all
    organizations — this is the only role that bypasses the org filter.
  This enforces L5 audit isolation at both the user and tenant boundary.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from honeybadge.server.dependencies import get_current_user, get_pg

router = APIRouter(prefix="/api/audit", tags=["audit"])

_ADMIN_ROLES = frozenset({"admin", "auditor", "superadmin"})
_SUPERADMIN_ROLE = "superadmin"


class AuditTrailResponse(BaseModel):
    trace_id: str
    question: str
    cypher: str
    summary: str
    session_id: str
    user_id: str
    execution_time_ms: int
    row_count: int
    created_at: str
    llm_model: str | None = None
    error_message: str | None = None
    rows: list[dict[str, Any]] | None = None
    columns: list[str] | None = None


def _is_privileged(user: dict[str, Any]) -> bool:
    """Return True if the user has an admin or auditor role."""
    roles = user.get("roles") or []
    return any(r in _ADMIN_ROLES for r in roles)


def _is_superadmin(user: dict[str, Any]) -> bool:
    """Return True if the user can bypass org-level filtering.

    A superadmin has either the ``"superadmin"`` role or ``org_id IS NULL``
    in the JWT (the legacy admin pattern where None means "all orgs").
    """
    roles = user.get("roles") or []
    if _SUPERADMIN_ROLE in roles:
        return True
    # JWT org_id=None signals cross-org access (the original admin design).
    return user.get("org_id") is None and _is_privileged(user)


def _user_identity(user: dict[str, Any]) -> str:
    """Extract the canonical identity string for ownership checks.

    Matches the value written to ``audit_logs.user_id`` at query time
    (see websocket.py: ``payload.get("username", payload.get("sub"))``).
    """
    return user.get("username") or user.get("sub") or ""


def _user_org_id(user: dict[str, Any]) -> int | None:
    """Extract org_id from the JWT payload, if present."""
    org = user.get("org_id")
    if isinstance(org, int):
        return org
    if isinstance(org, str) and org.isdigit():
        return int(org)
    return None


@router.get("/{trace_id}", response_model=AuditTrailResponse)
async def get_audit_trail(
    trace_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    pg: Any = Depends(get_pg),
) -> AuditTrailResponse:
    """Get audit trail by trace_id.

    Returns the full L5 audit chain: question -> nGQL -> raw result -> summary.

    Access control:
        - Users with ``admin`` or ``auditor`` role may view any record.
        - Other users may only view records where ``user_id`` matches
          their own identity. Mismatches return 403.

    Requires authentication.
    """
    if pg is None:
        raise HTTPException(status_code=503, detail="PostgreSQL not available")

    try:
        result = await pg.get_audit_log(trace_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query audit log: {e}") from e

    if result is None:
        # Return 404 for non-existent records rather than 403, to avoid
        # leaking existence information to non-privileged users.
        raise HTTPException(status_code=404, detail=f"Audit log not found for trace_id: {trace_id}")

    # Enforce per-user isolation for non-privileged users
    if not _is_privileged(user):
        record_owner = result.get("user_id") or ""
        requester = _user_identity(user)
        if record_owner and requester and record_owner != requester:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to view this audit record",
            )

    # Tenant boundary: privileged users (admin/auditor) are further restricted
    # to records within their own organization. Only superadmin (org_id=None
    # or explicit "superadmin" role) can view cross-org audit records.
    # Records with org_id=NULL (legacy rows written before the column existed)
    # are visible only to superadmin — org-scoped admins cannot see them.
    if _is_privileged(user) and not _is_superadmin(user):
        requester_org = _user_org_id(user)
        record_org = result.get("org_id")
        if requester_org is not None and record_org is not None and requester_org != record_org:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to view audit records from another organization",
            )

    # Extract rows and columns from raw_result (JSONB)
    raw_result = result.get("raw_result") or {}
    if isinstance(raw_result, dict):
        rows = raw_result.get("rows")
        columns = raw_result.get("columns")
        if rows is None:
            # raw_result is the rows array directly
            rows = raw_result if isinstance(raw_result, list) else None
    else:
        rows = None
        columns = None

    return AuditTrailResponse(
        trace_id=result["trace_id"],
        question=result["question"],
        cypher=result["cypher"],
        summary=result["summary"],
        session_id=result.get("session_id") or "",
        user_id=result.get("user_id") or "",
        execution_time_ms=result.get("execution_time_ms") or 0,
        row_count=result.get("row_count") or 0,
        created_at=result.get("created_at").isoformat() if result.get("created_at") else "",
        llm_model=result.get("llm_model"),
        error_message=result.get("error_message"),
        rows=rows,
        columns=columns,
    )
