"""Integration tests for global exception handlers and trace_id middleware.

Uses FastAPI TestClient against a minimal app that registers the same
exception handlers and TraceIdMiddleware as the production server.
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from honeybadge.core.exceptions import (
    AppRateLimitExceeded,
    DatabaseError,
    HoneyBadgeError,
    LLMError,
    LLMGenerationError,
    LLMTimeoutError,
    MessageValidationError,
    NebulaGraphError,
    PermissionValidationError,
    PostgreSQLError,
    ProtocolError,
    RedisError,
    SchemaValidationError,
    SessionError,
    SyntaxValidationError,
    ValidationError,
    WorkerError,
    WorkerTimeoutError,
    WorkerUnavailableError,
)
from honeybadge.server.exception_handlers import register_exception_handlers
from honeybadge.server.middleware import TraceIdMiddleware


def _build_app() -> FastAPI:
    """Build a minimal app with test routes that raise each exception type."""
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)
    register_exception_handlers(app)

    class Body(BaseModel):
        value: str

    @app.get("/ok")
    async def ok():
        from honeybadge.server.envelope import success
        from honeybadge.server.middleware import get_trace_id
        return success({"ok": True}, trace_id=get_trace_id())

    @app.get("/raise/{exc_name}")
    async def raise_exc(exc_name: str):
        excs = {
            "permission": PermissionValidationError("denied"),
            "syntax": SyntaxValidationError("bad", ngql="x"),
            "schema": SchemaValidationError("bad"),
            "validation": ValidationError("bad"),
            "message": MessageValidationError("bad"),
            "session": SessionError("bad"),
            "protocol": ProtocolError("bad"),
            "worker_timeout": WorkerTimeoutError(),
            "worker_unavailable": WorkerUnavailableError("g1"),
            "worker": WorkerError("bad"),
            "llm_timeout": LLMTimeoutError(),
            "llm_generation": LLMGenerationError("bad"),
            "llm": LLMError("bad"),
            "nebula": NebulaGraphError("bad"),
            "redis": RedisError("bad"),
            "postgres": PostgreSQLError("bad"),
            "database": DatabaseError("bad"),
            "base": HoneyBadgeError("bad"),
            "app_rate_limit": AppRateLimitExceeded("slow down"),
        }
        raise excs[exc_name]

    @app.get("/http-401")
    async def http_401():
        raise HTTPException(status_code=401, detail="Not authenticated")

    @app.get("/http-403")
    async def http_403():
        raise HTTPException(status_code=403, detail="Forbidden")

    @app.get("/http-404")
    async def http_404():
        raise HTTPException(status_code=404, detail="Not found")

    @app.get("/validation-error")
    async def validation_error(body: Body):
        return {"value": body.value}

    @app.get("/unhandled")
    async def unhandled():
        raise RuntimeError("secret internal detail")

    return app


@pytest.fixture
def client():
    return TestClient(_build_app())


@pytest.fixture
def client_no_raise():
    """TestClient with raise_server_exceptions=False so the catch-all
    Exception handler returns a 500 response instead of re-raising.
    """
    return TestClient(_build_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# HoneyBadgeError subclass -> HTTP status mapping (table-driven)
# ---------------------------------------------------------------------------

STATUS_CASES = [
    ("permission", 403, "PERMISSION_DENIED"),
    ("syntax", 400, "SYNTAX_ERROR"),
    ("schema", 400, "SCHEMA_ERROR"),
    ("validation", 400, "VALIDATION_FAILED"),
    ("message", 400, "INVALID_MESSAGE"),
    ("session", 400, "SESSION_ERROR"),
    ("protocol", 400, "PROTOCOL_ERROR"),
    ("worker_timeout", 504, "TIMEOUT"),
    ("worker_unavailable", 503, "SERVICE_UNAVAILABLE"),
    ("worker", 502, "WORKER_ERROR"),
    ("llm_timeout", 504, "LLM_TIMEOUT"),
    ("llm_generation", 502, "GENERATION_ERROR"),
    ("llm", 502, "LLM_ERROR"),
    ("nebula", 503, "NEBULA_ERROR"),
    ("redis", 503, "REDIS_ERROR"),
    ("postgres", 503, "POSTGRESQL_ERROR"),
    ("database", 503, "DATABASE_ERROR"),
    ("base", 500, "INTERNAL_ERROR"),
    ("app_rate_limit", 429, "RATE_LIMIT_EXCEEDED"),
]


@pytest.mark.parametrize("exc_name,expected_status,expected_code", STATUS_CASES)
def test_honeybadge_error_status_mapping(client, exc_name, expected_status, expected_code):
    """Each HoneyBadgeError subclass should map to the correct HTTP status and code."""
    resp = client.get(f"/raise/{exc_name}")
    assert resp.status_code == expected_status
    body = resp.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == expected_code
    assert body["trace_id"] is not None
    assert len(body["trace_id"]) > 0


# ---------------------------------------------------------------------------
# HTTPException handling
# ---------------------------------------------------------------------------

def test_http_exception_401(client):
    """HTTPException(401) should return envelope with UNAUTHENTICATED code."""
    resp = client.get("/http-401")
    assert resp.status_code == 401
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "Not authenticated"
    assert body["trace_id"] is not None


def test_http_exception_403(client):
    """HTTPException(403) should return envelope with PERMISSION_DENIED code."""
    resp = client.get("/http-403")
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "PERMISSION_DENIED"


def test_http_exception_404(client):
    """HTTPException(404) should return envelope with NOT_FOUND code."""
    resp = client.get("/http-404")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# RequestValidationError (422)
# ---------------------------------------------------------------------------

def test_request_validation_error_returns_422(client):
    """RequestValidationError should return 422 with VALIDATION_FAILED code."""
    resp = client.get("/validation-error")
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert body["error"]["details"] is not None
    assert "errors" in body["error"]["details"]
    assert body["trace_id"] is not None


# ---------------------------------------------------------------------------
# Catch-all Exception (500) — must not leak str(e)
# ---------------------------------------------------------------------------

def test_unhandled_exception_returns_500(client_no_raise):
    """Unhandled Exception should return 500 with INTERNAL_ERROR code."""
    resp = client_no_raise.get("/unhandled")
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "An internal server error occurred"
    assert body["trace_id"] is not None


def test_unhandled_exception_does_not_leak_str(client_no_raise):
    """The catch-all handler must NOT leak str(e) to the client."""
    resp = client_no_raise.get("/unhandled")
    assert "secret internal detail" not in resp.text


# ---------------------------------------------------------------------------
# trace_id propagation
# ---------------------------------------------------------------------------

def test_trace_id_header_in_response(client):
    """Every response should include an X-Trace-Id header."""
    resp = client.get("/ok")
    assert "x-trace-id" in resp.headers
    assert len(resp.headers["x-trace-id"]) > 0


def test_trace_id_propagated_from_request_header(client):
    """A valid X-Trace-Id in the request should be echoed in the response."""
    sent = "TRC-20260101-000000-aaaaaaaa"
    resp = client.get("/ok", headers={"X-Trace-Id": sent})
    assert resp.headers["x-trace-id"] == sent
    body = resp.json()
    assert body["trace_id"] == sent


def test_invalid_trace_id_replaced(client):
    """An invalid X-Trace-Id should be replaced with a fresh generated one."""
    resp = client.get("/ok", headers={"X-Trace-Id": "not-a-valid-trace-id"})
    generated = resp.headers["x-trace-id"]
    assert generated != "not-a-valid-trace-id"
    assert len(generated) > 0
    body = resp.json()
    assert body["trace_id"] == generated


def test_trace_id_in_error_response(client):
    """Error responses should also include trace_id in the body."""
    resp = client.get("/raise/base")
    body = resp.json()
    assert body["trace_id"] is not None
    assert body["trace_id"] == resp.headers["x-trace-id"]


# ---------------------------------------------------------------------------
# Success response shape
# ---------------------------------------------------------------------------

def test_success_response_has_envelope(client):
    """The /ok route should return the unified envelope."""
    resp = client.get("/ok")
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == {"ok": True}
    assert body["error"] is None
    assert body["trace_id"] is not None
