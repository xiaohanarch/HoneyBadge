"""Unit tests for the IncrementalLoader.

The PostgreSQL pool is mocked so these tests run without a live
database. They verify:

* FULL vs INCREMENTAL mode behaviour (TRUNCATE + since=None vs no TRUNCATE + watermark)
* Per-table sync status recording
* Idempotency (skip on prior success)
* First-run full extract (NULL watermark -> since=None)
* Batch INSERT with ETL metadata columns
"""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from honeybadge.etl.connectors.base import ERPConnector
from honeybadge.etl.incremental_loader import IncrementalLoader, TableLoadResult
from honeybadge.etl.run_pipeline import LoadMode


# ── Test fixtures ────────────────────────────────────────────────────────────

class FakeConnector(ERPConnector):
    """In-memory connector that yields a fixed set of rows."""

    def __init__(self, rows: list[dict[str, Any]], source_system: str = "EBS") -> None:
        self._rows = rows
        self._source_system = source_system
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def extract(self, table, since=None, batch_size=1000):  # type: ignore[override]
        # Simulate watermark filtering: if since is set, only return rows
        # whose source_update_time > since.
        for row in self._rows:
            if since is not None:
                ts = row.get("source_update_time")
                if isinstance(ts, datetime) and ts <= since:
                    continue
            yield [row]

    async def get_source_watermark(self, table: str) -> datetime | None:
        timestamps = [
            r["source_update_time"] for r in self._rows
            if isinstance(r.get("source_update_time"), datetime)
        ]
        return max(timestamps) if timestamps else None

    async def health_check(self) -> bool:
        return True


class FakePool:
    """Minimal asyncpg.Pool mock for the loader.

    asyncpg.Pool exposes convenience methods (fetchval, fetchrow) that
    acquire a connection internally. We mirror that so the loader code
    can call either pool.fetchval() or async with pool.acquire() as conn.
    """

    def __init__(self) -> None:
        self._conn = FakeConn()
        self.closed = False

    def acquire(self) -> "FakeConn":
        return self._conn

    async def fetchval(self, sql: str, *args: Any) -> Any:
        return await self._conn.fetchval(sql, *args)

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        return await self._conn.fetchrow(sql, *args)

    async def close(self) -> None:
        self.closed = True

    @property
    def conn(self) -> "FakeConn":
        return self._conn


