"""Unit tests for the Oracle EBS connector.

The ``oracledb`` driver is mocked so tests run without an Oracle
instance. Tests focus on SQL generation, column mapping, watermark
filtering, batch iteration, and type conversion.
"""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from honeybadge.etl.connectors.base import TableMapping
from honeybadge.etl.connectors.oracle_ebs import OracleEBSConnector


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeCursor:
    """Minimal fake async cursor mimicking oracledb's cursor API."""

    def __init__(
        self,
        rows: list[tuple],
        description: list[tuple] | None = None,
        fetchmany_sizes: list[int] | None = None,
    ) -> None:
        self._rows = rows
        self.description = description
        self._fetch_idx = 0
        # If provided, fetchmany returns these sizes; otherwise uses arg.
        self._fetchmany_sizes = fetchmany_sizes

    async def execute(self, sql: str, **params: Any) -> None:
        self._executed_sql = sql
        self._executed_params = params

    async def fetchmany(self, num: int) -> list[tuple]:
        if self._fetchmany_sizes is not None:
            if self._fetch_idx >= len(self._fetchmany_sizes):
                return []
            size = self._fetchmany_sizes[self._fetch_idx]
            self._fetch_idx += 1
            chunk = self._rows[:size]
            self._rows = self._rows[size:]
            return chunk
        chunk = self._rows[:num]
        self._rows = self._rows[num:]
        return chunk

    async def fetchone(self) -> tuple | None:
        if not self._rows:
            return None
        return self._rows.pop(0)

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


class FakeConnection:
    """Fake async connection that yields FakeCursors."""

    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        """Return the cursor directly (it is its own async context manager)."""
        return self._cursor

    async def __aenter__(self) -> "FakeConnection":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


class FakePool:
    """Fake oracledb async connection pool."""

    def __init__(self, connection: FakeConnection) -> None:
        self._conn = connection
        self.closed = False

    def acquire(self) -> FakeConnection:
        return self._conn

    async def close(self) -> None:
        self.closed = True


# ── Tests ────────────────────────────────────────────────────────────────────

def test_build_extract_sql_no_watermark() -> None:
    """Without a watermark, SQL has no WHERE clause but keeps ORDER BY."""
    mapping = TableMapping(
        source_table="PO_HEADERS_ALL",
        watermark_column="LAST_UPDATE_DATE",
        column_mapping={"po_header_id": "PO_HEADER_ID", "po_number": "SEGMENT1"},
        derived_columns={"is_deleted": "CASE WHEN X = 1 THEN 1 ELSE 0 END"},
    )
    sql = OracleEBSConnector._build_extract_sql(mapping, since=None)
    assert "SELECT" in sql
    assert "PO_HEADER_ID AS po_header_id" in sql
    assert "SEGMENT1 AS po_number" in sql
    assert "(CASE WHEN X = 1 THEN 1 ELSE 0 END) AS is_deleted" in sql
    assert "FROM PO_HEADERS_ALL" in sql
    assert "WHERE" not in sql
    assert "ORDER BY LAST_UPDATE_DATE" in sql


def test_build_extract_sql_with_watermark() -> None:
    """With a watermark, SQL adds WHERE watermark > :since."""
    mapping = TableMapping(
        source_table="PO_HEADERS_ALL",
        watermark_column="LAST_UPDATE_DATE",
        column_mapping={"po_header_id": "PO_HEADER_ID"},
    )
    since = datetime(2026, 1, 1)
    sql = OracleEBSConnector._build_extract_sql(mapping, since=since)
    assert "WHERE LAST_UPDATE_DATE > :since" in sql
    assert "ORDER BY LAST_UPDATE_DATE" in sql


def test_row_to_dict_coerces_is_deleted_to_bool() -> None:
    """Integer 0/1 from the derived expression becomes Python bool."""
    mapping = TableMapping(
        source_table="T",
        watermark_column="W",
        column_mapping={"po_header_id": "PO_HEADER_ID"},
        derived_columns={"is_deleted": "CASE WHEN X THEN 1 ELSE 0 END"},
    )
    columns = ["po_header_id", "is_deleted"]
    row = (42, 1)
    result = OracleEBSConnector._row_to_dict(columns, row, mapping)
    assert result["po_header_id"] == 42
    assert result["is_deleted"] is True


def test_row_to_dict_preserves_none_values() -> None:
    mapping = TableMapping(
        source_table="T",
        watermark_column="W",
        column_mapping={"a": "A", "b": "B"},
    )
    columns = ["a", "b"]
    row = (1, None)
    result = OracleEBSConnector._row_to_dict(columns, row, mapping)
    assert result["a"] == 1
    assert result["b"] is None


@pytest.mark.asyncio
async def test_extract_raises_before_connect() -> None:
    """extract() raises RuntimeError if connect() was not called."""
    connector = OracleEBSConnector(user="u", password="p", dsn="h:1521/svc")
    with pytest.raises(RuntimeError, match="before connect"):
        async for _ in connector.extract("ods_purchase_order"):
            pass


