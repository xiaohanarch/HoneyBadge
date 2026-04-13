"""Audit trail API router."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from honeybadge.server.dependencies import get_current_user, get_pg

router = APIRouter(prefix="/api/audit", tags=["audit"])


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


@router.get("/{trace_id}", response_model=AuditTrailResponse)
async def get_audit_trail(
    trace_id: str,
    user: dict = Depends(get_current_user),
    pg=Depends(get_pg),
) -> AuditTrailResponse:
    """Get audit trail by trace_id.

    Returns the full L5 audit chain: question -> nGQL -> raw result -> summary.
    Requires authentication.
    """
    if pg is None:
        raise HTTPException(status_code=503, detail="PostgreSQL not available")

    try:
        result = await pg.get_audit_log(trace_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query audit log: {e}")

    if result is None:
        raise HTTPException(status_code=404, detail=f"Audit log not found for trace_id: {trace_id}")

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
