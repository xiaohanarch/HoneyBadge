"""Global exception handlers that map the HoneyBadge error hierarchy to HTTP.

All handlers return the unified envelope (see :mod:`honeybadge.server.envelope`)
and include the current ``trace_id`` so clients can correlate failures with
audit logs. The catch-all ``Exception`` handler logs the full traceback
server-side but returns a generic message to the client to avoid leaking
internal details.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from honeybadge.core.exceptions import (
    AppRateLimitExceeded,
    DatabaseError,
    HoneyBadgeError,
    LLMError,
    LLMGenerationError,
    LLMSummarizationError,
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
from honeybadge.server.envelope import error
from honeybadge.server.middleware import get_trace_id

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Exception -> (HTTP status, error code) mapping
# Most specific subclasses first; the base HoneyBadgeError is the fallback.
# ---------------------------------------------------------------------------

_STATUS_MAP: list[tuple[type[HoneyBadgeError], int, str]] = [
    (PermissionValidationError, 403, "PERMISSION_DENIED"),
    (SyntaxValidationError, 400, "SYNTAX_ERROR"),
    (SchemaValidationError, 400, "SCHEMA_ERROR"),
    (ValidationError, 400, "VALIDATION_FAILED"),
    (MessageValidationError, 400, "INVALID_MESSAGE"),
    (SessionError, 400, "SESSION_ERROR"),
    (ProtocolError, 400, "PROTOCOL_ERROR"),
    (WorkerTimeoutError, 504, "TIMEOUT"),
    (WorkerUnavailableError, 503, "SERVICE_UNAVAILABLE"),
    (WorkerError, 502, "WORKER_ERROR"),
    (LLMTimeoutError, 504, "LLM_TIMEOUT"),
    (LLMGenerationError, 502, "GENERATION_ERROR"),
    (LLMSummarizationError, 502, "GENERATION_ERROR"),
    (LLMError, 502, "LLM_ERROR"),
    (NebulaGraphError, 503, "NEBULA_ERROR"),
    (RedisError, 503, "REDIS_ERROR"),
    (PostgreSQLError, 503, "POSTGRESQL_ERROR"),
    (DatabaseError, 503, "DATABASE_ERROR"),
    (AppRateLimitExceeded, 429, "RATE_LIMIT_EXCEEDED"),
]

_STATUS_CODE_TO_DEFAULT_CODE: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_ERROR",
    501: "NOT_IMPLEMENTED",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}


def _lookup_honeybadge_error(exc: HoneyBadgeError) -> tuple[int, str]:
    """Return (http_status, error_code) for a HoneyBadgeError subclass."""
    for exc_type, http_status, code in _STATUS_MAP:
        if isinstance(exc, exc_type):
            return http_status, code
    # Fallback for the base HoneyBadgeError itself
    return 500, "INTERNAL_ERROR"


def register_exception_handlers(app: FastAPI) -> None:
    """Register all global exception handlers on the FastAPI app."""

    @app.exception_handler(HoneyBadgeError)
    async def _honeybadge_error_handler(request: Request, exc: HoneyBadgeError) -> JSONResponse:
        http_status, code = _lookup_honeybadge_error(exc)
        trace_id = get_trace_id()
        logger.warning(
            "honeybadge_error",
            code=code,
            status=http_status,
            trace_id=trace_id,
            error=str(exc),
        )
        return JSONResponse(
            status_code=http_status,
            content=error(code, str(exc) or code, trace_id=trace_id),
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        trace_id = get_trace_id()
        code = _STATUS_CODE_TO_DEFAULT_CODE.get(exc.status_code, "ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=error(code, str(exc.detail), trace_id=trace_id),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        trace_id = get_trace_id()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error(
                "VALIDATION_FAILED",
                "Request validation failed",
                trace_id=trace_id,
                details={"errors": exc.errors()},
            ),
        )

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        trace_id = get_trace_id()
        retry_after = getattr(exc, "retry_after", 60)
        return JSONResponse(
            status_code=429,
            content=error(
                "RATE_LIMIT_EXCEEDED",
                "Rate limit exceeded",
                trace_id=trace_id,
                details={"retry_after": retry_after},
            ),
        )

    @app.exception_handler(Exception)
    async def _catch_all_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = get_trace_id()
        logger.error(
            "unhandled_exception",
            trace_id=trace_id,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content=error(
                "INTERNAL_ERROR",
                "An internal server error occurred",
                trace_id=trace_id,
            ),
        )