@pytest.mark.asyncio
async def test_health_check_returns_false_when_not_connected() -> None:
    connector = OracleEBSConnector(user="u", password="p", dsn="h:1521/svc")
    assert await connector.health_check() is False


@pytest.mark.asyncio
async def test_connect_creates_pool_in_thin_mode() -> None:
    """connect() calls oracledb.create_pool_async with thin=True."""
    import sys
    import types

    # Create a fake oracledb module so the lazy import inside connect() works.
    fake_oracledb = types.ModuleType("oracledb")
    mock_create_pool = AsyncMock()
    fake_oracledb.create_pool_async = mock_create_pool
    original = sys.modules.get("oracledb")
    sys.modules["oracledb"] = fake_oracledb

    try:
        connector = OracleEBSConnector(
            user="u", password="p", dsn="h:1521/svc", min_size=1, max_size=2,
        )
        await connector.connect()
        mock_create_pool.assert_called_once_with(
            user="u", password="p", dsn="h:1521/svc",
            min=1, max=2, thin=True,
        )
    finally:
        if original is not None:
            sys.modules["oracledb"] = original
        else:
            sys.modules.pop("oracledb", None)


@pytest.mark.asyncio
async def test_extract_streams_batches() -> None:
    """extract() yields batches of rows from fetchmany."""
    # Two batches: first 2 rows, then 1 row.
    rows = [
        (1000, 0),
        (1001, 0),
        (1002, 1),
    ]
    description = [("po_header_id",), ("is_deleted",)]
    cursor = FakeCursor(rows, description=description)
    conn = FakeConnection(cursor)
    pool = FakePool(conn)

    connector = OracleEBSConnector(user="u", password="p", dsn="h:1521/svc")
    connector._pool = pool

    batches = []
    async for batch in connector.extract("ods_purchase_order", batch_size=2):
        batches.append(batch)

    assert len(batches) == 2
    assert len(batches[0]) == 2
    assert len(batches[1]) == 1
    assert batches[0][0]["po_header_id"] == 1000
    assert batches[1][0]["is_deleted"] is True


@pytest.mark.asyncio
async def test_extract_with_watermark_passes_bind_var() -> None:
    """When since is provided, execute() receives it as a bind variable."""
    rows = [(1000, 0)]
    cursor = FakeCursor(rows, description=[("po_header_id",), ("is_deleted",)])
    # Track execute calls
    execute_mock = AsyncMock(wraps=cursor.execute)
    cursor.execute = execute_mock  # type: ignore[assignment]
    conn = FakeConnection(cursor)
    pool = FakePool(conn)

    connector = OracleEBSConnector(user="u", password="p", dsn="h:1521/svc")
    connector._pool = pool

    since = datetime(2026, 1, 1)
    batches = []
    async for batch in connector.extract("ods_purchase_order", since=since, batch_size=10):
        batches.append(batch)

    execute_mock.assert_called_once()
    call_kwargs = execute_mock.call_args.kwargs
    assert call_kwargs["since"] == since


@pytest.mark.asyncio
async def test_get_source_watermark_returns_max() -> None:
    """get_source_watermark returns the MAX row from the source."""
    cursor = FakeCursor(
        [(datetime(2026, 3, 15),)],
        description=[("MAX",)],
    )
    conn = FakeConnection(cursor)
    pool = FakePool(conn)

    connector = OracleEBSConnector(user="u", password="p", dsn="h:1521/svc")
    connector._pool = pool

    watermark = await connector.get_source_watermark("ods_purchase_order")
    assert watermark == datetime(2026, 3, 15)


@pytest.mark.asyncio
async def test_get_source_watermark_empty_table_returns_none() -> None:
    """An empty source table returns None."""
    cursor = FakeCursor([(None,)], description=[("MAX",)])
    conn = FakeConnection(cursor)
    pool = FakePool(conn)

    connector = OracleEBSConnector(user="u", password="p", dsn="h:1521/svc")
    connector._pool = pool

    assert await connector.get_source_watermark("ods_purchase_order") is None


@pytest.mark.asyncio
async def test_health_check_returns_true_on_success() -> None:
    """A successful SELECT 1 FROM DUAL returns True."""
    cursor = FakeCursor([(1,)], description=[("DUMMY",)])
    conn = FakeConnection(cursor)
    pool = FakePool(conn)

    connector = OracleEBSConnector(user="u", password="p", dsn="h:1521/svc")
    connector._pool = pool

    assert await connector.health_check() is True


@pytest.mark.asyncio
async def test_disconnect_closes_pool() -> None:
    """disconnect() closes the underlying pool."""
    cursor = FakeCursor([], description=[])
    conn = FakeConnection(cursor)
    pool = FakePool(conn)

    connector = OracleEBSConnector(user="u", password="p", dsn="h:1521/svc")
    connector._pool = pool
    await connector.disconnect()
    assert pool.closed is True
    assert connector._pool is None


@pytest.mark.asyncio
async def test_disconnect_is_safe_when_never_connected() -> None:
    """disconnect() is a no-op when connect() was never called."""
    connector = OracleEBSConnector(user="u", password="p", dsn="h:1521/svc")
    await connector.disconnect()  # must not raise
