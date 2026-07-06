"""Cron-driven ETL scheduler.

Wraps :class:`ETLPipelineRunner` with an ``APScheduler.AsyncIOScheduler``
so the pipeline runs on a cron schedule without an external cron daemon.
Designed to run as a dedicated process (``python -m honeybadge.etl``)
— NOT inside the API server, to keep the ETL blast radius isolated.

Idempotency
-----------
Before each run the scheduler checks ``etl_run_log.status='running'``.
If a run is already in-flight it is skipped (with a stale timeout so a
crashed run doesn't block forever). This makes the scheduler safe to
restart mid-batch.

batch_id generation
-------------------
``ETL-YYYYMMDD-NNN`` where NNN is the zero-padded run index for the day,
derived from the count of same-day entries in ``etl_run_log``. This
keeps batch ids human-readable and sortable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
import structlog

from honeybadge.etl.config import ETLConfig
from honeybadge.etl.run_pipeline import LoadMode, PipelineConfig

logger = structlog.get_logger()


class ETLScheduler:
    """Cron-scheduled wrapper around the ETL pipeline.

    Parameters
    ----------
    config:
        Loaded :class:`ETLConfig` (YAML + env vars).
    """

    def __init__(self, config: ETLConfig) -> None:
        self._config = config
        self._scheduler: Any = None  # apscheduler.AsyncIOScheduler

    async def start(self) -> None:
        """Register the cron job and start the underlying scheduler."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-not-found]
        from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-not-found]

        trigger = CronTrigger.from_crontab(
            self._config.scheduler.cron,
            timezone=self._config.scheduler.timezone,
        )
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._safe_run_once,
            trigger=trigger,
            id="etl_pipeline",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        logger.info(
            "etl_scheduler_started",
            cron=self._config.scheduler.cron,
            timezone=self._config.scheduler.timezone,
        )

    async def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=True)
            self._scheduler = None
            logger.info("etl_scheduler_stopped")

    async def _safe_run_once(self) -> str | None:
        """Run the pipeline once, swallowing exceptions.

        Used as the APScheduler callback so an unhandled error doesn't
        kill the scheduler process.
        """
        try:
            return await self.run_pipeline_once()
        except Exception as exc:
            logger.error("etl_scheduler_run_failed", error=str(exc))
            return None

    async def run_pipeline_once(self) -> str:
        """Execute one pipeline run.

        Returns the batch_id that was processed (whether it ran or was
        skipped). Raises on unrecoverable errors so callers can decide
        retry policy.
        """
        batch_id = await self._generate_batch_id()

        if self._config.scheduler.skip_if_running:
            if await self._is_run_in_progress():
                logger.info("etl_scheduler_skip_running", batch_id=batch_id)
                return batch_id

        # Record run start in etl_run_log so other workers see it.
        await self._record_run_start(batch_id)

        config = PipelineConfig(
            postgres_dsn=self._config.pipeline.postgres_dsn,
            nebula_host=self._config.pipeline.nebula_host,
            nebula_port=self._config.pipeline.nebula_port,
            batch_id=batch_id,
            load_mode=LoadMode(self._config.pipeline.load_mode),
            tables=self._config.pipeline.tables,
            connector_type=self._config.connector_type,
            oracle_dsn=self._config.oracle.to_dsn() if self._config.connector_type == "oracle_ebs" else None,
            csv_dir=self._config.csv.dir if self._config.connector_type == "csv" else None,
            skip_trigger=True,  # scheduler drives extraction itself
        )

        # Import lazily so the scheduler module stays importable in
        # environments where the full pipeline deps (nebula3, etc.)
        # aren't installed.
        from honeybadge.etl.run_pipeline import ETLPipelineRunner

        runner = ETLPipelineRunner(config)
        state = await runner.run()

        await self._record_run_end(batch_id, state.status.value if state else "failed")
        return batch_id

    # ------------------------------------------------------------------ helpers

    async def _generate_batch_id(self) -> str:
        """Generate ``ETL-YYYYMMDD-NNN`` from the day's run count."""
        dsn = self._config.pipeline.postgres_dsn
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        prefix = f"ETL-{today}-"
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
        try:
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM etl_run_log WHERE batch_id LIKE $1",
                    prefix + "%",
                )
            return f"{prefix}{count + 1:03d}"
        finally:
            await pool.close()

    async def _is_run_in_progress(self) -> bool:
        """Return True if a non-stale ``running`` row exists in etl_run_log."""
        dsn = self._config.pipeline.postgres_dsn
        stale_before = datetime.utcnow() - timedelta(
            seconds=self._config.scheduler.stale_timeout_sec
        )
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT batch_id, start_time
                      FROM etl_run_log
                     WHERE status = 'running'
                     ORDER BY start_time DESC
                     LIMIT 1
                    """
                )
            if row is None:
                return False
            # Stale runs (older than stale_timeout_sec) are treated as
            # crashed and cleared so the scheduler can proceed.
            if row["start_time"] < stale_before:
                logger.warning(
                    "etl_scheduler_stale_run_cleared",
                    batch_id=row["batch_id"],
                    start_time=row["start_time"].isoformat(),
                )
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE etl_run_log SET status = 'failed', end_time = NOW() "
                        "WHERE batch_id = $1",
                        row["batch_id"],
                    )
                return False
            return True
        finally:
            await pool.close()

    async def _record_run_start(self, batch_id: str) -> None:
        dsn = self._config.pipeline.postgres_dsn
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO etl_run_log (batch_id, status, load_mode, start_time)
                    VALUES ($1, 'running', $2, NOW())
                    ON CONFLICT (batch_id) DO UPDATE
                        SET status = 'running', start_time = NOW()
                    """,
                    batch_id,
                    self._config.pipeline.load_mode,
                )
        finally:
            await pool.close()

    async def _record_run_end(self, batch_id: str, status: str) -> None:
        dsn = self._config.pipeline.postgres_dsn
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE etl_run_log SET status = $1, end_time = NOW() WHERE batch_id = $2",
                    status,
                    batch_id,
                )
        finally:
            await pool.close()


async def run_scheduler(config_path: str) -> None:
    """Start the scheduler and block until interrupted."""
    config = ETLConfig.from_yaml(config_path)
    scheduler = ETLScheduler(config)
    await scheduler.start()
    try:
        # Block forever; the event loop drives scheduled jobs.
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        await scheduler.stop()


async def run_once(config_path: str) -> str:
    """Run a single pipeline invocation and return the batch_id."""
    config = ETLConfig.from_yaml(config_path)
    scheduler = ETLScheduler(config)
    return await scheduler.run_pipeline_once()
