"""Integration tests for the HoneyBadge ETL pipeline.

Tests the end-to-end flow:
    CSV generation → ODS load → quality checks → graph transform → pipeline

These tests require a running PostgreSQL instance with the ODS schema loaded.
Tests skip gracefully when infrastructure is unavailable.

Run:
    pytest tests/test_etl_pipeline.py -v
    pytest tests/test_etl_pipeline.py -v -k csv_to_ods   # single test
"""

import asyncio
import os
import shutil
import sys
from pathlib import Path

import pytest

# Project root for script paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Default test DSN — matches docker-compose postgres service
TEST_DSN = os.environ.get(
    "POSTGRES_DSN",
    "postgresql://honeybadge:honeybadge123@localhost:5432/honeybadge_ods",
)
TEST_NEBULA_HOST = os.environ.get("NEBULA_GRAPHD_HOST", "localhost")
TEST_NEBULA_PORT = int(os.environ.get("NEBULA_GRAPHD_PORT", "9669"))
TEST_BATCH_ID = "ETL-TEST-001"

# The 9 PTP tables
PTP_TABLES = [
    "ods_organization",
    "ods_supplier",
    "ods_item",
    "ods_purchase_order",
    "ods_purchase_order_line",
    "ods_receipt",
    "ods_receipt_line",
    "ods_ap_invoice",
    "ods_ap_invoice_line",
]

# Expected row counts (approximate — generator uses random)
EXPECTED_COUNTS = {
    "ods_organization": 12,
    "ods_supplier": 50,
    "ods_item": 100,
    "ods_purchase_order": 500,
    "ods_ap_invoice": 100,
}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _can_connect_postgres() -> bool:
    """Check if PostgreSQL ODS is reachable."""
    try:
        import asyncpg
    except ImportError:
        return False
    try:
        loop = asyncio.new_event_loop()
        try:
            conn = loop.run_until_complete(asyncpg.connect(TEST_DSN, timeout=3))
            loop.run_until_complete(conn.close())
        finally:
            loop.close()
        return True
    except Exception:
        return False


def _can_connect_nebula() -> bool:
    """Check if NebulaGraph is reachable."""
    try:
        from nebula3.Config import Config as NebulaConfig
        from nebula3.gclient.net import ConnectionPool
    except ImportError:
        return False
    try:
        config = NebulaConfig()
        config.timeout = 3000
        pool = ConnectionPool()
        ok = pool.init([(TEST_NEBULA_HOST, TEST_NEBULA_PORT)], config)
        if ok:
            pool.close()
        return ok
    except Exception:
        return False


# Skip markers
pytestmark_skip_no_pg = pytest.mark.skipif(
    not _can_connect_postgres(),
    reason="PostgreSQL ODS not reachable (set POSTGRES_DSN env var)",
)
pytestmark_skip_no_nebula = pytest.mark.skipif(
    not _can_connect_nebula(),
    reason="NebulaGraph not reachable",
)


# ── Tests ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def csv_dir(tmp_path_factory):
    """Generate PTP CSV files once per module run."""
    csv_path = tmp_path_factory.mktemp("ptp_csv")
    # Run the CSV generator script
    import subprocess
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "generate_ptp_csv.py"),
            "--output-dir", str(csv_path),
            "--batch-id", TEST_BATCH_ID,
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        pytest.fail(f"CSV generation failed: {result.stderr}")
    return csv_path


@pytest.fixture(scope="module")
def loaded_ods(csv_dir):
    """Load CSV files into ODS PostgreSQL."""
    import subprocess
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "load_csv_to_ods.py"),
            "--csv-dir", str(csv_dir),
            "--batch-id", TEST_BATCH_ID,
            "--postgres-dsn", TEST_DSN,
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        pytest.fail(f"ODS load failed: {result.stderr}")
    return csv_dir


