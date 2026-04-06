"""Tests for WebSocket message protocol."""

import pytest

from honeybadge.protocols.messages import (
    ErrorCode,
    ErrorMessage,
    ErrorPayload,
    HeartbeatMessage,
    ProgressMessage,
    ProgressPayload,
    QueryMessage,
    QueryPayload,
    ResponseMessage,
    ResponsePayload,
    StreamMessage,
    StreamPayload,
    StreamPhase,
    parse_message,
    serialize_message,
)


class TestQueryMessage:
    """Tests for QueryMessage."""

    def test_create_query_message(self):
        """Should create valid query message."""
        payload = QueryPayload(question="测试问题", session_id="sess_123")
        message = QueryMessage(payload=payload)

        assert message.type == "query"
        assert message.payload.question == "测试问题"
        assert message.payload.session_id == "sess_123"
        assert message.timestamp > 0

    def test_serialize_query_message(self):
        """Should serialize query message to dict."""
        payload = QueryPayload(question="测试问题", session_id="sess_123")
        message = QueryMessage(payload=payload)
        data = serialize_message(message)

        assert data["type"] == "query"
        assert data["payload"]["question"] == "测试问题"
        assert data["payload"]["session_id"] == "sess_123"

    def test_parse_query_message(self):
        """Should parse dict to QueryMessage."""
        data = {
            "type": "query",
            "payload": {"question": "测试问题", "session_id": "sess_123"},
            "timestamp": 1712188800000,
        }
        message = parse_message(data)

        assert isinstance(message, QueryMessage)
        assert message.payload.question == "测试问题"


class TestHeartbeatMessage:
    """Tests for HeartbeatMessage."""

    def test_create_heartbeat(self):
        """Should create heartbeat message."""
        message = HeartbeatMessage()

        assert message.type == "heartbeat"
        assert message.timestamp > 0

    def test_parse_heartbeat(self):
        """Should parse heartbeat message."""
        data = {"type": "heartbeat", "timestamp": 1712188800000}
        message = parse_message(data)

        assert isinstance(message, HeartbeatMessage)


class TestProgressMessage:
    """Tests for ProgressMessage."""

    def test_create_progress(self):
        """Should create progress message."""
        payload = ProgressPayload(
            step="正在理解问题",
            step_number=1,
            total_steps=5,
        )
        message = ProgressMessage(payload=payload, trace_id="TRC-123")

        assert message.type == "progress"
        assert message.payload.step_number == 1
        assert message.payload.total_steps == 5
        assert message.trace_id == "TRC-123"


class TestStreamMessage:
    """Tests for StreamMessage."""

    def test_create_stream_message(self):
        """Should create stream message."""
        payload = StreamPayload(
            content="发现",
            phase=StreamPhase.SUMMARIZING,
            done=False,
        )
        message = StreamMessage(payload=payload, trace_id="TRC-123")

        assert message.type == "stream"
        assert message.payload.content == "发现"
        assert message.payload.phase == StreamPhase.SUMMARIZING
        assert message.payload.done is False

    def test_stream_phases(self):
        """Should have correct stream phases."""
        assert StreamPhase.THINKING.value == "thinking"
        assert StreamPhase.CYPHER.value == "cypher"
        assert StreamPhase.EXECUTING.value == "executing"
        assert StreamPhase.SUMMARIZING.value == "summarizing"


class TestResponseMessage:
    """Tests for ResponseMessage."""

    def test_create_response(self):
        """Should create response message."""
        payload = ResponsePayload(
            summary="测试摘要",
            raw_data=[{"col1": "val1"}],
            columns=["col1"],
            cypher="MATCH (n) RETURN n",
            trace_id="TRC-123",
            execution_time_ms=100,
            row_count=1,
        )
        message = ResponseMessage(payload=payload)

        assert message.type == "response"
        assert message.payload.summary == "测试摘要"
        assert message.payload.row_count == 1


class TestErrorMessage:
    """Tests for ErrorMessage."""

    def test_create_error(self):
        """Should create error message."""
        payload = ErrorPayload(
            code=ErrorCode.VALIDATION_FAILED,
            message="验证失败",
        )
        message = ErrorMessage(payload=payload)

        assert message.type == "error"
        assert message.payload.code == ErrorCode.VALIDATION_FAILED
        assert message.payload.message == "验证失败"

    def test_error_codes(self):
        """Should have all error codes."""
        assert ErrorCode.VALIDATION_FAILED.value == "VALIDATION_FAILED"
        assert ErrorCode.EXECUTION_ERROR.value == "EXECUTION_ERROR"
        assert ErrorCode.LLM_ERROR.value == "LLM_ERROR"
        assert ErrorCode.TIMEOUT.value == "TIMEOUT"
        assert ErrorCode.RATE_LIMIT.value == "RATE_LIMIT"
        assert ErrorCode.SERVICE_UNAVAILABLE.value == "SERVICE_UNAVAILABLE"
        assert ErrorCode.INTERNAL_ERROR.value == "INTERNAL_ERROR"


class TestParseMessage:
    """Tests for parse_message function."""

    def test_parse_unknown_type_raises_error(self):
        """Should raise ValueError for unknown message type."""
        with pytest.raises(ValueError, match="Unknown message type"):
            parse_message({"type": "unknown"})
