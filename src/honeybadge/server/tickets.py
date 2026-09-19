"""Short-lived single-use auth tickets for the MCP identity chain.

Why tickets exist: the AgentTeams (openclaw) runtime's Matrix message
mapper forwards only ``content.body`` to the manager agent — custom
event fields such as ``x-hb-auth`` are dropped before the agent ever
sees the message. A cryptographic user identity therefore cannot ride
on the Matrix event itself.

Instead, the frontend exchanges its roles JWT for a short single-use
ticket (``POST /api/auth/ticket``). The ticket id travels inside the
message body; deterministic dispatch scripts extract it and either

- resolve it and pass the full JWT as ``user_context.auth_token``
  (fast-query direct path), or
- pass the ticket id as ``user_context.auth_ticket`` (worker path),
  which the MCP server resolves and verifies itself.

Either way the verified identity comes from JWT claims — a self-reported
``user_id`` is overridden or rejected, never trusted.

The store is in-memory (single-instance deployments); the natural
upgrade path is the existing Redis. Tickets expire after
``TICKET_TTL_SECONDS`` and allow up to ``TICKET_MAX_USES`` resolutions
(one user question triggers several MCP calls).
"""

import os
import secrets
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from honeybadge.server.auth import decode_token
from honeybadge.server.envelope import success
from honeybadge.server.middleware import get_trace_id

router = APIRouter(tags=["auth"])

TICKET_TTL_SECONDS = 600
TICKET_MAX_USES = 20


class TicketStore:
    """In-memory ticket store: TTL-bound, use-count limited.

    A ticket is NOT single-use: one user question legitimately triggers
    several MCP calls (worker investigation rounds, retries, multi-step
    queries). Each resolve decrements the use counter; the ticket dies at
    zero uses or on TTL expiry, whichever comes first. The bearer risk of
    the multi-use window is bounded by the short TTL and by the ticket
    only granting the issuing user's own privileges.
    """

    def __init__(
        self,
        ttl_seconds: int = TICKET_TTL_SECONDS,
        max_uses: int = TICKET_MAX_USES,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_uses = max_uses
        self._tickets: dict[str, tuple[str, float, int]] = {}

    def issue(self, jwt_value: str) -> tuple[str, int]:
        """Store *jwt_value* under a fresh ticket id."""
        now = time.monotonic()
        self._evict(now)
        ticket = secrets.token_urlsafe(12)
        self._tickets[ticket] = (jwt_value, now + self._ttl, self._max_uses)
        return ticket, self._ttl

    def resolve(self, ticket: str) -> str | None:
        """Return the stored JWT for *ticket*, consuming one use.

        None when unknown, expired, or exhausted.
        """
        entry = self._tickets.get(ticket)
        if entry is None:
            return None
        jwt_value, expires_at, uses_left = entry
        now = time.monotonic()
        if now >= expires_at or uses_left <= 0:
            del self._tickets[ticket]
            return None
        if uses_left - 1 <= 0:
            del self._tickets[ticket]
        else:
            self._tickets[ticket] = (jwt_value, expires_at, uses_left - 1)
        return jwt_value

    def _evict(self, now: float) -> None:
        for key in [k for k, (_, exp, _) in self._tickets.items() if now >= exp]:
            del self._tickets[key]


def _get_store(request: Request) -> TicketStore:
    store: TicketStore | None = getattr(request.app.state, "ticket_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Ticket store unavailable")
    return store


@router.post("/api/auth/ticket")
async def issue_ticket(request: Request) -> dict[str, Any]:
    """Exchange the caller's roles JWT for a short single-use ticket.

    The raw bearer token is stored server-side and handed back only to
    internal callers (scripts / MCP servers) presenting the shared
    service token. Accepts both auth-service roles JWTs (iss=
    "honeybadge-auth") and server access tokens — anything with a valid
    signature, unexpired, and carrying a ``username`` claim.
    """
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    raw_token = auth[len("Bearer "):].strip()

    config = request.app.state.config
    claims = decode_token(raw_token, config.jwt_secret)
    if claims is None or not claims.get("username"):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    store = _get_store(request)
    ticket, ttl = store.issue(raw_token)
    return success({"ticket": ticket, "expires_in": ttl}, trace_id=get_trace_id())


@router.get("/api/internal/ticket/{ticket}")
async def resolve_ticket(
    ticket: str,
    request: Request,
    x_hb_service_token: str = Header(default=""),
) -> dict[str, Any]:
    """Resolve a ticket back to the original JWT (internal callers only).

    Requires the ``X-HB-Service-Token`` header to match the
    ``HONEYBADGE_SERVICE_TOKEN`` env var. Fails closed when the env var
    is unset. Each resolve consumes one of the ticket's uses.
    """
    expected = os.environ.get("HONEYBADGE_SERVICE_TOKEN", "")
    if not expected or not secrets.compare_digest(x_hb_service_token, expected):
        raise HTTPException(status_code=403, detail="Valid service token required")

    store = _get_store(request)
    jwt_value = store.resolve(ticket)
    if jwt_value is None:
        raise HTTPException(status_code=404, detail="Unknown, expired, or already-used ticket")
    return success({"token": jwt_value}, trace_id=get_trace_id())