@pytest.mark.asyncio
@pytestmark_skip_no_pg
class TestCsvToOdsLoad:
    """Test CSV → ODS PostgreSQL loading."""

    async def test_all_9_tables_have_data(self, loaded_ods):
        """Verify all 9 PTP tables have rows for the test batch."""
        import asyncpg
        conn = await asyncpg.connect(TEST_DSN)
        try:
            for table in PTP_TABLES:
                count = await conn.fetchval(
                    f'SELECT COUNT(*) FROM "{table}" WHERE etl_batch_id = $1',
                    TEST_BATCH_ID,
                )
                assert count > 0, f"{table} has 0 rows for batch {TEST_BATCH_ID}"
        finally:
            await conn.close()

    async def test_organization_count_matches(self, loaded_ods):
        """Verify ods_organization has exactly 12 rows."""
        import asyncpg
        conn = await asyncpg.connect(TEST_DSN)
        try:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM ods_organization WHERE etl_batch_id = $1",
                TEST_BATCH_ID,
            )
            assert count == 12
        finally:
            await conn.close()

    async def test_supplier_count_matches(self, loaded_ods):
        """Verify ods_supplier has exactly 50 rows."""
        import asyncpg
        conn = await asyncpg.connect(TEST_DSN)
        try:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM ods_supplier WHERE etl_batch_id = $1",
                TEST_BATCH_ID,
            )
            assert count == 50
        finally:
            await conn.close()

    async def test_po_count_matches(self, loaded_ods):
        """Verify ods_purchase_order has exactly 500 rows."""
        import asyncpg
        conn = await asyncpg.connect(TEST_DSN)
        try:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM ods_purchase_order WHERE etl_batch_id = $1",
                TEST_BATCH_ID,
            )
            assert count == 500
        finally:
            await conn.close()

    async def test_intentional_dirty_data_exists(self, loaded_ods):
        """Verify the 5 POs with NULL po_number and 2 suppliers with invalid status."""
        import asyncpg
        conn = await asyncpg.connect(TEST_DSN)
        try:
            # 5 POs with NULL po_number
            null_po_count = await conn.fetchval(
                "SELECT COUNT(*) FROM ods_purchase_order "
                "WHERE etl_batch_id = $1 AND po_number IS NULL OR po_number = ''",
                TEST_BATCH_ID,
            )
            assert null_po_count == 5, f"Expected 5 POs with null/empty po_number, got {null_po_count}"

            # 2 suppliers with invalid status (FROZEN)
            invalid_status = await conn.fetchval(
                "SELECT COUNT(*) FROM ods_supplier "
                "WHERE etl_batch_id = $1 AND status = 'FROZEN'",
                TEST_BATCH_ID,
            )
            assert invalid_status == 2, f"Expected 2 suppliers with FROZEN status, got {invalid_status}"

            # 3 invoices with negative total_amount
            neg_invoices = await conn.fetchval(
                "SELECT COUNT(*) FROM ods_ap_invoice "
                "WHERE etl_batch_id = $1 AND total_amount < 0",
                TEST_BATCH_ID,
            )
            assert neg_invoices == 3, f"Expected 3 invoices with negative amount, got {neg_invoices}"
        finally:
            await conn.close()


@pytest.mark.asyncio
@pytestmark_skip_no_pg
class TestQualityCheck:
    """Test data quality checks."""

    async def test_quality_check_detects_dirty_data(self, loaded_ods):
        """Run quality checks and verify quarantined records are created."""
        from honeybadge.etl.quality import DataQualityChecker
        checker = DataQualityChecker(postgres_dsn=TEST_DSN)
        await checker.connect()
        try:
            # Check the tables with known dirty data
            po_summary = await checker.check_table(
                "ods_purchase_order", TEST_BATCH_ID
            )
            # 5 POs with NULL po_number → should be quarantined
            assert po_summary.failed >= 5, (
                f"Expected >= 5 failed PO records, got {po_summary.failed}"
            )

            supplier_summary = await checker.check_table(
                "ods_supplier", TEST_BATCH_ID
            )
            # 2 suppliers with FROZEN status → warnings (severity WARNING)
            assert supplier_summary.passed_with_warnings >= 1

            invoice_summary = await checker.check_table(
                "ods_ap_invoice", TEST_BATCH_ID
            )
            # 3 invoices with negative total_amount → should be quarantined (CRITICAL)
            assert invoice_summary.failed >= 3, (
                f"Expected >= 3 failed invoice records, got {invoice_summary.failed}"
            )
        finally:
            await checker.disconnect()

    async def test_quarantine_table_has_records(self, loaded_ods):
        """Verify etl_quarantine table has records for the dirty data."""
        import asyncpg
        conn = await asyncpg.connect(TEST_DSN)
        try:
            # Run quality checks first
            from honeybadge.etl.quality import DataQualityChecker
            checker = DataQualityChecker(postgres_dsn=TEST_DSN)
            await checker.connect()
            await checker.check_table("ods_purchase_order", TEST_BATCH_ID)
            await checker.check_table("ods_ap_invoice", TEST_BATCH_ID)
            await checker.disconnect()

            quarantine_count = await conn.fetchval(
                "SELECT COUNT(*) FROM etl_quarantine WHERE batch_id = $1",
                TEST_BATCH_ID,
            )
            assert quarantine_count >= 8, (
                f"Expected >= 8 quarantine records (5 null PO + 3 negative invoice), "
                f"got {quarantine_count}"
            )
        finally:
            await conn.close()


