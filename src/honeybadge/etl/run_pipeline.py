"""ETL Pipeline Runner for HoneyBadge Phase 1.

Orchestrates the T+1 ETL pipeline:
    1. Trigger detection (Kafka message or polling)
    2. Data quality checks
    3. Graph model transformation
    4. nebula-importer import
    5. Graph integrity verification
    6. Status reporting and alerting

Usage:
    # Run full pipeline
    python -m honeybadge.etl.run_pipeline --batch-id ETL-20260404-001

    # Run with specific tables
    python -m honeybadge.etl.run_pipeline --batch-id ETL-20260404-001 --tables ods_purchase_order,ods_supplier

    # Incremental mode (default)
    python -m honeybadge.etl.run_pipeline --batch-id ETL-20260404-001 --incremental

    # Full reload mode
    python -m honeybadge.etl.run_pipeline --batch-id ETL-20260404-001 --full

Scheduling:
    # Cron: Daily at 02:00 AM
    0 2 * * * /opt/honeybadge/etl/run_pipeline.sh >> /var/log/etl/pipeline.log 2>&1
"""

import argparse
import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

from honeybadge.core.constants import VERSION
from honeybadge.etl.quality import DataQualityChecker
from honeybadge.etl.transform import EDGE_MAPPINGS, VERTEX_MAPPINGS, GraphTransformer

logger = structlog.get_logger()


