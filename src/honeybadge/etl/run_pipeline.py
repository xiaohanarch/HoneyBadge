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
from honeybadge.db.nebula import NebulaGraphClient
from honeybadge.etl.quality import DataQualityChecker
from honeybadge.etl.tag_prop_types import (
    PTP_EDGES,
    PTP_TAGS,
    get_edge_prop_type,
    get_tag_prop_type,
)
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
    postgres_dsn: str = "postgresql://honeybadge:honeybadge123@localhost:5432/honeybadge_ods"

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

    # Trigger detection
    skip_trigger: bool = False  # Skip sync trigger wait (CSV mode, local dev)
    trigger_poll_interval_sec: int = 5
    trigger_timeout_sec: int = 600

    # Source connector (P3: real ERP extraction)
    connector_type: str = "csv"  # csv | oracle_ebs
    connector_config_path: str | None = None  # path to ETL YAML config
    oracle_dsn: str | None = None  # set when connector_type=oracle_ebs
    csv_dir: str | None = None  # set when connector_type=csv

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
            # Stage 0: Extract from source ERP into ODS (P3)
            await self._run_extract_stage()

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

    async def _run_extract_stage(self) -> None:
        """Stage 0: Extract rows from the source ERP into ODS tables.

        Behaviour by ``connector_type``:

        * ``csv`` with ``skip_trigger=True``: no-op. ODS is assumed to
          already contain data (e.g. loaded by ``load_csv_to_ods.py``).
          This preserves backward compatibility with the CSV dev path.
        * ``oracle_ebs`` (or ``csv`` with explicit ``csv_dir``):
          instantiate :class:`IncrementalLoader` and run
          ``load_all()`` to populate ODS + ``etl_table_sync_status``.

        Failures in this stage are recorded but do NOT abort the
        pipeline — subsequent stages will operate on whatever ODS data
        is available, which is the append-only design's self-healing
        behaviour.
        """
        if self.config.connector_type == "csv" and self.config.skip_trigger and not self.config.csv_dir:
            logger.info(
                "extract_stage_skipped",
                batch_id=self.config.batch_id,
                connector_type=self.config.connector_type,
            )
            return

        # Import lazily so the core pipeline runner stays importable
        # without the new connector/loader deps installed.
        from honeybadge.etl.config import ETLConfig
        from honeybadge.etl.connectors.factory import create_connector
        from honeybadge.etl.incremental_loader import IncrementalLoader

        if self.config.connector_config_path:
            etl_config = ETLConfig.from_yaml(self.config.connector_config_path)
        else:
            # Build a minimal config from PipelineConfig fields.
            etl_config = ETLConfig(
                connector_type=self.config.connector_type,
                csv_dir=self.config.csv_dir or "deploy/test-data/ptp_csv/",
            )

        connector = create_connector(etl_config)
        source_system = "EBS" if self.config.connector_type == "oracle_ebs" else "CSV"
        loader = IncrementalLoader(
            connector=connector,
            postgres_dsn=self.config.postgres_dsn,
            source_system=source_system,
        )

        logger.info(
            "extract_stage_starting",
            batch_id=self.config.batch_id,
            connector_type=self.config.connector_type,
            load_mode=self.config.load_mode.value,
        )

        try:
            await loader.connect()
            results = await loader.load_all(
                batch_id=self.config.batch_id,
                load_mode=self.config.load_mode,
                tables=self.config.tables,
            )

            total_extracted = sum(r.rows_extracted for r in results.values())
            total_loaded = sum(r.rows_loaded for r in results.values())
            failed_tables = [t for t, r in results.items() if r.status == "failed"]

            logger.info(
                "extract_stage_completed",
                batch_id=self.config.batch_id,
                tables=len(results),
                rows_extracted=total_extracted,
                rows_loaded=total_loaded,
                failed_tables=failed_tables,
            )

            if failed_tables:
                self.state.warnings.append({
                    "stage": "extract",
                    "failed_tables": failed_tables,
                    "timestamp": datetime.utcnow().isoformat(),
                })
        except Exception as e:
            logger.error(
                "extract_stage_failed",
                batch_id=self.config.batch_id,
                error=str(e),
            )
            self.state.errors.append({
                "stage": "extract",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            })
            # Do not re-raise: downstream stages proceed with whatever
            # ODS data is available (append-only self-healing).
        finally:
            await loader.disconnect()

    async def _wait_for_sync_trigger(self) -> None:
        """
        Wait for source system sync to complete.

        Supports two modes:
        - Polling: Check etl_sync_status table for status='completed'
        - Skip: When config.skip_trigger is True (CSV mode, local dev)

        Kafka trigger consumption is a Phase 2 concern.
        """
        if self.config.skip_trigger:
            logger.info("sync_trigger_skipped", batch_id=self.config.batch_id)
            return

        logger.info("waiting_for_sync_trigger", batch_id=self.config.batch_id)

        import asyncpg

        pool = await asyncpg.create_pool(self.config.postgres_dsn, min_size=1, max_size=2)
        try:
            elapsed = 0
            while elapsed < self.config.trigger_timeout_sec:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT status FROM etl_sync_status WHERE batch_id = $1",
                        self.config.batch_id,
                    )
                if row and row["status"] == "completed":
                    logger.info("sync_trigger_received", batch_id=self.config.batch_id)
                    return
                await asyncio.sleep(self.config.trigger_poll_interval_sec)
                elapsed += self.config.trigger_poll_interval_sec
            raise TimeoutError(
                f"Sync trigger not received within {self.config.trigger_timeout_sec}s "
                f"for batch {self.config.batch_id}"
            )
        finally:
            await pool.close()

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
        """Import data into NebulaGraph using nebula-importer or Python fallback."""
        stage_start = datetime.utcnow()
        logger.info("import_starting", batch_id=self.config.batch_id)

        try:
            # Check if nebula-importer binary is available — skip gracefully if not
            import shutil

            if not shutil.which(self.config.importer_binary):
                logger.warning(
                    "importer_binary_not_found",
                    binary=self.config.importer_binary,
                    batch_id=self.config.batch_id,
                )
                self.state.warnings.append({
                    "stage": "import",
                    "warning": f"nebula-importer binary '{self.config.importer_binary}' not found; "
                    "CSV files generated, manual import required.",
                })
                return
            # Check if there are files to import
            total_files = len(self.state.import_files.get("vertices", [])) + len(
                self.state.import_files.get("edges", [])
            )

            if total_files == 0:
                logger.warning("no_import_files", batch_id=self.config.batch_id)
                return

            # Try nebula-importer binary first
            import shutil

            binary_found = shutil.which(self.config.importer_binary)
            if binary_found:
                # Generate importer config for this batch
                import_config_path = Path(self.config.output_dir) / self.config.batch_id / "importer.yaml"
                await self._generate_import_config(import_config_path)

                cmd = [
                    self.config.importer_binary,
                    "--config", str(import_config_path),
                ]

                env = os.environ.copy()
                env["NEBULA_GRAPHD_HOST"] = self.config.nebula_host
                env["NEBULA_GRAPHD_PORT"] = str(self.config.nebula_port)
                env["NEBULA_USER"] = self.config.nebula_user
                env["NEBULA_PASSWORD"] = self.config.nebula_password
                env["NEBULA_SPACE"] = self.config.nebula_space
                env["BATCH_ID"] = self.config.batch_id

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
                    timeout=3600,
                )

                if result.returncode == 0:
                    self.state.import_duration_sec = int(
                        (datetime.utcnow() - stage_start).total_seconds()
                    )
                    logger.info(
                        "import_completed",
                        batch_id=self.config.batch_id,
                        duration_sec=self.state.import_duration_sec,
                    )
                    return

                # Binary failed — log and fall through to Python fallback
                logger.warning(
                    "importer_binary_failed",
                    batch_id=self.config.batch_id,
                    returncode=result.returncode,
                    stderr=result.stderr[:500] if result.stderr else None,
                )
                self.state.warnings.append({
                    "stage": "import",
                    "warning": f"nebula-importer binary failed (code {result.returncode}), "
                    "falling back to Python import.",
                })
            else:
                logger.warning(
                    "importer_binary_not_found",
                    binary=self.config.importer_binary,
                    batch_id=self.config.batch_id,
                )
                self.state.warnings.append({
                    "stage": "import",
                    "warning": f"nebula-importer binary '{self.config.importer_binary}' not found; "
                    "using Python import.",
                })

            # Fallback: Python-based import via NebulaGraphClient
            await self._import_via_python()

            self.state.import_duration_sec = int(
                (datetime.utcnow() - stage_start).total_seconds()
            )
            logger.info(
                "import_completed_python",
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

    async def _import_via_python(self) -> None:
        """Import CSV data into NebulaGraph using Python NebulaGraphClient.

        Fallback method when nebula-importer binary is unavailable or fails.
        Reads vertex/edge CSV files and executes INSERT statements in batches.
        """
        import csv as csv_mod

        from honeybadge.db.nebula import NebulaGraphClient
        from honeybadge.etl.tag_prop_types import get_edge_prop_type, get_tag_prop_type

        batch_dir = Path(self.config.output_dir) / self.config.batch_id
        BATCH_SIZE = 50
        total_v = 0
        total_e = 0

        client = NebulaGraphClient(
            host=self.config.nebula_host,
            port=self.config.nebula_port,
            user=self.config.nebula_user,
            password=self.config.nebula_password,
        )
        await client.connect()

        # Import vertex files
        for vfile_path in self.state.import_files.get("vertices", []):
            csv_path = Path(vfile_path)
            tag = csv_path.stem.replace("vertex_", "")
            if not csv_path.exists():
                continue

            with open(csv_path, encoding="utf-8", newline="") as f:
                reader = csv_mod.reader(f)
                header = next(reader)
                # First column is :VID, rest are props
                prop_names = header[1:]

                batch: list[str] = []
                for row in reader:
                    vid = row[0]
                    vals = []
                    for i, val in enumerate(row[1:]):
                        prop_name = prop_names[i] if i < len(prop_names) else ""
                        prop_type = get_tag_prop_type(tag, prop_name)
                        vals.append(self._format_ngql_value(val, prop_type))
                    values_str = ", ".join(vals)
                    batch.append(f'"{vid}":({values_str})')

                    if len(batch) >= BATCH_SIZE:
                        ngql = (
                            f"INSERT VERTEX {tag}({', '.join(prop_names)}) "
                            f"VALUES {', '.join(batch)};"
                        )
                        r = await client.execute(ngql, space=self.config.nebula_space)
                        if not r.success:
                            logger.warning(
                                "vertex_insert_partial_error",
                                tag=tag,
                                error=r.error_message,
                            )
                        total_v += len(batch)
                        batch = []

                if batch:
                    ngql = (
                        f"INSERT VERTEX {tag}({', '.join(prop_names)}) "
                        f"VALUES {', '.join(batch)};"
                    )
                    r = await client.execute(ngql, space=self.config.nebula_space)
                    if not r.success:
                        logger.warning(
                            "vertex_insert_error",
                            tag=tag,
                            error=r.error_message,
                        )
                    total_v += len(batch)

            logger.info("vertex_imported", tag=tag, count=total_v)

        # Import edge files
        for efile_path in self.state.import_files.get("edges", []):
            csv_path = Path(efile_path)
            edge_type = csv_path.stem.replace("edge_", "")
            if not csv_path.exists():
                continue

            with open(csv_path, encoding="utf-8", newline="") as f:
                reader = csv_mod.reader(f)
                header = next(reader)
                # First two columns are :SRC_VID, :DST_VID, rest are props
                prop_names = header[2:]

                batch: list[str] = []
                for row in reader:
                    src_vid = row[0]
                    dst_vid = row[1]
                    vals = []
                    for i, val in enumerate(row[2:]):
                        prop_name = prop_names[i] if i < len(prop_names) else ""
                        prop_type = get_edge_prop_type(edge_type, prop_name)
                        vals.append(self._format_ngql_value(val, prop_type))
                    values_str = ", ".join(vals) if vals else ""
                    batch.append(f'"{src_vid}"->"{dst_vid}":({values_str})')

                    if len(batch) >= BATCH_SIZE:
                        prop_clause = f"({', '.join(prop_names)})" if prop_names else ""
                        ngql = (
                            f"INSERT EDGE {edge_type}{prop_clause} "
                            f"VALUES {', '.join(batch)};"
                        )
                        r = await client.execute(ngql, space=self.config.nebula_space)
                        if not r.success:
                            logger.warning(
                                "edge_insert_partial_error",
                                edge_type=edge_type,
                                error=r.error_message,
                            )
                        total_e += len(batch)
                        batch = []

                if batch:
                    prop_clause = f"({', '.join(prop_names)})" if prop_names else ""
                    ngql = (
                        f"INSERT EDGE {edge_type}{prop_clause} "
                        f"VALUES {', '.join(batch)};"
                    )
                    r = await client.execute(ngql, space=self.config.nebula_space)
                    if not r.success:
                        logger.warning(
                            "edge_insert_error",
                            edge_type=edge_type,
                            error=r.error_message,
                        )
                    total_e += len(batch)

            logger.info("edge_imported", edge_type=edge_type, count=total_e)

        await client.disconnect()
        logger.info(
            "python_import_complete",
            total_vertices=total_v,
            total_edges=total_e,
        )

    @staticmethod
    def _format_ngql_value(val: str, prop_type: str) -> str:
        """Format a CSV string value for nGQL INSERT statement."""
        if val == "" or val is None:
            return "null"
        upper_type = prop_type.upper()
        if upper_type in ("INT", "INT64", "BIGINT", "INTEGER", "INT32"):
            return str(int(float(val)))
        if upper_type in ("DOUBLE", "FLOAT", "DECIMAL"):
            return str(float(val))
        if upper_type == "BOOL":
            return "true" if val.lower() in ("true", "1", "yes") else "false"
        if upper_type == "TIMESTAMP":
            # NebulaGraph TIMESTAMP stores Unix epoch seconds
            from datetime import datetime as _dt
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return str(int(_dt.strptime(val, fmt).timestamp()))
                except ValueError:
                    continue
            # Already a numeric timestamp
            try:
                return str(int(float(val)))
            except ValueError:
                return "null"
        # String types: escape backslashes and double quotes
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

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
        """Generate a complete nebula-importer config dynamically.

        Iterates VERTEX_MAPPINGS and EDGE_MAPPINGS to build the `files`
        section, using tag_prop_types for property type information.
        Only PTP tags/edges are included (controlled by PTP_TAGS / PTP_EDGES).
        """
        batch_dir = Path(self.config.output_dir) / self.config.batch_id

        # Header / client settings
        lines = [
            "version: v2",
            f"description: HoneyBadge Import - Batch {self.config.batch_id}",
            "",
            "clientSettings:",
            "  retry: 3",
            f"  concurrency: {self.config.import_concurrency}",
            f"  space: {self.config.nebula_space}",
            "  connection:",
            f'    address: "{self.config.nebula_host}:{self.config.nebula_port}"',
            f"    user: {self.config.nebula_user}",
            f"    password: {self.config.nebula_password}",
            "",
            f"logPath: {batch_dir.as_posix()}/import.log",
            f"statsPath: {batch_dir.as_posix()}/import-stats.json",
            "",
            "files:",
        ]

        # Vertex files — only for PTP tags
        for tag, mapping in VERTEX_MAPPINGS.items():
            if tag not in PTP_TAGS:
                continue
            vertex_file = batch_dir / f"vertex_{tag}.csv"
            if not vertex_file.exists():
                continue
            props = mapping["properties"]
            lines.append(f"  - path: {vertex_file.name}")
            lines.append("    csv:")
            lines.append("      withHeader: true")
            lines.append('      delimiter: ","')
            lines.append("    tags:")
            lines.append(f"      - name: {tag}")
            lines.append("        id:")
            lines.append("          type: STRING")
            lines.append("        props:")
            for prop_alias in props.keys():
                nebula_type = get_tag_prop_type(tag, prop_alias)
                lines.append(f"          - name: {prop_alias}")
                lines.append(f"            type: {nebula_type}")
            lines.append("")

        # Edge files — only for PTP edges
        for edge_type, mapping in EDGE_MAPPINGS.items():
            if edge_type not in PTP_EDGES:
                continue
            edge_file = batch_dir / f"edge_{edge_type}.csv"
            if not edge_file.exists():
                continue
            props = mapping["properties"]
            lines.append(f"  - path: {edge_file.name}")
            lines.append("    csv:")
            lines.append("      withHeader: true")
            lines.append('      delimiter: ","')
            lines.append("    edges:")
            lines.append(f"      - name: {edge_type}")
            lines.append("        src:")
            lines.append("          type: STRING")
            lines.append("        dst:")
            lines.append("          type: STRING")
            if props:
                lines.append("        props:")
                for prop_alias in props.keys():
                    nebula_type = get_edge_prop_type(edge_type, prop_alias)
                    lines.append(f"          - name: {prop_alias}")
                    lines.append(f"            type: {nebula_type}")
            lines.append("")

        return "\n".join(lines)

    async def _verify_graph_integrity(self) -> None:
        """Verify graph integrity after import.

        Compares vertex counts in NebulaGraph against the number of vertices
        written during the transform stage. If the difference exceeds 5%,
        the pipeline status is downgraded to PARTIAL.
        """
        logger.info("graph_integrity_verification_starting", batch_id=self.config.batch_id)

        try:
            client = NebulaGraphClient(
                host=self.config.nebula_host,
                port=self.config.nebula_port,
                user=self.config.nebula_user,
                password=self.config.nebula_password,
            )
            await client.connect()

            # Submit stats job then read stats
            await client.execute("SUBMIT JOB STATS;", space=self.config.nebula_space)
            # Stats job is async; give it a moment to settle
            await asyncio.sleep(2)
            stats_result = await client.execute("SHOW STATS;", space=self.config.nebula_space)

            if not stats_result.success:
                logger.warning(
                    "graph_stats_unavailable",
                    error=stats_result.error_message,
                )
                return

            # SHOW STATS returns rows: Type | Name | Count
            # Type is "Tag" / "Edge" / "Space"
            tag_counts: dict[str, int] = {}
            edge_counts: dict[str, int] = {}
            for row in stats_result.rows:
                stat_type = str(row.get("Type", ""))
                name = str(row.get("Name", ""))
                count = row.get("Count", 0)
                if stat_type == "Tag":
                    tag_counts[name] = int(count) if count else 0
                elif stat_type == "Edge":
                    edge_counts[name] = int(count) if count else 0

            logger.info(
                "graph_stats",
                tag_counts=tag_counts,
                edge_counts=edge_counts,
            )

            # Compare against expected (from state.vertices_written)
            # We don't have per-tag breakdown in state, so check aggregate.
            total_graph_vertices = sum(tag_counts.values())
            expected = self.state.vertices_written if self.state else 0

            if expected > 0 and total_graph_vertices > 0:
                diff_pct = abs(total_graph_vertices - expected) / expected
                if diff_pct > 0.05:
                    logger.warning(
                        "graph_integrity_partial",
                        expected=expected,
                        actual=total_graph_vertices,
                        diff_pct=f"{diff_pct:.1%}",
                    )
                    if self.state:
                        self.state.status = PipelineStatus.PARTIAL
                        self.state.warnings.append({
                            "stage": "graph_integrity",
                            "expected": expected,
                            "actual": total_graph_vertices,
                            "diff_pct": f"{diff_pct:.1%}",
                        })

            logger.info("graph_integrity_verification_completed", batch_id=self.config.batch_id)

        except Exception as e:
            # Graph integrity verification is non-fatal — log and continue
            logger.warning(
                "graph_integrity_verification_failed",
                batch_id=self.config.batch_id,
                error=str(e),
            )
            if self.state:
                self.state.warnings.append({
                    "stage": "graph_integrity",
                    "error": str(e),
                })

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
        default=os.environ.get("POSTGRES_DSN", "postgresql://honeybadge:honeybadge123@localhost:5432/honeybadge_ods"),
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
        "--skip-trigger",
        action="store_true",
        default=False,
        help="Skip sync trigger wait (CSV mode, local dev).",
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
        skip_trigger=args.skip_trigger,
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