@pytest.mark.asyncio
@pytestmark_skip_no_pg
class TestTransform:
    """Test graph transformation."""

    async def test_transform_generates_vertex_csvs(self, loaded_ods):
        """Verify transform produces CSV files for all PTP vertex tags."""
        import tempfile

        from honeybadge.etl.tag_prop_types import PTP_TAGS
        from honeybadge.etl.transform import VERTEX_MAPPINGS, GraphTransformer
        output_dir = tempfile.mkdtemp(prefix="etl_transform_")
        transformer = GraphTransformer(
            postgres_dsn=TEST_DSN,
            output_dir=output_dir,
        )
        await transformer.connect()
        try:
            batch_id = TEST_BATCH_ID
            vertex_files = []
            for tag in VERTEX_MAPPINGS:
                if tag not in PTP_TAGS:
                    continue
                result = await transformer.transform_vertices(tag, batch_id)
                assert result.success, f"Transform failed for {tag}: {result.error_message}"
                if result.records_written > 0:
                    vertex_files.append(tag)

            # Should have generated vertex CSVs for PTP tags
            assert len(vertex_files) >= 5, (
                f"Expected >= 5 vertex CSVs, got {len(vertex_files)}"
            )
        finally:
            await transformer.disconnect()
            shutil.rmtree(output_dir, ignore_errors=True)

    async def test_transform_generates_edge_csvs(self, loaded_ods):
        """Verify transform produces CSV files for PTP edge types."""
        import tempfile

        from honeybadge.etl.tag_prop_types import PTP_EDGES
        from honeybadge.etl.transform import EDGE_MAPPINGS, GraphTransformer
        output_dir = tempfile.mkdtemp(prefix="etl_transform_")
        transformer = GraphTransformer(
            postgres_dsn=TEST_DSN,
            output_dir=output_dir,
        )
        await transformer.connect()
        try:
            batch_id = TEST_BATCH_ID
            edge_files = []
            for edge_type in EDGE_MAPPINGS:
                if edge_type not in PTP_EDGES:
                    continue
                result = await transformer.transform_edges(edge_type, batch_id)
                assert result.success, f"Transform failed for {edge_type}: {result.error_message}"
                if result.records_written > 0:
                    edge_files.append(edge_type)

            # Should have generated edge CSVs
            assert len(edge_files) >= 3, (
                f"Expected >= 3 edge CSVs, got {len(edge_files)}"
            )
        finally:
            await transformer.disconnect()
            shutil.rmtree(output_dir, ignore_errors=True)


@pytest.mark.asyncio
@pytestmark_skip_no_pg
class TestPipelineRunner:
    """Test the full pipeline runner."""

    async def test_pipeline_generates_config(self, loaded_ods):
        """Verify the pipeline can generate a dynamic importer config."""
        import tempfile

        from honeybadge.etl.run_pipeline import ETLPipelineRunner, LoadMode, PipelineConfig

        output_dir = tempfile.mkdtemp(prefix="etl_pipeline_")
        config = PipelineConfig(
            batch_id=TEST_BATCH_ID,
            load_mode=LoadMode.INCREMENTAL,
            tables=PTP_TABLES,
            postgres_dsn=TEST_DSN,
            output_dir=output_dir,
            skip_trigger=True,
        )
        runner = ETLPipelineRunner(config)

        # Run transform to generate CSV files
        await runner._run_quality_checks()
        await runner._run_graph_transform()

        # Generate importer config
        config_yaml = runner._generate_minimal_config()
        assert "files:" in config_yaml
        assert "Supplier" in config_yaml or "PurchaseOrder" in config_yaml
        assert "vertex_" in config_yaml

        # Verify importer config references actual files
        batch_dir = Path(output_dir) / TEST_BATCH_ID
        assert batch_dir.exists()
        csv_files = list(batch_dir.glob("*.csv"))
        assert len(csv_files) > 0

        # Cleanup
        await runner._quality_checker.disconnect() if runner._quality_checker else None
        shutil.rmtree(output_dir, ignore_errors=True)
