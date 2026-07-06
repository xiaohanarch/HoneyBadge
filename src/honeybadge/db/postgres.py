"""PostgreSQL client for HoneyBadge audit logging."""

import json
from dataclasses import dataclass
from typing import Any

import asyncpg
import structlog

from honeybadge.core.exceptions import PostgreSQLError

logger = structlog.get_logger()


@dataclass
class AuditLogEntry:
    """Audit log entry for PostgreSQL."""

    trace_id: str
    question: str
    cypher: str
    raw_result: dict[str, Any]
    summary: str
    user_id: str
    session_id: str
    execution_time_ms: int
    row_count: int
    error_message: str | None = None
    org_id: int | None = None


class PostgreSQLClient:
    """
    Async client for PostgreSQL audit logging.

    Stores the L5 full-chain audit log as specified in the Anti-Hallucination Framework.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        user: str = "honeybadge",
        password: str = "",
        database: str = "honeybadge_audit",
        min_pool_size: int = 2,
        max_pool_size: int = 10,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Connect to PostgreSQL and create pool."""
        try:
            self._pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
            )
            logger.info(
                "postgres_connected",
                host=self.host,
                port=self.port,
                database=self.database,
            )
        except Exception as e:
            raise PostgreSQLError(f"Failed to connect to PostgreSQL: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from PostgreSQL."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("postgres_disconnected")

    async def init_schema(self) -> None:
        """Initialize audit log and chat session schema."""
        if not self._pool:
            raise PostgreSQLError("Not connected to PostgreSQL")

        async with self._pool.acquire() as conn:
            # audit_logs table (existing)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    trace_id        VARCHAR(64) NOT NULL UNIQUE,
                    question        TEXT NOT NULL,
                    cypher          TEXT NOT NULL,
                    raw_result      JSONB NOT NULL,
                    summary         TEXT,
                    user_id         VARCHAR(64) NOT NULL,
                    session_id      VARCHAR(64) NOT NULL,
                    execution_time_ms INT NOT NULL,
                    row_count       INT NOT NULL,
                    error_message   TEXT,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_trace_id ON audit_logs(trace_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_logs(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_session_id ON audit_logs(session_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at DESC)")

            # Multi-tenancy: add org_id column for tenant-level audit isolation.
            # ALTER TABLE IF NOT EXISTS is idempotent — existing deployments get
            # the column added on the next init_schema() call, with NULL for
            # legacy rows (treated as "unknown org" — filtered out for
            # org-scoped queries but visible to superadmins with org_id=None).
            await conn.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS org_id INT")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_org_id ON audit_logs(org_id)")

            # chat_sessions table (new)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id      VARCHAR(64) PRIMARY KEY,
                    user_id         VARCHAR(64) NOT NULL,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    message_count   INT NOT NULL DEFAULT 0,
                    last_trace_id   VARCHAR(64)
                )
            """)

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_session_user_id ON chat_sessions(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_session_created_at ON chat_sessions(created_at DESC)")

            # chat_messages table (new)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    session_id      VARCHAR(64) NOT NULL REFERENCES chat_sessions(session_id),
                    role            VARCHAR(16) NOT NULL,  -- 'user' or 'assistant'
                    content         TEXT NOT NULL,
                    message_type    VARCHAR(32) NOT NULL,  -- 'text', 'query_result', 'error'
                    metadata        JSONB,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON chat_messages(session_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON chat_messages(created_at)")

        logger.info("postgres_schema_initialized")

    async def write_audit_log(self, entry: AuditLogEntry) -> bool:
        """Write audit log entry (L5 audit trail)."""
        if not self._pool:
            raise PostgreSQLError("Not connected to PostgreSQL")

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_logs (
                        trace_id, question, cypher, raw_result, summary,
                        user_id, session_id, execution_time_ms, row_count, error_message,
                        org_id
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    entry.trace_id,
                    entry.question,
                    entry.cypher,
                    json.dumps(entry.raw_result, ensure_ascii=False, default=str),
                    entry.summary,
                    entry.user_id,
                    entry.session_id,
                    entry.execution_time_ms,
                    entry.row_count,
                    entry.error_message,
                    entry.org_id,
                )

            logger.info(
                "audit_log_written",
                trace_id=entry.trace_id,
                user_id=entry.user_id,
                row_count=entry.row_count,
            )
            return True

        except Exception as e:
            logger.error("audit_log_write_failed", trace_id=entry.trace_id, error=str(e))
            raise PostgreSQLError(f"Failed to write audit log: {e}") from e

    async def get_audit_log(self, trace_id: str) -> dict[str, Any] | None:
        """Get audit log entry by trace_id."""
        if not self._pool:
            raise PostgreSQLError("Not connected to PostgreSQL")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM audit_logs WHERE trace_id = $1",
                trace_id,
            )
            if row:
                return dict(row)
        return None

    async def get_user_audit_logs(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get audit logs for a user."""
        if not self._pool:
            raise PostgreSQLError("Not connected to PostgreSQL")

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM audit_logs
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_id,
                limit,
                offset,
            )
            return [dict(row) for row in rows]

    async def get_session_audit_logs(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Get all audit logs for a session."""
        if not self._pool:
            raise PostgreSQLError("Not connected to PostgreSQL")

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM audit_logs
                WHERE session_id = $1
                ORDER BY created_at ASC
                """,
                session_id,
            )
            return [dict(row) for row in rows]
