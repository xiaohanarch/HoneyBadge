"""CSV-backed ERP connector.

Reads ODS-shaped CSV files from a directory on disk. Used for:

* Local development without an Oracle EBS instance
* Tests / fixtures
* Backward compatibility with ``scripts/load_csv_to_ods.py`` behaviour
  (when ``connector_type=csv`` the incremental loader falls back to
  reading pre-staged CSVs instead of connecting to a real ERP)

CSV contract
------------
Each file is named ``<ods_table>.csv`` and must include a header row
whose column names match the ODS business columns. ETL metadata columns
(``etl_batch_id``, ``etl_load_time``, ``source_system``,
``source_update_time``, ``is_deleted``, ``dq_status``, ``dq_errors``)
are optional; when present they are preserved, otherwise the loader
fills them in.

The connector honours the ``source_update_time`` column for watermark
calculations so the incremental path can be exercised against CSVs
that emulate ERP updates.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import structlog

from honeybadge.etl.connectors.base import ERPConnector

logger = structlog.get_logger()


class CSVConnector(ERPConnector):
    """Read ODS-shaped CSV files from a local directory.

    Parameters
    ----------
    csv_dir:
        Directory containing ``<ods_table>.csv`` files.
    source_system:
        Value recorded in ``ods_*.source_system`` (default ``"CSV"``).
    """

    def __init__(self, csv_dir: str | Path, *, source_system: str = "CSV") -> None:
        self._csv_dir = Path(csv_dir)
        self._source_system = source_system
        # The CSV connector is stateless (no pool); ``connect`` is a no-op.

    async def connect(self) -> None:
        """Validate that ``csv_dir`` exists."""
        if not self._csv_dir.is_dir():
            raise FileNotFoundError(f"CSV connector dir does not exist: {self._csv_dir}")
        logger.info("csv_connector_ready", csv_dir=str(self._csv_dir))

    async def disconnect(self) -> None:
        """No-op for the CSV connector."""

    async def extract(
        self,
        table: str,
        since: datetime | None = None,
        batch_size: int = 1000,
    ) -> AsyncIterator[list[dict]]:
        """Stream rows from ``<csv_dir>/<table>.csv`` in batches.

        Rows are filtered client-side by ``source_update_time`` when
        ``since`` is provided, mirroring the Oracle connector's
        ``WHERE watermark > :since`` semantics.
        """
        csv_path = self._csv_dir / f"{table}.csv"
        if not csv_path.exists():
            logger.warning("csv_connector_missing_file", table=table, path=str(csv_path))
            return

        batch: list[dict[str, Any]] = []
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                parsed = self._parse_row(row, table)
                if since is not None and self._row_watermark(parsed) is not None:
                    if self._row_watermark(parsed) <= since:
                        continue
                batch.append(parsed)
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
        if batch:
            yield batch

    async def get_source_watermark(self, table: str) -> datetime | None:
        """Return ``MAX(source_update_time)`` across the CSV rows."""
        csv_path = self._csv_dir / f"{table}.csv"
        if not csv_path.exists():
            return None

        max_ts: datetime | None = None
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = self._parse_timestamp(row.get("source_update_time"))
                if ts is not None and (max_ts is None or ts > max_ts):
                    max_ts = ts
        return max_ts

    async def health_check(self) -> bool:
        """Return ``True`` iff ``csv_dir`` is a readable directory."""
        return self._csv_dir.is_dir()

    # ------------------------------------------------------------------ helpers

    def _parse_row(self, row: dict[str, str], table: str) -> dict[str, Any]:
        """Coerce CSV string values into native Python types.

        Type inference is intentionally simple:

        * Empty strings become ``None`` (mirrors asyncpg ``null=""`` in
          ``load_csv_to_ods.py``).
        * ``source_update_time`` / columns ending in ``_date`` /
          ``_time`` are parsed as ISO timestamps.
        * ``is_deleted`` becomes a ``bool`` (``"1"`` / ``"true"`` -> True).
        * Columns whose ODS schema is numeric (heuristic: name in a
          known set) are parsed as ``int`` / ``Decimal``.
        """
        out: dict[str, Any] = {}
        for key, raw in row.items():
            if key is None:
                continue
            if raw is None or raw == "":
                out[key] = None
                continue
            if key == "is_deleted":
                out[key] = raw.strip().lower() in ("1", "true", "t", "yes", "y")
                continue
            if key == "source_update_time" or key.endswith("_date") or key.endswith("_time"):
                ts = self._parse_timestamp(raw)
                out[key] = ts if ts is not None else raw
                continue
            if self._looks_numeric(key, raw):
                out[key] = self._parse_number(raw)
                continue
            out[key] = raw
        return out

    @staticmethod
    def _row_watermark(row: dict[str, Any]) -> datetime | None:
        ts = row.get("source_update_time")
        if isinstance(ts, datetime):
            return ts
        return None

    @staticmethod
    def _parse_timestamp(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _looks_numeric(col: str, raw: str) -> bool:
        """Heuristic: decide whether a CSV value should be parsed as a number.

        Conservative — only numeric when the column name matches a known
        numeric ODS column pattern AND the value parses cleanly. This
        keeps the CSV connector aligned with the schema-driven type
        conversion that PostgreSQL performs in the COPY path.
        """
        numeric_suffixes = (
            "_id", "_qty", "_count", "_rate", "_amount", "_price",
            "_cost", "_stock", "_quantity", "_received", "_invoiced",
        )
        if not (col.endswith(numeric_suffixes) or col in {"quantity", "amount"}):
            return False
        try:
            float(raw)  # validation only; actual parse via _parse_number
            return True
        except ValueError:
            return False

    @staticmethod
    def _parse_number(raw: str) -> int | float:
        """Parse a numeric CSV value into int (when integral) else float."""
        try:
            if "." not in raw and "e" not in raw.lower():
                return int(raw)
        except ValueError:
            pass
        return float(raw)
