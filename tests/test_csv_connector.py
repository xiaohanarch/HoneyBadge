"""Unit tests for the CSV connector.

Uses small temp-directory fixtures so tests are deterministic and do
not depend on the committed ``deploy/test-data/ptp_csv/`` data.
"""

from datetime import datetime
from pathlib import Path

import pytest

from honeybadge.etl.connectors.csv_connector import CSVConnector


@pytest.fixture
def csv_dir(tmp_path: Path) -> Path:
    """Create a minimal CSV directory with one ODS-shaped table."""
    csv_path = tmp_path / "ods_organization.csv"
    csv_path.write_text(
        "org_id,org_code,org_name,org_type,status,"
        "etl_batch_id,source_system,source_update_time,is_deleted\n"
        "1000,ORG1000,Acme Corp,COMPANY,ACTIVE,"
        "ETL-1,EBS,2026-01-01 10:00:00,false\n"
        "1001,ORG1001,Beta Co,BUSINESS_UNIT,ACTIVE,"
        "ETL-1,EBS,2026-01-02 11:30:00,false\n"
        "1002,ORG1002,Cancelled Ltd,COMPANY,INACTIVE,"
        "ETL-1,EBS,2026-01-03 09:00:00,true\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.asyncio
async def test_csv_connector_extracts_full(csv_dir: Path) -> None:
    """Full extract returns every row from the CSV."""
    connector = CSVConnector(csv_dir)
    await connector.connect()

    batches = []
    async for batch in connector.extract("ods_organization"):
        batches.append(batch)

    # Single batch (3 rows < default batch_size 1000)
    assert len(batches) == 1
    assert len(batches[0]) == 3

    first = batches[0][0]
    assert first["org_id"] == 1000
    assert first["org_code"] == "ORG1000"
    assert first["org_name"] == "Acme Corp"


@pytest.mark.asyncio
async def test_csv_connector_watermark_filters_rows(csv_dir: Path) -> None:
    """The ``since`` watermark excludes rows with source_update_time <= since."""
    connector = CSVConnector(csv_dir)
    await connector.connect()

    # since = Jan 2 11:30 → filters out Jan 1 10:00 AND Jan 2 11:30,
    # leaving only the Jan 3 row.
    since = datetime(2026, 1, 2, 11, 30, 0)
    batches = []
    async for batch in connector.extract("ods_organization", since=since):
        batches.append(batch)

    rows = [row for batch in batches for row in batch]
    # Only the 2026-01-03 row survives the > since filter
    assert len(rows) == 1
    assert rows[0]["org_code"] == "ORG1002"


@pytest.mark.asyncio
async def test_csv_connector_get_source_watermark(csv_dir: Path) -> None:
    """``get_source_watermark`` returns MAX(source_update_time) from the CSV."""
    connector = CSVConnector(csv_dir)
    await connector.connect()

    watermark = await connector.get_source_watermark("ods_organization")
    assert watermark == datetime(2026, 1, 3, 9, 0, 0)


@pytest.mark.asyncio
async def test_csv_connector_get_source_watermark_missing_file(tmp_path: Path) -> None:
    """Missing CSV file returns None watermark (not an error)."""
    connector = CSVConnector(tmp_path)
    await connector.connect()
    assert await connector.get_source_watermark("nonexistent") is None


@pytest.mark.asyncio
async def test_csv_connector_health_check(csv_dir: Path) -> None:
    """health_check returns True for a readable directory."""
    connector = CSVConnector(csv_dir)
    assert await connector.health_check() is True


@pytest.mark.asyncio
async def test_csv_connector_health_check_missing_dir(tmp_path: Path) -> None:
    """health_check returns False for a non-existent directory."""
    connector = CSVConnector(tmp_path / "does_not_exist")
    assert await connector.health_check() is False


@pytest.mark.asyncio
async def test_csv_connector_connect_rejects_missing_dir(tmp_path: Path) -> None:
    """connect() raises FileNotFoundError for a non-existent directory."""
    connector = CSVConnector(tmp_path / "does_not_exist")
    with pytest.raises(FileNotFoundError):
        await connector.connect()


@pytest.mark.asyncio
async def test_csv_connector_is_deleted_coerced_to_bool(csv_dir: Path) -> None:
    """``is_deleted`` string values become Python bools."""
    connector = CSVConnector(csv_dir)
    await connector.connect()

    batches = []
    async for batch in connector.extract("ods_organization"):
        batches.append(batch)

    rows = [row for batch in batches for row in batch]
    deleted_flags = {row["org_code"]: row["is_deleted"] for row in rows}
    assert deleted_flags["ORG1000"] is False
    assert deleted_flags["ORG1002"] is True


@pytest.mark.asyncio
async def test_csv_connector_batch_size_splits(csv_dir: Path) -> None:
    """Small batch_size yields multiple batches."""
    connector = CSVConnector(csv_dir)
    await connector.connect()

    batches = []
    async for batch in connector.extract("ods_organization", batch_size=2):
        batches.append(batch)

    assert len(batches) == 2
    assert len(batches[0]) == 2
    assert len(batches[1]) == 1


@pytest.mark.asyncio
async def test_csv_connector_missing_table_yields_nothing(tmp_path: Path) -> None:
    """Extracting a table with no CSV file yields no batches (no error)."""
    connector = CSVConnector(tmp_path)
    await connector.connect()

    batches = []
    async for batch in connector.extract("ods_nonexistent"):
        batches.append(batch)
    assert batches == []


@pytest.mark.asyncio
async def test_csv_connector_disconnect_is_noop(csv_dir: Path) -> None:
    """disconnect() is safe to call even without a pool."""
    connector = CSVConnector(csv_dir)
    await connector.connect()
    await connector.disconnect()  # must not raise
