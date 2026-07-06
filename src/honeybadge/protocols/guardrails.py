"""Session-level guardrails for MCP tool calls.

Enforces hard limits that SKILL.md expresses as soft instructions:

* "max 5 investigation rounds" — limits how many times a worker can call
  ``validate_and_execute`` within a single task before being forced to
  proceed to summarization.

These guards are keyed by ``trace_id`` (or ``session_id``) and stored in
Redis when available, falling back to an in-process dict. They are
**defensive limits** — the LLM is expected to self-regulate via SKILL.md,
but if it doesn't, the tool layer blocks the call rather than allowing
unbounded retries.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger()

# Default hard limits (overridable via environment variables)
_MAX_INVESTIGATION_ROUNDS = int(os.environ.get("HONEYBADGE_MAX_INVESTIGATION_ROUNDS", "5"))
_REDIS_KEY_PREFIX = "guardrail:investigation:"

# In-process fallback when Redis is unavailable.
# Keyed by trace_id; values are round counts.
_memory_counters: dict[str, int] = {}


async def check_investigation_round(
    trace_id: str,
    redis: Any = None,
    max_rounds: int | None = None,
) -> tuple[bool, int]:
    """Check and increment the investigation round counter for a trace.

    Returns ``(allowed, current_count)``. When ``current_count >= max_rounds``,
    ``allowed`` is False and the caller should reject the tool call with a
    clear error directing the worker to proceed to summarization.

    Args:
        trace_id: The trace/session identifier for this task.
        redis: Optional Redis client for cross-process counting.
        max_rounds: Override the default max (defaults to env var or 5).

    Returns:
        Tuple of (whether the call is allowed, current round count).
    """
    _max = max_rounds or _MAX_INVESTIGATION_ROUNDS
    if not trace_id:
        return True, 0

    # Try Redis first (cross-process safe)
    if redis is not None:
        try:
            key = f"{_REDIS_KEY_PREFIX}{trace_id}"
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, 600)  # 10-minute TTL
            if current > _max:
                logger.warning(
                    "investigation_round_exceeded",
                    trace_id=trace_id,
                    current=current,
                    max=_max,
                )
                return False, current
            return True, current
        except Exception as e:
            logger.warning("guardrail_redis_failed", error=str(e), fallback="memory")

    # In-process fallback (single-process only)
    current = _memory_counters.get(trace_id, 0) + 1
    _memory_counters[trace_id] = current
    # Opportunistic cleanup of stale entries
    if len(_memory_counters) > 1000:
        _memory_counters.clear()
    if current > _max:
        logger.warning(
            "investigation_round_exceeded",
            trace_id=trace_id,
            current=current,
            max=_max,
        )
        return False, current
    return True, current


def reset_investigation_counter(trace_id: str) -> None:
    """Reset the counter for a trace (call when a task completes)."""
    _memory_counters.pop(trace_id, None)


def get_investigation_rounds(trace_id: str) -> int:
    """Read-only access to the current round count (for observability)."""
    return _memory_counters.get(trace_id, 0)
