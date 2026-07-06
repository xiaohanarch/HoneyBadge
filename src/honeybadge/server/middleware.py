"""Trace ID middleware + request-scoped ContextVar.

Propagates an ``X-Trace-Id`` header through every request and exposes the
current trace id via :func:`get_trace_id` so handlers and exception handlers
can include it in the response envelope without threading the request object
around.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, cast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from honeybadge.core.trace import generate_trace_id, is_valid_trace_id

# Request-scoped trace id. Set by TraceIdMiddleware on every request and reset
# in the finally block so it never leaks across requests.
trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Inject a trace id into every request and response."""

    async def dispatch(
        self, request: Request, call_next: Any
    ) -> Response:
        inbound = request.headers.get("X-Trace-Id", "")
        trace_id = (
            inbound
            if inbound and is_valid_trace_id(inbound)
            else generate_trace_id()
        )
        request.state.trace_id = trace_id
        token = trace_id_ctx.set(trace_id)
        try:
            response = cast(Response, await call_next(request))
        finally:
            trace_id_ctx.reset(token)
        response.headers["X-Trace-Id"] = trace_id
        return response


def get_trace_id() -> str:
    """Return the trace id for the current request scope.

    Returns an empty string when called outside a request.
    """
    return trace_id_ctx.get()