class FakeConn:
    """Minimal asyncpg.Connection mock."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.fetchval_result: Any = None
        self.fetchrow_result: Any = None

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        return "OK"

    async def executemany(self, sql: str, records: list[tuple]) -> None:
        self.executed.append((sql, ("executemany", len(records))))  # type: ignore[arg-type]

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.executed.append((sql, args))
        return self.fetchval_result

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.executed.append((sql, args))
        return self.fetchrow_result

    async def __aenter__(self) -> "FakeConn":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


@pytest.fixture
def fake_pool() -> FakePool:
    return FakePool()


@pytest.fixture
def loader(fake_pool: FakePool) -> IncrementalLoader:
    connector = FakeConnector(
        rows=[
            {
                "po_header_id": 1000,
                "po_number": "PO-001",
                "source_update_time": datetime(2026, 1, 15, 10, 0, 0),
            },
        ],
        source_system="EBS",
    )
    ld = IncrementalLoader(connector, "postgresql://test", source_system="EBS")
    ld._pool = fake_pool  # type: ignore[assignment]
    ld._connector = connector  # already connected
    # Default: INSERT ... RETURNING yields id=1; no prior success row.
    fake_pool.conn.fetchrow_result = {"id": 1}
    fake_pool.conn.fetchval_result = None
    return ld


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_mode_truncates_and_passes_none_watermark(loader: IncrementalLoader, fake_pool: FakePool) -> None:
    """FULL mode: TRUNCATE executed; since=None passed to connector."""
    # No prior sync status -> proceeds
    fake_pool.conn.fetchval_result = None  # no existing success row

    result = await loader.load_table(
        "ods_purchase_order", "ETL-TEST-001", LoadMode.FULL,
    )

    assert result.status == "success"
    assert result.rows_loaded == 1
    assert result.watermark_start is None  # FULL -> no watermark

    # TRUNCATE should be in executed SQL
    truncate_sqls = [s for s, _ in fake_pool.conn.executed if "TRUNCATE" in s]
    assert len(truncate_sqls) == 1
    assert "ods_purchase_order" in truncate_sqls[0]


@pytest.mark.asyncio
async def test_incremental_mode_uses_ods_watermark(loader: IncrementalLoader, fake_pool: FakePool) -> None:
    """INCREMENTAL mode: no TRUNCATE; since = ODS MAX(source_update_time)."""
    fake_pool.conn.fetchval_result = None  # no existing success row

    # Patch _get_ods_watermark to return a fixed value
    ods_watermark = datetime(2026, 1, 10)
    loader._get_ods_watermark = AsyncMock(return_value=ods_watermark)  # type: ignore[assignment]

    result = await loader.load_table(
        "ods_purchase_order", "ETL-TEST-001", LoadMode.INCREMENTAL,
    )

    assert result.status == "success"
    assert result.watermark_start == ods_watermark

    # No TRUNCATE should run
    truncate_sqls = [s for s, _ in fake_pool.conn.executed if "TRUNCATE" in s]
    assert len(truncate_sqls) == 0


@pytest.mark.asyncio
async def test_incremental_first_run_full_extract(loader: IncrementalLoader, fake_pool: FakePool) -> None:
    """First run (NULL watermark) does a full extract via since=None."""
    fake_pool.conn.fetchval_result = None  # no existing success row

    # _get_ods_watermark returns None (empty ODS table)
    loader._get_ods_watermark = AsyncMock(return_value=None)  # type: ignore[assignment]

    result = await loader.load_table(
        "ods_purchase_order", "ETL-TEST-001", LoadMode.INCREMENTAL,
    )

    assert result.status == "success"
    assert result.watermark_start is None  # no prior data -> full extract
    assert result.rows_loaded == 1


@pytest.mark.asyncio
async def test_skips_when_already_success(loader: IncrementalLoader, fake_pool: FakePool) -> None:
    """Idempotency: skip when etl_table_sync_status already has 'success'."""
    fake_pool.conn.fetchval_result = "success"  # existing success row

    result = await loader.load_table(
        "ods_purchase_order", "ETL-TEST-001", LoadMode.INCREMENTAL,
    )

    assert result.status == "skipped"
    assert result.rows_extracted == 0
    assert result.rows_loaded == 0


@pytest.mark.asyncio
async def test_records_sync_status_on_success(loader: IncrementalLoader, fake_pool: FakePool) -> None:
    """Successful load records extracting -> success in etl_table_sync_status."""
    fake_pool.conn.fetchval_result = None  # no existing success row

    # fetchrow returns an id for the INSERT ... RETURNING
    fake_pool.conn.fetchrow_result = {"id": 42}

    await loader.load_table(
        "ods_purchase_order", "ETL-TEST-001", LoadMode.FULL,
    )

    # Should have an INSERT into etl_table_sync_status + an UPDATE to success
    sync_inserts = [
        s for s, _ in fake_pool.conn.executed
        if "INSERT INTO etl_table_sync_status" in s
    ]
    sync_updates = [
        s for s, _ in fake_pool.conn.executed
        if "UPDATE etl_table_sync_status" in s and "success" in s.lower()
    ]
    assert len(sync_inserts) >= 1
    assert len(sync_updates) >= 1


@pytest.mark.asyncio
async def test_records_failure_on_exception(loader: IncrementalLoader, fake_pool: FakePool) -> None:
    """When extract raises, sync status is recorded as 'failed'."""
    fake_pool.conn.fetchval_result = None  # no existing success row
    fake_pool.conn.fetchrow_result = {"id": 99}

    # Make the connector raise during extract
    original_extract = loader._connector.extract

    async def failing_extract(*args: Any, **kwargs: Any):  # type: ignore[override]
        raise ConnectionError("Oracle gone")
        yield  # pragma: no cover - unreachable, satisfies async generator

    loader._connector.extract = failing_extract  # type: ignore[assignment]

    result = await loader.load_table(
        "ods_purchase_order", "ETL-TEST-001", LoadMode.FULL,
    )

    assert result.status == "failed"
    assert result.error is not None
    assert "Oracle gone" in result.error

    # Verify failure was recorded
    fail_updates = [
        s for s, _ in fake_pool.conn.executed
        if "UPDATE etl_table_sync_status" in s and "failed" in s.lower()
    ]
    assert len(fail_updates) >= 1


@pytest.mark.asyncio
async def test_insert_batch_adds_etl_metadata(loader: IncrementalLoader, fake_pool: FakePool) -> None:
    """_insert_batch adds etl_batch_id and source_system to every row."""
    rows = [
        {"po_header_id": 1000, "po_number": "PO-001"},
        {"po_header_id": 1001, "po_number": "PO-002"},
    ]
    fake_pool.conn.executed.clear()

    count = await loader._insert_batch(
        fake_pool.conn, "ods_purchase_order", "ETL-B1", rows, "EBS",
    )

    assert count == 2
    # executemany should have been called once
    executemany_calls = [
        s for s, _ in fake_pool.conn.executed if "INSERT INTO" in s
    ]
    assert len(executemany_calls) == 1
    assert "ods_purchase_order" in executemany_calls[0]
    assert "etl_batch_id" in executemany_calls[0]
    assert "source_system" in executemany_calls[0]


@pytest.mark.asyncio
async def test_insert_batch_empty_rows_returns_zero(loader: IncrementalLoader) -> None:
    """Empty batch is a no-op."""
    conn = FakeConn()
    count = await loader._insert_batch(conn, "ods_purchase_order", "ETL-B1", [], "EBS")
    assert count == 0
    assert conn.executed == []


@pytest.mark.asyncio
async def test_load_all_respects_table_order(loader: IncrementalLoader, fake_pool: FakePool) -> None:
    """load_all iterates tables in LOAD_ORDER when no subset given."""
    fake_pool.conn.fetchval_result = None
    fake_pool.conn.fetchrow_result = {"id": 1}

    # Use a small subset to keep the test fast
    results = await loader.load_all(
        "ETL-TEST-001", LoadMode.FULL, tables=["ods_organization", "ods_supplier"],
    )

    assert set(results.keys()) == {"ods_organization", "ods_supplier"}
    for r in results.values():
        assert r.status == "success"


@pytest.mark.asyncio
async def test_load_all_continues_after_table_failure(loader: IncrementalLoader, fake_pool: FakePool) -> None:
    """A failure in one table does not abort the rest of the batch."""
    fake_pool.conn.fetchval_result = None
    fake_pool.conn.fetchrow_result = {"id": 1}

    # Make the first table fail
    call_count = {"n": 0}
    original_load_table = loader.load_table

    async def flaky_load(table_name: str, batch_id: str, load_mode: Any) -> TableLoadResult:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return TableLoadResult(
                table_name=table_name,
                rows_extracted=0,
                rows_loaded=0,
                watermark_start=None,
                watermark_end=datetime.utcnow(),
                status="failed",
                error="simulated",
            )
        return await original_load_table(table_name, batch_id, load_mode)

    loader.load_table = flaky_load  # type: ignore[assignment]

    results = await loader.load_all(
        "ETL-TEST-001", LoadMode.FULL,
        tables=["ods_organization", "ods_supplier"],
    )

    assert results["ods_organization"].status == "failed"
    assert results["ods_supplier"].status == "success"


@pytest.mark.asyncio
async def test_connect_creates_pool_and_connects_connector() -> None:
    """connect() creates the asyncpg pool and connects the connector."""
    connector = FakeConnector(rows=[], source_system="EBS")
    loader = IncrementalLoader(connector, "postgresql://test", source_system="EBS")

    with patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
        mock_pool = MagicMock()
        mock_create.return_value = mock_pool
        await loader.connect()

        mock_create.assert_called_once_with("postgresql://test", min_size=1, max_size=4)
        assert loader._pool is mock_pool
        assert connector.connected is True


@pytest.mark.asyncio
async def test_disconnect_closes_pool_and_connector() -> None:
    """disconnect() closes both the pool and the connector."""
    connector = FakeConnector(rows=[], source_system="EBS")
    loader = IncrementalLoader(connector, "postgresql://test", source_system="EBS")

    pool = FakePool()
    loader._pool = pool  # type: ignore[assignment]
    connector.connected = True

    await loader.disconnect()

    assert pool.closed is True
    assert loader._pool is None
    assert connector.connected is False
