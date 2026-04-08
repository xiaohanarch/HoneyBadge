"""End-to-end integration tests for the HoneyBadge server.

These tests use FastAPI TestClient with mocked DB clients.
For full Docker-based integration, use the Docker Compose environment.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from honeybadge.server.app import create_app
from honeybadge.server.config import ServerConfig
from honeybadge.server.orchestrator import QueryResult


class MockConnContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class MockPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return MockConnContext(self._conn)


@pytest.fixture
def config():
    return ServerConfig()


@pytest.fixture
def app(config):
    application = create_app(config)

    # Mock infrastructure
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
    mock_conn.fetchval = AsyncMock(return_value=1)

    application.state.pg = AsyncMock()
    application.state.pg._pool = MockPool(mock_conn)
    application.state.pg.write_audit_log = AsyncMock(return_value=True)

    application.state.redis = AsyncMock()
    application.state.redis._client = AsyncMock()
    application.state.redis._client.ping = AsyncMock(return_value=True)

    application.state.nebula = AsyncMock()
    application.state.nebula._pool = True

    application.state.llm = AsyncMock()
    application.state.llm.health_check = AsyncMock(return_value=True)

    # Mock orchestrator returns a successful result
    mock_orchestrator = AsyncMock()
    mock_orchestrator.execute_query = AsyncMock(return_value=QueryResult(
        summary="找到5个活跃供应商",
        raw_data=[
            {"supplier_name": "大连黄海贸易有限公司", "status": "ACTIVE"},
            {"supplier_name": "成都孙超贸易有限公司", "status": "ACTIVE"},
        ],
        columns=["supplier_name", "status"],
        cypher="MATCH (n:Supplier) WHERE n.Supplier.status == 'ACTIVE' RETURN n.Supplier.supplier_name, n.Supplier.status LIMIT 100",
        trace_id="TRC-20260407-120000-abcd1234",
        execution_time_ms=150,
        row_count=2,
    ))
    application.state.orchestrator = mock_orchestrator

    # Mock gateway components (normally set in lifespan, but TestClient skips it)
    # The on_result/on_error callbacks live on application.state so the mock can call them
    from honeybadge.gateway.matrix_client import MatrixMessage
    from honeybadge.protocols.messages import ResponseMessage, ResponsePayload, serialize_message

    async def mock_on_result(msg: MatrixMessage):
        session_id = application.state.room_manager.get_session_id_by_trace(msg.trace_id)
        if session_id:
            ws = application.state.active_ws_sessions.get(session_id)
            if ws:
                response = ResponseMessage(
                    payload=ResponsePayload(
                        summary=msg.summary or "找到5个活跃供应商",
                        raw_data=msg.data.get("rows", []) if msg.data else [],
                        columns=msg.data.get("columns", []) if msg.data else [],
                        cypher="",
                        trace_id=msg.trace_id or "TRC-20260407-120000-abcd1234",
                        execution_time_ms=0,
                        row_count=2,
                    ),
                )
                await ws.send_json(serialize_message(response))

    async def mock_send_query(question, trace_id, user_id, org_id, roles, session_id):
        # Simulate Matrix client sending query and immediately triggering the result callback
        import asyncio
        asyncio.get_event_loop().create_task(mock_on_result(MatrixMessage(
            msgtype="result",
            trace_id=trace_id,
            summary="找到5个活跃供应商",
            data={"rows": [
                {"supplier_name": "大连黄海贸易有限公司", "status": "ACTIVE"},
                {"supplier_name": "成都孙超贸易有限公司", "status": "ACTIVE"},
            ], "columns": ["supplier_name", "status"]},
        )))

    application.state.matrix_client = AsyncMock()
    application.state.matrix_client.send_query = mock_send_query
    application.state.matrix_client.on_result = mock_on_result
    application.state.room_manager = MagicMock()
    application.state.room_manager.register_trace = MagicMock()
    application.state.room_manager.get_session_id_by_trace = MagicMock(return_value="test-session")
    application.state.schema_cache = AsyncMock()
    application.state.active_ws_sessions = {}

    return application


@pytest.fixture
def client(app):
    return TestClient(app)


class TestE2EAuthFlow:
    """Test the complete authentication flow."""

    def test_login_and_access(self, client):
        # Login
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200
        data = resp.json()
        token = data["token"]
        refresh = data["refresh_token"]
        assert data["user"]["username"] == "admin"

        # Access protected endpoint
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

        # Refresh token
        resp = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 200
        assert "token" in resp.json()
        assert "refresh_token" in resp.json()

    def test_unauthenticated_access_blocked(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

        resp = client.get("/api/sessions", headers={"Authorization": "Bearer invalid"})
        assert resp.status_code == 401


class TestE2EHealthCheck:
    """Test health check endpoint."""

    def test_health_returns_service_status(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert "services" in data
        assert "redis" in data["services"]
        assert "postgres" in data["services"]
        assert "nebula" in data["services"]


class TestE2EQueryFlow:
    """Test the complete query flow via WebSocket."""

    def test_full_query_flow(self, client):
        # Login first
        resp = client.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
        token = resp.json()["token"]

        # Connect WebSocket and send query
        with client.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_json({
                "type": "query",
                "payload": {"question": "查询所有活跃供应商", "session_id": "test-session"},
                "timestamp": 1234567890,
            })

            # Collect messages
            messages = []
            for _ in range(30):
                msg = ws.receive_json()
                messages.append(msg)
                if msg["type"] in ("response", "error"):
                    break

            # Verify we got a response
            response_msgs = [m for m in messages if m["type"] == "response"]
            assert len(response_msgs) == 1
            resp_data = response_msgs[0]["payload"]
            assert resp_data["row_count"] == 2
            assert resp_data["trace_id"].startswith("TRC-")
            assert "供应商" in resp_data["summary"]

    def test_heartbeat(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        token = resp.json()["token"]

        with client.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_json({"type": "heartbeat", "payload": {}, "timestamp": 1234567890})
            msg = ws.receive_json()
            assert msg["type"] == "heartbeat_ack"
