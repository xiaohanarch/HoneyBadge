"""Tests for WebSocket handler."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from honeybadge.server.orchestrator import QueryResult


@pytest.fixture
def app():
    from honeybadge.server.app import create_app
    from honeybadge.server.config import ServerConfig

    config = ServerConfig()
    application = create_app(config)

    application.state.pg = AsyncMock()
    application.state.pg._pool = MagicMock()
    application.state.redis = AsyncMock()
    application.state.nebula = AsyncMock()
    application.state.llm = AsyncMock()

    mock_orchestrator = AsyncMock()
    mock_orchestrator.execute_query = AsyncMock(return_value=QueryResult(
        summary="找到3个供应商",
        raw_data=[{"name": "供应商A"}, {"name": "供应商B"}, {"name": "供应商C"}],
        columns=["name"],
        cypher="MATCH (n:Supplier) RETURN n.Supplier.supplier_name LIMIT 10",
        trace_id="TRC-20260407-120000-abcd1234",
        execution_time_ms=150,
        row_count=3,
    ))
    application.state.orchestrator = mock_orchestrator

    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def token(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    return resp.json()["token"]


def test_ws_connect_with_valid_token(client, token):
    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({"type": "heartbeat", "payload": {}, "timestamp": 1234567890})
        msg = ws.receive_json()
        assert msg["type"] == "heartbeat_ack"


def test_ws_connect_without_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws") as ws:
            pass


def test_ws_query_message(client, token):
    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({
            "type": "query",
            "payload": {"question": "查询所有供应商", "session_id": "test-session"},
            "timestamp": 1234567890,
        })
        messages = []
        for _ in range(20):
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] == "response" or msg["type"] == "error":
                break
        types = [m["type"] for m in messages]
        assert "response" in types or "error" in types
