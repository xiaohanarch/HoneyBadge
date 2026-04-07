"""WebSocket handler for HoneyBadge query pipeline."""

import json
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from honeybadge.server.auth import decode_token
from honeybadge.server.orchestrator import PipelineCallbacks, QueryResult
from honeybadge.protocols.messages import (
    ErrorCode,
    ErrorMessage,
    ErrorPayload,
    HeartbeatAckMessage,
    ProgressMessage,
    ProgressPayload,
    ResponseMessage,
    ResponsePayload,
    StreamMessage,
    StreamPayload,
    StreamPhase,
    serialize_message,
)

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

    if not question:
        await _send_error(websocket, ErrorCode.VALIDATION_FAILED, "Empty question")
        return

    orchestrator = websocket.app.state.orchestrator
    if orchestrator is None:
        await _send_error(websocket, ErrorCode.SERVICE_UNAVAILABLE, "Orchestrator not available")
        return

    user_context = {
        "user_id": user_payload["sub"],
        "username": user_payload.get("username"),
        "org_ids": [user_payload.get("org_id")] if user_payload.get("org_id") else [],
        "data_scope": "ALL",
    }

    async def on_progress(step_number: int, total_steps: int, step: str, detail=None) -> None:
        msg = ProgressMessage(payload=ProgressPayload(step=step, step_number=step_number, total_steps=total_steps, detail=detail), trace_id="")
        await websocket.send_json(serialize_message(msg))

    async def on_stream(content: str, phase: str, done: bool) -> None:
        msg = StreamMessage(payload=StreamPayload(content=content, phase=StreamPhase(phase), done=done), trace_id="")
        await websocket.send_json(serialize_message(msg))

    callbacks = PipelineCallbacks(on_progress=on_progress, on_stream=on_stream)

    result = await orchestrator.execute_query(question=question, session_id=session_id, user_context=user_context, callbacks=callbacks)

    if result.error:
        await _send_error(websocket, ErrorCode.EXECUTION_ERROR, result.error, result.trace_id)
    else:
        response = ResponseMessage(
            payload=ResponsePayload(
                summary=result.summary, raw_data=result.raw_data, columns=result.columns,
                cypher=result.cypher, trace_id=result.trace_id,
                execution_time_ms=result.execution_time_ms, row_count=result.row_count,
            ),
        )
        await websocket.send_json(serialize_message(response))

    # Save messages to PostgreSQL
    pg = websocket.app.state.pg
    if pg and hasattr(pg, '_pool') and pg._pool:
        try:
            async with pg._pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO honeybadge_audit.chat_messages (session_id, role, content, message_type, metadata) VALUES ($1, 'user', $2, 'text', NULL)""",
                    session_id, question,
                )
                metadata = json.dumps({"trace_id": result.trace_id, "cypher": result.cypher, "raw_data": result.raw_data, "columns": result.columns, "execution_time_ms": result.execution_time_ms}, ensure_ascii=False, default=str)
                await conn.execute(
                    """INSERT INTO honeybadge_audit.chat_messages (session_id, role, content, message_type, metadata) VALUES ($1, 'assistant', $2, $3, $4::jsonb)""",
                    session_id, result.summary, "query_result" if not result.error else "error", metadata,
                )
                await conn.execute(
                    """UPDATE honeybadge_audit.chat_sessions SET message_count = message_count + 2 WHERE session_id = $1""",
                    session_id,
                )
        except Exception as e:
            logger.error("save_messages_failed", error=str(e))


async def _send_error(websocket: WebSocket, code: ErrorCode, message: str, trace_id: str = "") -> None:
    msg = ErrorMessage(payload=ErrorPayload(code=code, message=message, trace_id=trace_id or None))
    await websocket.send_json(serialize_message(msg))
