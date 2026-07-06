"""Tests for session and auth API endpoints using FastAPI TestClient."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    from honeybadge.server.app import create_app
    from honeybadge.server.config import ServerConfig

    config = ServerConfig()
    application = create_app(config)

    # Mock DB clients in app state
    application.state.pg = AsyncMock()
    application.state.redis = AsyncMock()
    application.state.nebula = AsyncMock()
    application.state.llm = AsyncMock()
    application.state.pg._pool = MagicMock()

    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_success(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "token" in data
    assert "refresh_token" in data
    assert data["user"]["username"] == "admin"
    assert data["user"]["display_name"] == "系统管理员"
    assert body["trace_id"] is not None


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNAUTHENTICATED"


def test_login_unknown_user(client):
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


def test_me_authenticated(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["username"] == "admin"


def test_me_unauthenticated(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    body = resp.json()
    assert body["success"] is False


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "version" in data
    # Health is exempt from the envelope — raw shape, no "success" key.
    assert "success" not in data


# ---------------------------------------------------------------------------
# IDOR tests for GET /api/sessions/{id}/messages
# ---------------------------------------------------------------------------

def test_get_messages_owner(client, app):
    """The session owner should be able to fetch messages (200)."""
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    admin_token = resp.json()["data"]["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    admin_user_id = "admin"
    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = admin_user_id

    # asyncpg Record supports dict() conversion via keys()/__getitem__.
    # Use a dict subclass so dict(r) works correctly.
    class FakeRecord(dict):
        pass

    mock_rows = [
        FakeRecord(
            id="msg-1", session_id="sess-1", role="user",
            content="hello", message_type="text",
            metadata=None, created_at="2026-01-01T00:00:00Z",
        ),
    ]
    mock_conn.fetch.return_value = mock_rows
    app.state.pg._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    app.state.pg._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    resp = client.get("/api/sessions/sess-1/messages", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)


def test_get_messages_idor_non_owner(client, app):
    """A non-owner should get 404 (not 403) for another user's session."""
    resp = client.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
    analyst_token = resp.json()["data"]["token"]
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}

    admin_user_id = "admin"
    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = admin_user_id
    app.state.pg._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    app.state.pg._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    resp = client.get("/api/sessions/sess-1/messages", headers=analyst_headers)
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_get_messages_idor_nonexistent_session(client, app):
    """A nonexistent session should return 404."""
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    admin_token = resp.json()["data"]["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = None
    app.state.pg._pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    app.state.pg._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    resp = client.get("/api/sessions/nonexistent/messages", headers=admin_headers)
    assert resp.status_code == 404