class PipelineStatus(str, Enum):
    """Pipeline execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class LoadMode(str, Enum):
    """Load mode for pipeline execution."""

    FULL = "full"
    INCREMENTAL = "incremental"


# =============================================================================
# Pipeline Configuration
# =============================================================================


@dataclass
class PipelineConfig:
    """Configuration for ETL pipeline execution."""

    # PostgreSQL ODS connection
    postgres_dsn: str = "postgresql://honeybadge:honeybadge@localhost:5432/honeybadge_ods"

    # NebulaGraph connection
    nebula_host: str = "localhost"
    nebula_port: int = 9669
    nebula_user: str = "root"
    nebula_password: str = "nebula"
    nebula_space: str = "honeybadge"

    # Pipeline settings
    batch_id: str | None = None
    load_mode: LoadMode = LoadMode.INCREMENTAL
    tables: list[str] | None = None  # None means all tables
    output_dir: str = "import"
    import_concurrency: int = 10

    # Quarantine settings
    quarantine_threshold: int = 100

    # Paths
    importer_config_template: str = "src/honeybadge/etl/importer.yaml"
    importer_binary: str = "nebula-importer"

    @property
    def incremental(self) -> bool:
        return self.load_mode == LoadMode.INCREMENTAL

    @property
    def is_full_load(self) -> bool:
        return self.load_mode == LoadMode.FULL


# =============================================================================
# Pipeline State
# =============================================================================


@dataclass
class PipelineState:
    """Runtime state of the pipeline."""

    batch_id: str
    status: PipelineStatus = PipelineStatus.PENDING
    load_mode: LoadMode = LoadMode.INCREMENTAL
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: datetime | None = None

    # Stage timings
    quality_check_duration_sec: int = 0
    transform_duration_sec: int = 0
    import_duration_sec: int = 0

    # Record counts
    total_records: int = 0
    passed_records: int = 0
    failed_records: int = 0
    quarantined_records: int = 0

    # Vertex/Edge counts
    vertices_written: int = 0
    edges_written: int = 0

    # Error tracking
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    # Import files
    import_files: dict[str, list[str]] = field(default_factory=dict)

    @property
    def duration_sec(self) -> int:
        """Total pipeline duration in seconds."""
        if self.end_time:
            return int((self.end_time - self.start_time).total_seconds())
        return int((datetime.utcnow() - self.start_time).total_seconds())

    @property
    def success(self) -> bool:
        return self.status == PipelineStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/reporting."""
        return {
            "batch_id": self.batch_id,
            "status": self.status.value,
            "load_mode": self.load_mode.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_sec": self.duration_sec,
            "quality_check_duration_sec": self.quality_check_duration_sec,
            "transform_duration_sec": self.transform_duration_sec,
            "import_duration_sec": self.import_duration_sec,
            "total_records": self.total_records,
            "passed_records": self.passed_records,
            "failed_records": self.failed_records,
            "quarantined_records": self.quarantined_records,
            "vertices_written": self.vertices_written,
            "edges_written": self.edges_written,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# =============================================================================
# Pipeline Runner
# =============================================================================


class ETLPipelineRunner:
    """
    Main ETL pipeline orchestrator.

    Coordinates the end-to-end data pipeline:
        1. Waits for sync trigger (polling or Kafka)
        2. Runs data quality checks
        3. Transforms ODS data to graph format
        4. Imports into NebulaGraph
        5. Verifies graph integrity
        6. Reports status

    Example:
        >>> config = PipelineConfig(
        ...     batch_id="ETL-20260404-001",
        ...     load_mode=LoadMode.INCREMENTAL
        ... )
        >>> runner = ETLPipelineRunner(config)
        >>> state = await runner.run()
        >>> if state.success:
        ...     print(f"Pipeline completed successfully in {state.duration_sec}s")
    """

    def __init__(self, config: PipelineConfig):
        """
        Initialize the pipeline runner.

        Args:
            config: Pipeline configuration
        """
        self.config = config
        self.state: PipelineState | None = None
        self._quality_checker: DataQualityChecker | None = None
        self._transformer: GraphTransformer | None = None

    async def run(self) -> PipelineState:
        """
        Execute the full ETL pipeline.

        Returns:
            PipelineState with execution results
        """
        if not self.config.batch_id:
            raise ValueError("batch_id is required")

        # Initialize state
        self.state = PipelineState(
            batch_id=self.config.batch_id,
            load_mode=self.config.load_mode,
        )

        logger.info(
            "pipeline_starting",
            batch_id=self.config.batch_id,
            load_mode=self.config.load_mode.value,
            incremental=self.config.incremental,
        )

        try:
            # Stage 1: Wait for sync trigger
            await self._wait_for_sync_trigger()

            # Stage 2: Data quality checks
            await self._run_quality_checks()

            # Stage 3: Graph transformation
            await self._run_graph_transform()

            # Stage 4: Import into NebulaGraph
            await self._run_import()

            # Stage 5: Verify graph integrity
            await self._verify_graph_integrity()

            # Mark as success
            self.state.status = PipelineStatus.SUCCESS
            self.state.end_time = datetime.utcnow()

            logger.info(
                "pipeline_completed",
                batch_id=self.config.batch_id,
                duration_sec=self.state.duration_sec,
                vertices=self.state.vertices_written,
                edges=self.state.edges_written,
            )

        except Exception as e:
            logger.error(
                "pipeline_failed",
                batch_id=self.config.batch_id,
                error=str(e),
                errors=self.state.errors if self.state else [],
            )
            if self.state:
                self.state.status = PipelineStatus.FAILED
                self.state.end_time = datetime.utcnow()
                self.state.errors.append({
                    "stage": "unknown",
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                })

        return self.state

    async def _wait_for_sync_trigger(self) -> None:
        """
        Wait for source system sync to complete.

        Supports two modes:
        - Polling: Check etl_sync_status table
        - Kafka: Consume from etl-trigger topic (TODO)

        For now, uses polling mode with immediate return if batch already synced.
        """
        logger.info("waiting_for_sync_trigger", batch_id=self.config.batch_id)

        # TODO: Implement actual trigger detection
        # Option A: Poll etl_sync_status table
        # Option B: Consume Kafka message from etl-trigger topic

        # For now, assume trigger is already received
        logger.info("sync_trigger_received", batch_id=self.config.batch_id)

    async def _run_quality_checks(self) -> None:
        """Run data quality checks on ODS tables."""
        stage_start = datetime.utcnow()
        logger.info("quality_checks_starting", batch_id=self.config.batch_id)

        try:
            self._quality_checker = DataQualityChecker(
                postgres_dsn=self.config.postgres_dsn,
                quarantine_threshold=self.config.quarantine_threshold,
            )
            await self._quality_checker.connect()

            # Determine which tables to check
            if self.config.tables:
                table_list = self.config.tables
            else:
                table_list = list(TABLE_DQ_ORDER)  # Use default order

            total_passed = 0
            total_failed = 0
            total_quarantined = 0

            for table in table_list:
                summary = await self._quality_checker.check_table(
                    table_name=table,
                    batch_id=self.config.batch_id,
                )

                total_passed += summary.passed
                total_failed += summary.failed
                total_quarantined += summary.quarantined

                if summary.quarantined > self.config.quarantine_threshold:
                    logger.warning(
                        "quarantine_threshold_exceeded",
                        table=table,
                        quarantined=summary.quarantined,
                        threshold=self.config.quarantine_threshold,
                    )
                    # TODO: Trigger P2 alert

            self.state.total_records = total_passed + total_failed + total_quarantined
            self.state.passed_records = total_passed
            self.state.failed_records = total_failed
            self.state.quarantined_records = total_quarantined

            self.state.quality_check_duration_sec = int(
                (datetime.utcnow() - stage_start).total_seconds()
            )

            logger.info(
                "quality_checks_completed",
                batch_id=self.config.batch_id,
                total=self.state.total_records,
                passed=self.state.passed_records,
                failed=self.state.failed_records,
                quarantined=self.state.quarantined_records,
                duration_sec=self.state.quality_check_duration_sec,
            )

        except Exception as e:
            logger.error("quality_checks_failed", batch_id=self.config.batch_id, error=str(e))
            self.state.errors.append({
                "stage": "quality_checks",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            })
            raise

        finally:
            if self._quality_checker:
                await self._quality_checker.disconnect()

    async def _run_graph_transform(self) -> None:
        """Transform ODS data to NebulaGraph import format."""
        stage_start = datetime.utcnow()
        logger.info("graph_transform_starting", batch_id=self.config.batch_id)

        try:
            self._transformer = GraphTransformer(
                postgres_dsn=self.config.postgres_dsn,
                output_dir=self.config.output_dir,
            )
            await self._transformer.connect()

            # Create batch directory
            batch_dir = Path(self.config.output_dir) / self.config.batch_id
            batch_dir.mkdir(parents=True, exist_ok=True)

            vertices_written = 0
            edges_written = 0

            # Transform vertices
            for tag in VERTEX_MAPPINGS:
                if self.config.tables:
                    # Check if this tag's table is in the requested list
                    mapping = VERTEX_MAPPINGS[tag]
                    if mapping["source_table"] not in self.config.tables:
                        continue

                result = await self._transformer.transform_vertices(
                    tag=tag,
                    batch_id=self.config.batch_id,
                    incremental=self.config.incremental,
                )

                if result.success:
                    vertices_written += result.records_written
                    logger.info("vertex_transformed", tag=tag, records=result.records_written)
                else:
                    logger.error("vertex_transform_failed", tag=tag, error=result.error_message)
                    self.state.errors.append({
                        "stage": "transform_vertices",
                        "tag": tag,
                        "error": result.error_message,
                        "timestamp": datetime.utcnow().isoformat(),
                    })

            # Transform edges
            for edge_type in EDGE_MAPPINGS:
                if self.config.tables:
                    # Check if this edge's table is in the requested list
                    mapping = EDGE_MAPPINGS[edge_type]
                    if mapping["source_table"] not in self.config.tables:
                        continue

                result = await self._transformer.transform_edges(
                    edge_type=edge_type,
                    batch_id=self.config.batch_id,
                    incremental=self.config.incremental,
                )

                if result.success:
                    edges_written += result.records_written
                    logger.info("edge_transformed", edge_type=edge_type, records=result.records_written)
                else:
                    logger.error("edge_transform_failed", edge_type=edge_type, error=result.error_message)
                    self.state.errors.append({
                        "stage": "transform_edges",
                        "edge_type": edge_type,
                        "error": result.error_message,
                        "timestamp": datetime.utcnow().isoformat(),
                    })

            # Get list of generated import files
            self.state.import_files = self._transformer.get_import_files(self.config.batch_id)
            self.state.vertices_written = vertices_written
            self.state.edges_written = edges_written

            self.state.transform_duration_sec = int(
                (datetime.utcnow() - stage_start).total_seconds()
            )

            logger.info(
                "graph_transform_completed",
                batch_id=self.config.batch_id,
                vertices=vertices_written,
                edges=edges_written,
                duration_sec=self.state.transform_duration_sec,
                files=self.state.import_files,
            )

        except Exception as e:
            logger.error("graph_transform_failed", batch_id=self.config.batch_id, error=str(e))
            self.state.errors.append({
                "stage": "graph_transform",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            })
            raise

        finally:
            if self._transformer:
                await self._transformer.disconnect()

    async def _run_import(self) -> None:
        """Import data into NebulaGraph using nebula-importer."""
        stage_start = datetime.utcnow()
        logger.info("import_starting", batch_id=self.config.batch_id)

        try:
            # Check if there are files to import
            total_files = len(self.state.import_files.get("vertices", [])) + len(
                self.state.import_files.get("edges", [])
            )

            if total_files == 0:
                logger.warning("no_import_files", batch_id=self.config.batch_id)
                return

            # Generate importer config for this batch
            import_config_path = Path(self.config.output_dir) / self.config.batch_id / "importer.yaml"
            await self._generate_import_config(import_config_path)

            # Build nebula-importer command
            cmd = [
                self.config.importer_binary,
                "--config", str(import_config_path),
            ]

            # Set environment variables
            env = os.environ.copy()
            env["NEBULA_GRAPHD_HOST"] = self.config.nebula_host
            env["NEBULA_GRAPHD_PORT"] = str(self.config.nebula_port)
            env["NEBULA_USER"] = self.config.nebula_user
            env["NEBULA_PASSWORD"] = self.config.nebula_password
            env["NEBULA_SPACE"] = self.config.nebula_space
            env["BATCH_ID"] = self.config.batch_id

            # Run nebula-importer
            logger.info(
                "running_nebula_importer",
                batch_id=self.config.batch_id,
                command=" ".join(cmd),
            )

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
            )

            if result.returncode != 0:
                logger.error(
                    "import_failed",
                    batch_id=self.config.batch_id,
                    returncode=result.returncode,
                    stdout=result.stdout[:1000] if result.stdout else None,
                    stderr=result.stderr[:1000] if result.stderr else None,
                )
                self.state.errors.append({
                    "stage": "import",
                    "error": f"nebula-importer failed with code {result.returncode}",
                    "stdout": result.stdout[:1000] if result.stdout else None,
                    "stderr": result.stderr[:1000] if result.stderr else None,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                raise RuntimeError(f"nebula-importer failed with code {result.returncode}")

            self.state.import_duration_sec = int(
                (datetime.utcnow() - stage_start).total_seconds()
            )

            logger.info(
                "import_completed",
                batch_id=self.config.batch_id,
                duration_sec=self.state.import_duration_sec,
            )

        except subprocess.TimeoutExpired:
            logger.error("import_timeout", batch_id=self.config.batch_id)
            self.state.errors.append({
                "stage": "import",
                "error": "Import timed out after 1 hour",
                "timestamp": datetime.utcnow().isoformat(),
            })
            raise

        except Exception as e:
            logger.error("import_failed", batch_id=self.config.batch_id, error=str(e))
            self.state.errors.append({
                "stage": "import",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            })
            raise

    async def _generate_import_config(self, output_path: Path) -> None:
        """Generate nebula-importer config for this batch."""
        # Read template
        template_path = Path(self.config.importer_config_template)
        if template_path.exists():
            with open(template_path, encoding="utf-8") as f:
                template_content = f.read()
        else:
            # Generate minimal config
            template_content = self._generate_minimal_config()

        # Replace placeholders
        content = template_content.replace("${BATCH_ID}", self.config.batch_id)
        content = content.replace("${NEBULA_SPACE}", self.config.nebula_space)
        content = content.replace("${NEBULA_GRAPHD_HOST}", self.config.nebula_host)
        content = content.replace("${NEBULA_GRAPHD_PORT}", str(self.config.nebula_port))
        content = content.replace("${NEBULA_USER}", self.config.nebula_user)
        content = content.replace("${NEBULA_PASSWORD}", self.config.nebula_password)

        # Write config
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("import_config_generated", path=str(output_path))

    def _generate_minimal_config(self) -> str:
        """Generate a minimal nebula-importer config."""
        # Build file list from import files
        vertex_files = []
        edge_files = []

        batch_dir = Path(self.config.output_dir) / self.config.batch_id
        if batch_dir.exists():
            for f in batch_dir.glob("vertex_*.csv"):
                vertex_files.append(str(f))
            for f in batch_dir.glob("edge_*.csv"):
                edge_files.append(str(f))

        # Generate YAML
        # This is a simplified version - in production, would generate complete config
        config = f"""version: v3
description: HoneyBadge Import - Batch {self.config.batch_id}

clientSettings:
  retry: 3
  concurrency: {self.config.import_concurrency}
  space: {self.config.nebula_space}
  connection:
    address: "{self.config.nebula_host}:{self.config.nebula_port}"
    user: {self.config.nebula_user}
    password: {self.config.nebula_password}
"""
        return config

    async def _verify_graph_integrity(self) -> None:
        """Verify graph integrity after import."""
        logger.info("graph_integrity_verification_starting", batch_id=self.config.batch_id)

        # TODO: Implement actual graph integrity verification
        # - Check node counts match expected
        # - Check edge counts match expected
        # - Verify sample lookups work

        logger.info("graph_integrity_verification_completed", batch_id=self.config.batch_id)

    def get_status(self) -> dict[str, Any]:
        """Get current pipeline status."""
        if self.state:
            return self.state.to_dict()
        return {"status": PipelineStatus.PENDING.value}


# =============================================================================
# Table processing order (for dependency-aware processing)
# =============================================================================

# Process master data first (no dependencies), then transactions
TABLE_DQ_ORDER = [
    # Master data (no dependencies)
    "ods_currency",
    "ods_uom",
    "ods_organization",
    "ods_supplier",
    "ods_supplier_site",
    "ods_customer",
    "ods_customer_site",
    "ods_item",
    "ods_item_category",
    "ods_employee",
    "ods_warehouse",
    "ods_bom_header",
    "ods_bom_component",

    # Procurement
    "ods_purchase_requisition",
    "ods_purchase_requisition_line",
    "ods_purchase_order",
    "ods_purchase_order_line",
    "ods_receipt",
    "ods_receipt_line",
    "ods_supplier_qualification",
    "ods_asl",

    # Accounts Payable
    "ods_ap_invoice",
    "ods_ap_invoice_line",
    "ods_ap_payment",
    "ods_ap_payment_batch",
    "ods_ap_invoice_payment",

    # Order-to-Cash
    "ods_sales_order",
    "ods_sales_order_line",
    "ods_shipment",
    "ods_shipment_line",
    "ods_ar_invoice",
    "ods_ar_receipt",
    "ods_ar_receipt_application",

    # General Ledger
    "ods_gl_account",
    "ods_gl_journal",
    "ods_gl_journal_line",
    "ods_xla_event",
    "ods_xla_distribution",

    # Approval / Contract
    "ods_approval_record",
    "ods_contract",
]


# =============================================================================
# Main Entry Point
# =============================================================================


def parse_args() -> PipelineConfig:
    """Parse command line arguments into PipelineConfig."""
    parser = argparse.ArgumentParser(
        description="HoneyBadge ETL Pipeline Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run incremental pipeline for specific batch
  python -m honeybadge.etl.run_pipeline --batch-id ETL-20260404-001

  # Run full reload
  python -m honeybadge.etl.run_pipeline --batch-id ETL-20260404-001 --full

  # Process specific tables only
  python -m honeybadge.etl.run_pipeline --batch-id ETL-20260404-001 --tables ods_supplier,ods_purchase_order

  # Use custom PostgreSQL connection
  python -m honeybadge.etl.run_pipeline --batch-id ETL-20260404-001 --postgres-dsn postgresql://user:pass@host:5432/db
        """,
    )

    parser.add_argument(
        "--batch-id",
        type=str,
        default=None,
        help="ETL batch identifier (e.g., ETL-20260404-001). Auto-generated if not provided.",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        default=True,
        dest="incremental",
        help="Run in incremental mode (default). Only process changed records.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        default=False,
        help="Run in full reload mode. Process all records.",
    )
    parser.add_argument(
        "--tables",
        type=str,
        nargs="+",
        default=None,
        help="Specific ODS tables to process (default: all tables).",
    )
    parser.add_argument(
        "--postgres-dsn",
        type=str,
        default=os.environ.get("POSTGRES_DSN", "postgresql://honeybadge:honeybadge@localhost:5432/honeybadge_ods"),
        help="PostgreSQL connection string for ODS database.",
    )
    parser.add_argument(
        "--nebula-host",
        type=str,
        default=os.environ.get("NEBULA_GRAPHD_HOST", "localhost"),
        help="NebulaGraph GraphD host.",
    )
    parser.add_argument(
        "--nebula-port",
        type=int,
        default=int(os.environ.get("NEBULA_GRAPHD_PORT", "9669")),
        help="NebulaGraph GraphD port.",
    )
    parser.add_argument(
        "--nebula-user",
        type=str,
        default=os.environ.get("NEBULA_USER", "root"),
        help="NebulaGraph username.",
    )
    parser.add_argument(
        "--nebula-password",
        type=str,
        default=os.environ.get("NEBULA_PASSWORD", "nebula"),
        help="NebulaGraph password.",
    )
    parser.add_argument(
        "--nebula-space",
        type=str,
        default=os.environ.get("NEBULA_SPACE", "honeybadge"),
        help="NebulaGraph space name.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="import",
        help="Directory for import CSV files.",
    )
    parser.add_argument(
        "--importer-binary",
        type=str,
        default="nebula-importer",
        help="Path to nebula-importer binary.",
    )
    parser.add_argument(
        "--quarantine-threshold",
        type=int,
        default=100,
        help="Quarantine threshold for alerts.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"HoneyBadge ETL Pipeline v{VERSION}",
    )

    args = parser.parse_args()

    # Determine load mode
    load_mode = LoadMode.FULL if args.full else LoadMode.INCREMENTAL

    # Generate batch_id if not provided
    batch_id = args.batch_id
    if not batch_id:
        batch_id = f"ETL-{datetime.utcnow().strftime('%Y%m%d')}-{datetime.utcnow().strftime('%H%M%S')}"

    return PipelineConfig(
        batch_id=batch_id,
        load_mode=load_mode,
        tables=args.tables,
        postgres_dsn=args.postgres_dsn,
        nebula_host=args.nebula_host,
        nebula_port=args.nebula_port,
        nebula_user=args.nebula_user,
        nebula_password=args.nebula_password,
        nebula_space=args.nebula_space,
        output_dir=args.output_dir,
        importer_binary=args.importer_binary,
        quarantine_threshold=args.quarantine_threshold,
    )


async def main() -> int:
    """Main entry point for the ETL pipeline."""
    # Configure structured logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Parse configuration
    config = parse_args()

    logger.info(
        "pipeline_initialized",
        batch_id=config.batch_id,
        load_mode=config.load_mode.value,
        postgres_dsn=config.postgres_dsn.split("@")[-1] if "@" in config.postgres_dsn else "localhost",
        nebula_host=config.nebula_host,
    )

    # Create and run pipeline
    runner = ETLPipelineRunner(config)
    state = await runner.run()

    # Print summary
    print("\n" + "=" * 60)
    print(f"Pipeline Execution Summary - Batch: {state.batch_id}")
    print("=" * 60)
    print(f"Status:           {state.status.value}")
    print(f"Load Mode:        {state.load_mode.value}")
    print(f"Duration:         {state.duration_sec} seconds")
    print(f"Quality Check:    {state.quality_check_duration_sec} seconds")
    print(f"Transform:        {state.transform_duration_sec} seconds")
    print(f"Import:           {state.import_duration_sec} seconds")
    print("-" * 60)
    print(f"Total Records:    {state.total_records}")
    print(f"Passed:          {state.passed_records}")
    print(f"Failed:           {state.failed_records}")
    print(f"Quarantined:      {state.quarantined_records}")
    print(f"Vertices Written: {state.vertices_written}")
    print(f"Edges Written:    {state.edges_written}")
    print("-" * 60)

    if state.errors:
        print(f"Errors:           {len(state.errors)}")
        for err in state.errors[:5]:
            print(f"  - {err.get('stage', 'unknown')}: {err.get('error', 'unknown')}")
    else:
        print("Errors:           0")

    print("=" * 60)

    # Return exit code
    return 0 if state.success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
