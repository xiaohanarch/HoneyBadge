"""WebSocket message protocol for HoneyBadge."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """WebSocket message types."""

    # Client → Server
    QUERY = "query"
    HEARTBEAT = "heartbeat"

    # Server → Client
    PROGRESS = "progress"
    STREAM = "stream"
    RESPONSE = "response"
    ERROR = "error"
    HEARTBEAT_ACK = "heartbeat_ack"


class StreamPhase(str, Enum):
    """Stream phase values."""

    THINKING = "thinking"
    CYPHER = "cypher"
    EXECUTING = "executing"
    SUMMARIZING = "summarizing"


class ErrorCode(str, Enum):
    """Error codes for error messages."""

    VALIDATION_FAILED = "VALIDATION_FAILED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    LLM_ERROR = "LLM_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# =============================================================================
# Client → Server Messages
# =============================================================================


class QueryPayload(BaseModel):
    """Payload for query message."""

    question: str = Field(..., description="User's natural language question")
    session_id: str = Field(..., description="Session identifier")


class QueryMessage(BaseModel):
    """Client sends a query."""

    type: Literal["query"] = "query"
    payload: QueryPayload
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000),
        description="Message timestamp in milliseconds",
    )


class HeartbeatMessage(BaseModel):
    """Client heartbeat."""

    type: Literal["heartbeat"] = "heartbeat"
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000),
    )


# =============================================================================
# Server → Client Messages
# =============================================================================


class ProgressPayload(BaseModel):
    """Payload for progress message."""

    step: str = Field(..., description="Current step description")
    step_number: int = Field(..., ge=1, description="Current step number")
    total_steps: int = Field(..., ge=1, description="Total number of steps")
    detail: Optional[str] = Field(None, description="Optional detail text")


class ProgressMessage(BaseModel):
    """Server sends execution progress."""

    type: Literal["progress"] = "progress"
    payload: ProgressPayload
    trace_id: str = Field(..., description="Trace identifier for correlation")
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000),
    )


class StreamPayload(BaseModel):
    """Payload for stream message."""

    content: str = Field(..., description="Text content being streamed")
    phase: StreamPhase = Field(..., description="Current processing phase")
    done: bool = Field(..., description="Whether this is the final message")


class StreamMessage(BaseModel):
    """Server sends streaming text output."""

    type: Literal["stream"] = "stream"
    payload: StreamPayload
    trace_id: str
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000),
    )


class ResponsePayload(BaseModel):
    """Payload for final response message."""

    summary: str = Field(..., description="AI-generated summary of results")
    raw_data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw query results",
    )
    columns: list[str] = Field(
        default_factory=list,
        description="Column names",
    )
    cypher: str = Field(..., description="Generated nGQL query")
    trace_id: str = Field(..., description="Trace identifier")
    execution_time_ms: int = Field(..., ge=0, description="Query execution time")
    row_count: int = Field(..., ge=0, description="Number of result rows")


class ResponseMessage(BaseModel):
    """Server sends final response."""

    type: Literal["response"] = "response"
    payload: ResponsePayload
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000),
    )


class ErrorPayload(BaseModel):
    """Payload for error message."""

    code: ErrorCode = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    trace_id: Optional[str] = Field(None, description="Associated trace ID")


class ErrorMessage(BaseModel):
    """Server sends error."""

    type: Literal["error"] = "error"
    payload: ErrorPayload
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000),
    )


class HeartbeatAckMessage(BaseModel):
    """Server acknowledges heartbeat."""

    type: Literal["heartbeat_ack"] = "heartbeat_ack"
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now().timestamp() * 1000),
    )


# =============================================================================
# Message Parsing
# =============================================================================


def parse_message(data: dict[str, Any]) -> BaseModel:
    """
    Parse incoming message into appropriate message type.

    Args:
        data: Raw message dictionary

    Returns:
        Parsed message object

    Raises:
        ValueError: If message type is unknown or invalid
    """
    msg_type = data.get("type")

    if msg_type == "query":
        return QueryMessage(**data)
    elif msg_type == "heartbeat":
        return HeartbeatMessage(**data)
    else:
        raise ValueError(f"Unknown message type: {msg_type}")


def serialize_message(msg: BaseModel) -> dict[str, Any]:
    """
    Serialize message to dictionary for WebSocket transmission.

    Args:
        msg: Message object

    Returns:
        Dictionary representation
    """
    return msg.model_dump(mode="json")
