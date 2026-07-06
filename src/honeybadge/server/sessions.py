"""Session CRUD router. Uses PostgreSQL chat_sessions and chat_messages tables."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from honeybadge.server.dependencies import get_current_user, get_pg
from honeybadge.server.envelope import success
from honeybadge.server.middleware import get_trace_id

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str


@router.get("")
async def list_sessions(
    user: dict[str, Any] = Depends(get_current_user),
    pg: Any = Depends(get_pg),
) -> dict[str, Any]:
    async with pg._pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT session_id as id, title, created_at, updated_at, message_count, status
               FROM honeybadge_audit.chat_sessions
               WHERE user_id = $1 AND status != 'deleted'
               ORDER BY updated_at DESC""",
            user["sub"],
        )
    return success([dict(r) for r in rows], trace_id=get_trace_id())


@router.post("")
async def create_session(
    body: CreateSessionRequest,
    user: dict[str, Any] = Depends(get_current_user),
    pg: Any = Depends(get_pg),
) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    title = body.title or "新会话"
    now = datetime.now(timezone.utc)

    async with pg._pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO honeybadge_audit.chat_sessions
               (user_id, session_id, title, created_at, updated_at, message_count, status)
               VALUES ($1, $2, $3, $4, $5, 0, 'active')""",
            user["sub"], session_id, title, now, now,
        )
    return success({"id": session_id, "title": title, "created_at": now.isoformat(), "updated_at": now.isoformat(), "message_count": 0, "status": "active"}, trace_id=get_trace_id())


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    pg: Any = Depends(get_pg),
) -> dict[str, Any]:
    async with pg._pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT session_id as id, title, created_at, updated_at, message_count, status
               FROM honeybadge_audit.chat_sessions
               WHERE session_id = $1 AND user_id = $2 AND status != 'deleted'""",
            session_id, user["sub"],
        )
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return success(dict(row), trace_id=get_trace_id())


@router.put("/{session_id}")
async def update_session(
    session_id: str,
    body: UpdateSessionRequest,
    user: dict[str, Any] = Depends(get_current_user),
    pg: Any = Depends(get_pg),
) -> dict[str, Any]:
    async with pg._pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE honeybadge_audit.chat_sessions
               SET title = $1 WHERE session_id = $2 AND user_id = $3 AND status != 'deleted'""",
            body.title, session_id, user["sub"],
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Session not found")
    return success({"id": session_id, "title": body.title}, trace_id=get_trace_id())


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    pg: Any = Depends(get_pg),
) -> dict[str, Any]:
    async with pg._pool.acquire() as conn:
        await conn.execute(
            """UPDATE honeybadge_audit.chat_sessions
               SET status = 'deleted' WHERE session_id = $1 AND user_id = $2""",
            session_id, user["sub"],
        )
    return success({"id": session_id, "status": "deleted"}, trace_id=get_trace_id())


@router.get("/{session_id}/messages")
async def get_messages(
    session_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    pg: Any = Depends(get_pg),
) -> dict[str, Any]:
    # IDOR fix: verify the session belongs to the caller BEFORE fetching
    # messages. The chat_messages table has no user_id column, so ownership
    # is checked against chat_sessions.user_id. Returns 404 (not 403) for
    # non-owned sessions to prevent existence leakage (OWASP IDOR guidance).
    async with pg._pool.acquire() as conn:
        owner = await conn.fetchval(
            """SELECT user_id FROM honeybadge_audit.chat_sessions
               WHERE session_id = $1 AND status != 'deleted'""",
            session_id,
        )
        if owner is None or owner != user["sub"]:
            raise HTTPException(status_code=404, detail="Session not found")
        rows = await conn.fetch(
            """SELECT id, session_id, role, content, message_type, metadata, created_at
               FROM honeybadge_audit.chat_messages
               WHERE session_id = $1 ORDER BY created_at ASC""",
            session_id,
        )
    results = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        results.append(d)
    return success(results, trace_id=get_trace_id())
