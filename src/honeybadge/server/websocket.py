"""WebSocket handler for HoneyBadge query pipeline."""

import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from honeybadge.core.trace import generate_trace_id
from honeybadge.protocols.messages import (
    ErrorCode,
    ErrorMessage,
    ErrorPayload,
    HeartbeatAckMessage,
    ProgressMessage,
    ProgressPayload,
    serialize_message,
)
from honeybadge.server.auth import decode_token

logger = structlog.get_logger()

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    config = websocket.app.state.config
    payload = decode_token(token, config.jwt_secret)
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    user_id = payload["sub"]
    username = payload.get("username", "unknown")
    logger.info("ws_connected", user_id=user_id, username=username)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, ErrorCode.INTERNAL_ERROR, "Invalid JSON")
                continue

            msg_type = data.get("type")

            if msg_type == "heartbeat":
                ack = HeartbeatAckMessage()
                await websocket.send_json(serialize_message(ack))

            elif msg_type == "query":
                await _handle_query(websocket, data, payload)

            else:
                await _send_error(websocket, ErrorCode.INTERNAL_ERROR, f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info("ws_disconnected", user_id=user_id)
    except Exception as e:
        logger.error("ws_error", user_id=user_id, error=str(e))
        try:
            await _send_error(websocket, ErrorCode.INTERNAL_ERROR, str(e))
        except Exception:
            pass


async def _handle_query(websocket: WebSocket, data: dict, user_payload: dict) -> None:
    question = data.get("payload", {}).get("question", "")
    session_id = data.get("payload", {}).get("session_id", "")

    # ---- Lightweight Input Filtering ----
    # Full L1-L3 validation happens in Worker after nGQL generation.
    # Gateway only does basic safety checks on the raw question.

    # Check: empty question
    if not question.strip():
        await _send_error(websocket, ErrorCode.VALIDATION_FAILED, "Empty question", "")
        return

    # Check: write operations attempted at gateway level
    write_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"]
    question_upper = question.upper()
    for kw in write_keywords:
        if kw in question_upper:
            await _send_error(websocket, ErrorCode.PERMISSION_DENIED, f"Write operations not allowed: {kw}", "")
            return

    matrix_client = websocket.app.state.matrix_client
    room_manager = websocket.app.state.room_manager

    if matrix_client is None:
        await _send_error(websocket, ErrorCode.SERVICE_UNAVAILABLE, "Matrix client not initialized", "")
        return

    # Register WebSocket session for response routing
    websocket.app.state.active_ws_sessions[session_id] = websocket
    room_manager.register_trace("", session_id)  # temporary mapping until trace_id assigned

    trace_id = generate_trace_id()
    room_manager.register_trace(trace_id, session_id)

    # Forward to Matrix → Manager → Worker (L1-L3 validation happens in Worker)
    await matrix_client.send_query(
        question=question,
        trace_id=trace_id,
        user_id=user_payload["sub"],
        org_id=user_payload.get("org_id", ""),
        roles=user_payload.get("roles", []),
        session_id=session_id,
    )

    # Send progress: query forwarded to Manager
    progress_msg = ProgressMessage(
        payload=ProgressPayload(
            step="Query forwarded to Manager",
            step_number=1,
            total_steps=3,
            detail=f"trace_id={trace_id}",
        ),
        trace_id=trace_id,
    )
    await websocket.send_json(serialize_message(progress_msg))

    # Save user message to PostgreSQL (optimistic)
    pg = websocket.app.state.pg
    if pg and hasattr(pg, '_pool') and pg._pool:
        try:
            async with pg._pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO chat_sessions (session_id, user_id, message_count, last_trace_id) VALUES ($1, $2, 1, $3) ON CONFLICT (session_id) DO UPDATE SET message_count = chat_sessions.message_count + 1, updated_at = NOW(), last_trace_id = $3""",
                    session_id, user_payload["sub"], trace_id,
                )
                await conn.execute(
                    """INSERT INTO chat_messages (session_id, role, content, message_type, metadata) VALUES ($1, 'user', $2, 'text', NULL)""",
                    session_id, question,
                )
        except Exception as e:
            logger.error("save_user_message_failed", error=str(e))


async def _send_error(websocket: WebSocket, code: ErrorCode, message: str, trace_id: str = "") -> None:
    msg = ErrorMessage(payload=ErrorPayload(code=code, message=message, trace_id=trace_id or None))
    await websocket.send_json(serialize_message(msg))
