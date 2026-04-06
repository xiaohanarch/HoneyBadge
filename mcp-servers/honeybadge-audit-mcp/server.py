"""HoneyBadge Audit Log MCP Server.

L5 audit trail — records the full chain (question -> nGQL -> result -> summary)
for every query. Uses FastMCP and the existing PostgreSQLClient.
"""

import os
import sys
from typing import Optional

# Add src/ to path so we can import honeybadge modules
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_project_root, "src"))

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from honeybadge.db.postgres import AuditLogEntry, PostgreSQLClient

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# FastMCP app
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "honeybadge-audit-mcp",
    instructions="Audit Log MCP Server for HoneyBadge — L5 full-chain audit trail. "
    "Records question -> nGQL -> result -> summary for every query.",
)

# ---------------------------------------------------------------------------
# Lazy singleton (initialized from env vars on first use)
# ---------------------------------------------------------------------------

_pg_client: Optional[PostgreSQLClient] = None


async def _get_pg() -> PostgreSQLClient:
    """Return a connected PostgreSQLClient singleton, initialized from env vars."""
    global _pg_client
    if _pg_client is None:
        _pg_client = PostgreSQLClient(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            user=os.environ.get("POSTGRES_USER", "honeybadge"),
            password=os.environ.get("POSTGRES_PASSWORD", ""),
            database=os.environ.get("POSTGRES_DB", "honeybadge_audit"),
        )
        await _pg_client.connect()
        await _pg_client.init_schema()
        logger.info("postgres_client_initialized")
    return _pg_client


# ---------------------------------------------------------------------------
# Implementation functions (accept explicit dependencies for testability)
# ---------------------------------------------------------------------------


async def write_audit_log_impl(
    pg: PostgreSQLClient,
    trace_id: str,
    question: str,
    ngql: str,
    raw_result: dict,
    summary: str,
    user_id: str = "anonymous",
    session_id: str = "",
    execution_time_ms: int = 0,
    row_count: int = 0,
    error_message: Optional[str] = None,
) -> dict:
    """Write a full-chain audit entry to PostgreSQL."""
    entry = AuditLogEntry(
        trace_id=trace_id,
        question=question,
        cypher=ngql,
        raw_result=raw_result,
        summary=summary,
        user_id=user_id,
        session_id=session_id,
        execution_time_ms=execution_time_ms,
        row_count=row_count,
        error_message=error_message,
    )
    ok = await pg.write_audit_log(entry)
    return {"success": ok, "trace_id": trace_id}


async def get_audit_trail_impl(
    pg: PostgreSQLClient,
    trace_id: str,
) -> Optional[dict]:
    """Retrieve an audit trail entry by trace_id."""
    result = await pg.get_audit_log(trace_id)
    return result


# ---------------------------------------------------------------------------
# MCP Tool wrappers (use lazy singleton)
# ---------------------------------------------------------------------------


@mcp.tool()
async def write_audit_log(
    trace_id: str,
    question: str,
    ngql: str,
    raw_result: dict,
    summary: str,
    user_id: str = "anonymous",
    session_id: str = "",
    execution_time_ms: int = 0,
    row_count: int = 0,
    error_message: Optional[str] = None,
) -> dict:
    """Write a full-chain audit entry (L5 audit trail).

    Records the complete chain: question -> nGQL -> raw result -> summary,
    along with metadata for traceability and compliance.

    Args:
        trace_id: Unique trace identifier for the query.
        question: Original user question.
        ngql: Generated nGQL statement.
        raw_result: Raw query result data.
        summary: LLM-generated summary text.
        user_id: User identifier (default: "anonymous").
        session_id: Session identifier.
        execution_time_ms: Query execution time in milliseconds.
        row_count: Number of rows returned.
        error_message: Error message if the query failed.
    """
    pg = await _get_pg()
    return await write_audit_log_impl(
        pg,
        trace_id=trace_id,
        question=question,
        ngql=ngql,
        raw_result=raw_result,
        summary=summary,
        user_id=user_id,
        session_id=session_id,
        execution_time_ms=execution_time_ms,
        row_count=row_count,
        error_message=error_message,
    )


@mcp.tool()
async def get_audit_trail(trace_id: str) -> dict:
    """Retrieve audit trail by trace_id.

    Returns the full audit log entry including question, nGQL, raw result,
    summary, and all metadata.

    Args:
        trace_id: The trace identifier to look up.
    """
    pg = await _get_pg()
    result = await get_audit_trail_impl(pg, trace_id=trace_id)
    if result is None:
        raise ToolError(f"Audit trail not found for trace_id: {trace_id}")
    return result


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="sse")
