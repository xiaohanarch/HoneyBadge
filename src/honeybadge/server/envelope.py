"""Unified API response envelope for all HoneyBadge REST endpoints.

Every REST endpoint returns the same shape::

    {
        "success": true,          # bool
        "data": <payload>,         # Any | null
        "error": null,             # ErrorBody | null
        "trace_id": "TRC-..."      # str | null
    }

On failure ``success`` is ``false``, ``data`` is ``null``, and ``error``
contains a machine-readable code plus a safe user-facing message.

``/api/health`` is intentionally exempt (monitoring tools expect a raw shape).
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorBody(BaseModel):
    """Machine-readable error details returned to the client."""

    code: str  # e.g. "VALIDATION_FAILED"
    message: str  # safe user-facing message
    details: dict[str, Any] | None = None


class ApiResponse(BaseModel, Generic[T]):
    """Pydantic model of the unified envelope (for OpenAPI / type checking)."""

    success: bool
    data: T | None = None
    error: ErrorBody | None = None
    trace_id: str | None = None


def success(data: Any, trace_id: str | None = None) -> dict[str, Any]:
    """Build a success envelope dict."""
    return {"success": True, "data": data, "error": None, "trace_id": trace_id}


def error(
    code: str,
    message: str,
    trace_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an error envelope dict."""
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details},
        "trace_id": trace_id,
    }
