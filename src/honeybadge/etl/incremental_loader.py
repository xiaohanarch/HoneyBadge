"""Incremental ODS loader.

Drives the *extract* stage of the ETL pipeline: pulls rows from an
:class:`ERPConnector` and writes them into ODS PostgreSQL tables,
recording per-table sync status in ``etl_table_sync_status``.

Design decisions
----------------
* **Append-only, no UPSERT.** ODS tables have no primary key by design;
  each run INSERTs a new ``etl_batch_id`` slice and the transform layer
  filters by ``WHERE etl_batch_id = $1`` (see ``transform.py:1461``).
  Incremental loading therefore means "INSERT new rows with a new
  batch_id", never "update existing rows".
* **Watermark = ``MAX(source_update_time) FROM <ods_table>``.** Self-
  healing: if ODS is reloaded from scratch the watermark becomes NULL
  and the next run naturally does a full extract. No schema migration
  required.
* **Extraction boundary.** At extract start we record the source
  ``SYSTIMESTAMP`` (via ``connector.get_source_watermark`` for CSV, or
  the database clock for Oracle) into
  ``etl_table_sync_status.extraction_cutoff``. The *next* run uses this
  cutoff — not ``MAX(source_update_time)`` — as its ``since`` value, so
  rows updated during extraction are not lost.
* **Idempotency.** Before extracting, we check whether a ``success``
  row already exists for ``(batch_id, table_name)``. If so, the table
  is skipped. This makes re-running a partially-failed batch safe.
* **FULL vs INCREMENTAL.** FULL mode ``TRUNCATE ... CASCADE`` before
  loading and passes ``since=None`` to the connector. INCREMENTAL mode
  preserves existing rows and passes the ODS watermark.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog

from honeybadge.etl.connectors.base import ERPConnector
from honeybadge.etl.connectors.table_mappings import LOAD_ORDER, get_mapping
from honeybadge.etl.run_pipeline import LoadMode

logger = structlog.get_logger()


@dataclass
class TableLoadResult:
    """Outcome of loading a single ODS table."""

    table_name: str
    rows_extracted: int
    rows_loaded: int
    watermark_start: datetime | None
    watermark_end: datetime
    status: str  # success | failed | skipped
    error: str | None = None


class IncrementalLoader:
    """Extract-into-ODS loader driven by an :class:`ERPConnector`.

    Parameters
    ----------
    connector:
        The ERP source connector (Oracle EBS or CSV).
    postgres_dsn:
        DSN for the ODS PostgreSQL database.
    source_system:
        Default ``source_system`` value to record on ODS rows when the
        connector does not supply one (e.g. CSV connector defaults to
        ``"CSV"``).
    """

    def __init__(
        self,
        connector: ERPConnector,
        postgres_dsn: str,
        *,
        source_system: str = "EBS",
    ) -> None:
        self._connector = connector
        self._dsn = postgres_dsn
        self._source_system = source_system
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Create the PostgreSQL pool and ensure the connector is connected."""
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        await self._connector.connect()

    async def disconnect(self) -> None:
        """Close the PostgreSQL pool and the connector."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        await self._connector.disconnect()

    async def load_table(
        self,
        table_name: str,
        batch_id: str,
        load_mode: LoadMode,
    ) -> TableLoadResult:
        """Extract + load a single ODS table.

        Returns a :class:`TableLoadResult` regardless of success or
        failure; failures are recorded in ``etl_table_sync_status`` with
        ``status='failed'`` and surfaced via the ``error`` field.
        """
        if self._pool is None:
            raise RuntimeError("IncrementalLoader.load_table called before connect()")

        mapping = get_mapping(table_name)

        # 1. Idempotency: skip if this batch+table already succeeded.
        existing = await self._pool.fetchval(
            "SELECT status FROM etl_table_sync_status WHERE batch_id = $1 AND table_name = $2",
            batch_id,
            table_name,
        )
        if existing == "success":
            logger.info("loader_skip_already_success", table=table_name, batch_id=batch_id)
            return TableLoadResult(
                table_name=table_name,
                rows_extracted=0,
                rows_loaded=0,
                watermark_start=None,
                watermark_end=datetime.utcnow(),
                status="skipped",
            )

        # 2. Compute watermark.
        watermark_start: datetime | None
        if load_mode == LoadMode.FULL:
            watermark_start = None
        else:
            watermark_start = await self._get_ods_watermark(table_name)

        # 3. Record extraction start (status=extracting).
        sync_id = await self._record_sync_start(
            batch_id=batch_id,
            table_name=table_name,
            watermark_start=watermark_start,
            source_system=mapping.source_system,
        )

        rows_extracted = 0
        rows_loaded = 0
        try:
            # 4. Optionally TRUNCATE for FULL mode.
            if load_mode == LoadMode.FULL:
                async with self._pool.acquire() as conn:
                    await conn.execute(f'TRUNCATE TABLE "{table_name}" CASCADE;')
                logger.info("loader_truncated", table=table_name, load_mode=load_mode.value)

            # 5. Stream-extract from the connector, batch-INSERT into ODS.
            async with self._pool.acquire() as conn:
                async for batch in self._connector.extract(
                    table_name, since=watermark_start
                ):
                    if not batch:
                        continue
                    rows_extracted += len(batch)
                    inserted = await self._insert_batch(
                        conn, table_name, batch_id, batch, mapping.source_system
                    )
                    rows_loaded += inserted

            # 6. Record success.
            watermark_end = datetime.utcnow()
            await self._record_sync_success(
                sync_id=sync_id,
                rows_extracted=rows_extracted,
                rows_loaded=rows_loaded,
            )
            logger.info(
                "loader_table_success",
                table=table_name,
                batch_id=batch_id,
                rows_extracted=rows_extracted,
                rows_loaded=rows_loaded,
            )
            return TableLoadResult(
                table_name=table_name,
                rows_extracted=rows_extracted,
                rows_loaded=rows_loaded,
                watermark_start=watermark_start,
                watermark_end=watermark_end,
                status="success",
            )
        except Exception as exc:
            # Record failure and re-raise so the caller can decide
            # whether to abort the whole batch or continue.
            await self._record_sync_failure(sync_id=sync_id, error=str(exc))
            logger.error(
                "loader_table_failed",
                table=table_name,
                batch_id=batch_id,
                error=str(exc),
            )
            return TableLoadResult(
                table_name=table_name,
                rows_extracted=rows_extracted,
                rows_loaded=rows_loaded,
                watermark_start=watermark_start,
                watermark_end=datetime.utcnow(),
                status="failed",
                error=str(exc),
            )

    async def load_all(
        self,
        batch_id: str,
        load_mode: LoadMode,
        tables: list[str] | None = None,
    ) -> dict[str, TableLoadResult]:
        """Load every table in :data:`LOAD_ORDER` (or the given subset).

        Tables are loaded sequentially in dependency order. A failure in
        one table does NOT abort the others — the batch is "best effort"
        and the caller (scheduler) decides whether to mark the whole
        run as failed based on the aggregate result.
        """
        table_list = tables if tables is not None else list(LOAD_ORDER)
        results: dict[str, TableLoadResult] = {}
        for table in table_list:
            results[table] = await self.load_table(table, batch_id, load_mode)
        return results

    # ------------------------------------------------------------------ helpers

    async def _get_ods_watermark(self, table_name: str) -> datetime | None:
        """Return ``MAX(source_update_time)`` from the ODS table.

        Returns ``None`` when the table is empty or the column is all
        NULL, which causes the connector to do a full extract.
        """
        assert self._pool is not None
        return await self._pool.fetchval(  # type: ignore[no-any-return]
            f'SELECT MAX(source_update_time) FROM "{table_name}"'
        )

    async def _record_sync_start(
        self,
        *,
        batch_id: str,
        table_name: str,
        watermark_start: datetime | None,
        source_system: str,
    ) -> int:
        """Insert an ``extracting`` row into ``etl_table_sync_status``.

        If a row already exists for ``(batch_id, table_name)`` (e.g. a
        previous failed attempt), it is updated in place so the UNIQUE
        constraint is honoured.
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO etl_table_sync_status
                    (batch_id, table_name, source_system, watermark_start,
                     extraction_cutoff, status, started_at)
                VALUES ($1, $2, $3, $4, NOW(), 'extracting', NOW())
                ON CONFLICT (batch_id, table_name) DO UPDATE
                    SET status = 'extracting',
                        watermark_start = EXCLUDED.watermark_start,
                        extraction_cutoff = NOW(),
                        started_at = NOW(),
                        completed_at = NULL,
                        error_message = NULL,
                        rows_extracted = 0,
                        rows_loaded = 0
                RETURNING id
                """,
                batch_id,
                table_name,
                source_system,
                watermark_start,
            )
            return int(row["id"])

    async def _record_sync_success(
        self,
        *,
        sync_id: int,
        rows_extracted: int,
        rows_loaded: int,
    ) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE etl_table_sync_status
                   SET status = 'success',
                       rows_extracted = $1,
                       rows_loaded = $2,
                       completed_at = NOW()
                 WHERE id = $3
                """,
                rows_extracted,
                rows_loaded,
                sync_id,
            )

    async def _record_sync_failure(self, *, sync_id: int, error: str) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE etl_table_sync_status
                   SET status = 'failed',
                       error_message = $1,
                       completed_at = NOW()
                 WHERE id = $2
                """,
                error,
                sync_id,
            )

    async def _insert_batch(
        self,
        conn: asyncpg.Connection,
        table_name: str,
        batch_id: str,
        rows: list[dict[str, Any]],
        source_system: str,
    ) -> int:
        """INSERT a batch of rows into an ODS table.

        Adds ETL metadata columns (``etl_batch_id``, ``etl_load_time``,
        ``source_system``, ``dq_status``) to every row. ``is_deleted``
        defaults to ``False`` when the connector did not populate it.
        """
        if not rows:
            return 0

        # Union of all keys across the batch (some rows may omit
        # nullable columns). Order-stable for executemany.
        columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
        # Ensure ETL metadata columns are present.
        for meta_col in ("etl_batch_id", "source_system"):
            if meta_col not in seen:
                columns.append(meta_col)
                seen.add(meta_col)

        col_list = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))

        now = datetime.utcnow()
        records: list[tuple[Any, ...]] = []
        for row in rows:
            record: list[Any] = []
            for col in columns:
                if col == "etl_batch_id":
                    record.append(batch_id)
                elif col == "source_system":
                    record.append(source_system)
                elif col == "etl_load_time":
                    record.append(now)
                elif col == "dq_status":
                    record.append("pending")
                else:
                    record.append(row.get(col))
            records.append(tuple(record))

        await conn.executemany(
            f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
            records,
        )
        return len(records)
