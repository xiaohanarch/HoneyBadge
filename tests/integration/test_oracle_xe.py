"""Integration tests against a real Oracle XE instance.

These tests are SKIPPED by default because they require:

1. A running Oracle XE container (``gvenzl/oracle-xe:latest``)
2. The ``oracledb`` Python package installed
3. The ``ORACLE_XE_DSN``, ``ORACLE_XE_USER``, ``ORACLE_XE_PASSWORD``
   environment variables set

To run locally:

    docker run -d --name oracle-xe \\
        -e ORACLE_PASSWORD=oracle \\
        -p 1521:1521 gvenzl/oracle-xe:latest

    export ORACLE_XE_DSN="localhost:1521/XEPDB1"
    export ORACLE_XE_USER="system"
    export ORACLE_XE_PASSWORD="oracle"
    pytest tests/integration/test_oracle_xe.py -v

CI skips these because the Oracle XE image is ~1.5 GB and would
slow the pipeline significantly.
"""

import os
from datetime import datetime
from pathlib import Path

import pytest

ORACLE_XE_DSN = os.environ.get("ORACLE_XE_DSN")
ORACLE_XE_USER = os.environ.get("ORACLE_XE_USER", "system")
ORACLE_XE_PASSWORD = os.environ.get("ORACLE_XE_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ORACLE_XE_DSN or not ORACLE_XE_PASSWORD,
    reason="Oracle XE not configured (set ORACLE_XE_DSN / ORACLE_XE_PASSWORD env vars)",
)


@pytest.fixture
async def oracle_connector():
    """Create and connect an OracleEBSConnector against the XE instance."""
    from honeybadge.etl.connectors.oracle_ebs import OracleEBSConnector

    connector = OracleEBSConnector(
        user=ORACLE_XE_USER,
        password=ORACLE_XE_PASSWORD,
        dsn=ORACLE_XE_DSN,
    )
    await connector.connect()
    yield connector
    await connector.disconnect()


@pytest.mark.asyncio
async def test_health_check(oracle_connector) -> None:
    """SELECT 1 FROM DUAL returns True."""
    assert await oracle_connector.health_check() is True


@pytest.mark.asyncio
async def test_extract_from_test_table(oracle_connector) -> None:
    """Create a temp table, insert a row, extract it via the connector.

    This exercises the full oracledb thin-mode path: connection pool,
    cursor.execute with bind variables, fetchmany, and type conversion.
    """
    # We need a TableMapping registered for the test table. Use a
    # temporary mapping injected into the registry.
    from honeybadge.etl.connectors.base import TableMapping
    from honeybadge.etl.connectors import table_mappings

    test_mapping = TableMapping(
        source_table="TEST_EXTRACT_TBL",
        watermark_column="UPDATED_AT",
        column_mapping={
            "test_id": "ID",
            "test_name": "NAME",
        },
        derived_columns={
            "is_deleted": "CASE WHEN STATUS = 'X' THEN 1 ELSE 0 END",
        },
        source_system="TEST",
    )
    table_mappings.TABLE_MAPPINGS["ods_test_extract"] = test_mapping

    try:
        async with oracle_connector._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "CREATE TABLE TEST_EXTRACT_TBL ("
                    "  ID NUMBER, NAME VARCHAR2(100), "
                    "  STATUS VARCHAR2(1), UPDATED_AT TIMESTAMP)"
                )
                await cur.execute(
                    "INSERT INTO TEST_EXTRACT_TBL VALUES (1, 'alpha', 'A', "
                    "TO_TIMESTAMP('2026-01-01 10:00:00', 'YYYY-MM-DD HH24:MI:SS'))"
                )
                await cur.execute("COMMIT")

        # Full extract (since=None)
        batches = []
        async for batch in oracle_connector.extract("ods_test_extract"):
            batches.append(batch)

        assert len(batches) == 1
        assert len(batches[0]) == 1
        row = batches[0][0]
        assert row["test_id"] == 1
        assert row["test_name"] == "alpha"
        assert row["is_deleted"] is False  # STATUS='A' -> 0 -> False

        # Incremental extract (since = row's updated_at)
        since = datetime(2026, 1, 1, 10, 0, 0)
        batches = []
        async for batch in oracle_connector.extract("ods_test_extract", since=since):
            batches.append(batch)
        # No rows newer than since
        assert batches == []

    finally:
        # Cleanup
        async with oracle_connector._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DROP TABLE TEST_EXTRACT_TBL")
                await cur.execute("COMMIT")
        # Remove the test mapping
        table_mappings.TABLE_MAPPINGS.pop("ods_test_extract", None)


@pytest.mark.asyncio
async def test_get_source_watermark(oracle_connector) -> None:
    """get_source_watermark returns MAX(UPDATED_AT) from the source."""
    from honeybadge.etl.connectors.base import TableMapping
    from honeybadge.etl.connectors import table_mappings

    test_mapping = TableMapping(
        source_table="TEST_WATERMARK_TBL",
        watermark_column="UPDATED_AT",
        column_mapping={"test_id": "ID"},
        source_system="TEST",
    )
    table_mappings.TABLE_MAPPINGS["ods_test_wm"] = test_mapping

    try:
        async with oracle_connector._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "CREATE TABLE TEST_WATERMARK_TBL ("
                    "  ID NUMBER, UPDATED_AT TIMESTAMP)"
                )
                await cur.execute(
                    "INSERT INTO TEST_WATERMARK_TBL VALUES (1, "
                    "TO_TIMESTAMP('2026-03-15 12:00:00', 'YYYY-MM-DD HH24:MI:SS'))"
                )
                await cur.execute("COMMIT")

        wm = await oracle_connector.get_source_watermark("ods_test_wm")
        assert wm is not None
        assert wm.year == 2026 and wm.month == 3 and wm.day == 15

    finally:
        async with oracle_connector._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DROP TABLE TEST_WATERMARK_TBL")
                await cur.execute("COMMIT")
        table_mappings.TABLE_MAPPINGS.pop("ods_test_wm", None)
