"""Unit tests for the ETL scheduler.

Mocks asyncpg and the pipeline runner so tests verify scheduler logic
(batch_id generation, idempotency, stale-run clearing) without a live
database or a full pipeline execution.
"""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from honeybadge.etl.config import ETLConfig, OracleConfig, PipelineSection, SchedulerSection
from honeybadge.etl.scheduler import ETLScheduler


# ── Config helpers ───────────────────────────────────────────────────────────

def make_config() -> ETLConfig:
    return ETLConfig(
        connector_type="csv",
        oracle=OracleConfig(),
        pipeline=PipelineSection(
            postgres_dsn="postgresql://test",
        ),
        scheduler=SchedulerSection(
            cron="0 2 * * *",
            skip_if_running=True,
            stale_timeout_sec=7200,
        ),
    )


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_batch_id_format() -> None:
    """batch_id follows ETL-YYYYMMDD-NNN format."""
    scheduler = ETLScheduler(make_config())

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    # Simulate 0 prior runs -> first run of the day -> NNN=001
    mock_conn.fetchval = AsyncMock(return_value=0)

    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        mock_pool.close = AsyncMock()
        batch_id = await scheduler._generate_batch_id()

    today = datetime.utcnow().strftime("%Y%m%d")
    assert batch_id == f"ETL-{today}-001"


@pytest.mark.asyncio
async def test_generate_batch_id_increments_run_count() -> None:
    """NNN increments based on same-day run count in etl_run_log."""
    scheduler = ETLScheduler(make_config())

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_conn.fetchval = AsyncMock(return_value=3)  # 3 prior runs
    mock_pool.close = AsyncMock()

    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        batch_id = await scheduler._generate_batch_id()

    today = datetime.utcnow().strftime("%Y%m%d")
    assert batch_id == f"ETL-{today}-004"


@pytest.mark.asyncio
async def test_is_run_in_progress_returns_false_when_no_running_row() -> None:
    """No 'running' row -> scheduler proceeds."""
    scheduler = ETLScheduler(make_config())

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_pool.close = AsyncMock()

    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        result = await scheduler._is_run_in_progress()

    assert result is False


@pytest.mark.asyncio
async def test_is_run_in_progress_returns_true_for_active_run() -> None:
    """A fresh 'running' row -> scheduler skips."""
    scheduler = ETLScheduler(make_config())

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_conn.fetchrow = AsyncMock(
        return_value={"batch_id": "ETL-X", "start_time": datetime.utcnow()}
    )
    mock_pool.close = AsyncMock()

    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        result = await scheduler._is_run_in_progress()

    assert result is True


@pytest.mark.asyncio
async def test_is_run_in_progress_clears_stale_run() -> None:
    """A 'running' row older than stale_timeout_sec is cleared and proceeds."""
    scheduler = ETLScheduler(make_config())
    scheduler._config.scheduler.stale_timeout_sec = 100

    stale_time = datetime.utcnow() - timedelta(seconds=200)
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_conn.fetchrow = AsyncMock(
        return_value={"batch_id": "ETL-STALE", "start_time": stale_time}
    )
    mock_conn.execute = AsyncMock()
    mock_pool.close = AsyncMock()

    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        result = await scheduler._is_run_in_progress()

    assert result is False
    # Verify stale run was marked as failed
    stale_updates = [
        call for call in mock_conn.execute.call_args_list
        if call.args and "failed" in str(call.args)
    ]
    assert len(stale_updates) >= 1


@pytest.mark.asyncio
async def test_skips_when_already_running() -> None:
    """run_pipeline_once skips when skip_if_running and a run is in progress."""
    scheduler = ETLScheduler(make_config())

    # Stub _generate_batch_id
    scheduler._generate_batch_id = AsyncMock(return_value="ETL-SKIP-001")  # type: ignore[assignment]
    # Stub _is_run_in_progress -> True
    scheduler._is_run_in_progress = AsyncMock(return_value=True)  # type: ignore[assignment]
    # _record_run_start should NOT be called
    scheduler._record_run_start = AsyncMock()  # type: ignore[assignment]

    batch_id = await scheduler.run_pipeline_once()

    assert batch_id == "ETL-SKIP-001"
    scheduler._record_run_start.assert_not_called()


@pytest.mark.asyncio
async def test_run_pipeline_once_records_start_and_end() -> None:
    """run_pipeline_once records run start, executes, then records end."""
    scheduler = ETLScheduler(make_config())
    scheduler._generate_batch_id = AsyncMock(return_value="ETL-RUN-001")  # type: ignore[assignment]
    scheduler._is_run_in_progress = AsyncMock(return_value=False)  # type: ignore[assignment]
    scheduler._record_run_start = AsyncMock()  # type: ignore[assignment]
    scheduler._record_run_end = AsyncMock()  # type: ignore[assignment]

    # Mock the pipeline runner to avoid importing the full dep chain
    mock_state = MagicMock()
    mock_state.status.value = "success"

    with patch("honeybadge.etl.run_pipeline.ETLPipelineRunner") as mock_runner_cls:
        mock_runner = mock_runner_cls.return_value
        mock_runner.run = AsyncMock(return_value=mock_state)

        batch_id = await scheduler.run_pipeline_once()

    assert batch_id == "ETL-RUN-001"
    scheduler._record_run_start.assert_called_once_with("ETL-RUN-001")
    scheduler._record_run_end.assert_called_once_with("ETL-RUN-001", "success")


@pytest.mark.asyncio
async def test_safe_run_once_swallows_exceptions() -> None:
    """_safe_run_once returns None instead of raising."""
    scheduler = ETLScheduler(make_config())
    scheduler.run_pipeline_once = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[assignment]

    result = await scheduler._safe_run_once()

    assert result is None  # exception swallowed


def test_etl_config_from_yaml_expands_env_vars(tmp_path: Any) -> None:
    """${VAR} tokens in YAML are expanded from the environment."""
    import os
    yaml_content = """
connector:
  type: oracle_ebs
  oracle:
    host: ${ORACLE_HOST}
    password: ${ORACLE_PASSWORD}
pipeline:
  postgres_dsn: ${POSTGRES_DSN}
"""
    config_path = tmp_path / "etl-config.yaml"
    config_path.write_text(yaml_content, encoding="utf-8")

    with patch.dict(os.environ, {
        "ORACLE_HOST": "db.example.com",
        "ORACLE_PASSWORD": "s3cr3t",
        "POSTGRES_DSN": "postgresql://u:p@host/db",
    }):
        config = ETLConfig.from_yaml(config_path)

    assert config.connector_type == "oracle_ebs"
    assert config.oracle.host == "db.example.com"
    assert config.oracle.password == "s3cr3t"
    assert config.pipeline.postgres_dsn == "postgresql://u:p@host/db"


def test_etl_config_from_dict_defaults() -> None:
    """Empty dict yields default config."""
    config = ETLConfig.from_dict({})
    assert config.connector_type == "csv"
    assert config.pipeline.load_mode == "incremental"
    assert config.scheduler.cron == "0 2 * * *"


def test_oracle_config_to_dsn() -> None:
    """OracleConfig.to_dsn() produces host:port/service_name."""
    oracle = OracleConfig(host="db.host", port=1522, service_name="PROD")
    assert oracle.to_dsn() == "db.host:1522/PROD"
