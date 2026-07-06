"""Oracle EBS source connector.

Uses ``oracledb`` in *thin mode* (pure Python, no Oracle Instant Client
required) so the same image works in Docker without a C client install.

The connector keeps an async connection pool (``create_pool_async``) and
streams rows in batches via ``cursor.fetchmany``. All Oracle-native types
are converted to Python natives by the driver itself; we only need to
coerce ``datetime`` watermark values into bind variables and normalise
``is_deleted`` from the integer expression produced by
``TableMapping.derived_columns`` into a Python ``bool`` for the ODS
BOOLEAN column.

Usage
-----
    >>> connector = OracleEBSConnector(
    ...     user="apps", password="...", dsn="host:1521/service")
    >>> await connector.connect()
    >>> async for batch in connector.extract("ods_purchase_order", since=watermark):
    ...     # batch: list[dict] with ODS column keys
    ...     ...
    >>> await connector.disconnect()
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import structlog

from honeybadge.etl.connectors.base import ERPConnector, TableMapping
from honeybadge.etl.connectors.table_mappings import get_mapping

logger = structlog.get_logger()


class OracleEBSConnector(ERPConnector):
    """Async Oracle EBS connector backed by ``oracledb`` thin-mode pools.

    Parameters
    ----------
    user, password, dsn:
        Oracle credentials. ``dsn`` may be ``host:port/service_name``
        or a full EZCONNECT string.
    min_size, max_size:
        Connection-pool size bounds.
    source_system:
        Value recorded in ``ods_*.source_system`` (default ``"EBS"``).
    """

    def __init__(
        self,
        user: str,
        password: str,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 4,
        source_system: str = "EBS",
    ) -> None:
        self._user = user
        self._password = password
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._source_system = source_system
        self._pool: Any = None  # oracledb.AsyncConnectionPool, typed as Any to avoid import-time dep

    async def connect(self) -> None:
        """Create the async connection pool.

        ``oracledb`` is imported lazily so that environments without an
        Oracle backend (CSV-only dev setups) can still import the
        package without the dependency being installed.
        """
        import oracledb

        self._pool = oracledb.create_pool_async(
            user=self._user,
            password=self._password,
            dsn=self._dsn,
            min=self._min_size,
            max=self._max_size,
            thin=True,
        )
        logger.info(
            "oracle_ebs_connected",
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
        )

    async def disconnect(self) -> None:
        """Close the pool. Safe to call even when never connected."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("oracle_ebs_disconnected", dsn=self._dsn)

    async def extract(
        self,
        table: str,
        since: datetime | None = None,
        batch_size: int = 1000,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Stream rows from the source table in batches.

        Builds a parameterised ``SELECT`` from the :class:`TableMapping`,
        appends an optional ``WHERE watermark > :since`` predicate, and
        yields batches of ``{ods_column: value}`` dicts.
        """
        if self._pool is None:
            raise RuntimeError("OracleEBSConnector.extract called before connect()")

        mapping = get_mapping(table)
        sql = self._build_extract_sql(mapping, since)

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                if since is not None:
                    await cur.execute(sql, since=since)
                else:
                    await cur.execute(sql)
                columns = [d[0].lower() for d in cur.description] if cur.description else []

                while True:
                    rows = await cur.fetchmany(batch_size)
                    if not rows:
                        return
                    yield [self._row_to_dict(columns, row, mapping) for row in rows]

    async def get_source_watermark(self, table: str) -> datetime | None:
        """Return ``MAX(watermark_column)`` from the source table."""
        if self._pool is None:
            raise RuntimeError(
                "OracleEBSConnector.get_source_watermark called before connect()"
            )

        mapping = get_mapping(table)
        sql = f"SELECT MAX({mapping.watermark_column}) FROM {mapping.source_table}"

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                row = await cur.fetchone()
                if not row or row[0] is None:
                    return None
                value = row[0]
                if isinstance(value, datetime):
                    return value
                # oracledb may return cx_Oracle.LOB or DATETIME variants;
                # coerce defensively.
                return datetime.fromisoformat(str(value))

    async def health_check(self) -> bool:
        """Return ``True`` iff ``SELECT 1 FROM DUAL`` succeeds."""
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1 FROM DUAL")
                    row = await cur.fetchone()
                    return bool(row and row[0] == 1)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("oracle_ebs_health_check_failed", error=str(exc))
            return False

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _build_extract_sql(mapping: TableMapping, since: datetime | None) -> str:
        """Build the extraction SELECT.

        Uses a bind variable (``:since``) for the watermark predicate so
        that Oracle can reuse the parsed plan across runs and so that
        timestamp values are passed safely without string interpolation.
        """
        select_list = mapping.build_select_list()
        sql = f"SELECT {select_list} FROM {mapping.source_table}"
        if since is not None:
            sql += f" WHERE {mapping.watermark_column} > :since"
        sql += f" ORDER BY {mapping.watermark_column}"
        return sql

    @staticmethod
    def _row_to_dict(
        columns: list[str],
        row: tuple[Any, ...],
        mapping: TableMapping,
    ) -> dict[str, Any]:
        """Convert a driver row tuple into an ODS-column-keyed dict.

        Applies two normalisations:

        * ``is_deleted`` (when present) is coerced to ``bool``. The
          derived-expression in :class:`TableMapping` produces 0/1 which
          the ODS schema stores as BOOLEAN.
        * ``None`` values are preserved (the loader maps them to SQL
          NULL via asyncpg).
        """
        out: dict[str, Any] = {}
        for col_name, value in zip(columns, row, strict=False):
            if col_name == "is_deleted" and value is not None:
                out[col_name] = bool(int(value))
            else:
                out[col_name] = value
        # Ensure every ODS column from the mapping is present even if the
        # driver omitted it (defensive — should not normally happen).
        for ods_col in mapping.ods_columns:
            out.setdefault(ods_col, None)
        return out
