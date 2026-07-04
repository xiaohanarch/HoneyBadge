"""ERP connector abstraction layer.

Defines the ``ERPConnector`` abstract base class and the ``TableMapping``
dataclass that together describe the contract for extracting rows from an
ERP source system (Oracle EBS, custom ERP, CSV fixtures, ...) into the
HoneyBadge ODS layer.

Design notes
------------
* ``extract`` returns an *async iterator of batches* (``list[dict]``).
  Yielding batches rather than single rows balances memory usage against
  per-fetch overhead. A 1000-row batch is a sensible default.
* The connector is responsible for type conversion into Python natives
  (``int``, ``Decimal``, ``datetime``, ``str``) so the loader never has
  to introspect driver-specific types.
* Soft deletes are modeled via ``derived_columns`` (e.g. an ``is_deleted``
  flag derived from an EBS status column). Hard-delete capture via
  LogMiner is out of scope for P3 and is documented as a known limitation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator


@dataclass(frozen=True)
class TableMapping:
    """Declarative mapping between one ODS table and its ERP source.

    Attributes
    ----------
    source_table:
        Name of the source table/view in the ERP system
        (e.g. ``"PO_HEADERS_ALL"``).
    watermark_column:
        Column on the source table used for incremental extraction
        (e.g. ``"LAST_UPDATE_DATE"``).
    column_mapping:
        ``{ods_column: source_column}`` mapping. The connector SELECTs
        each ``source_column`` and the loader INSERTs the value into
        ``ods_column``. Only the ODS business columns are listed here;
        ETL metadata columns (``etl_batch_id`` etc.) are added by the
        loader.
    derived_columns:
        ``{ods_column: sql_expr}`` mapping for columns whose ODS value
        is computed from source columns rather than read directly
        (e.g. ``{"is_deleted": "CASE WHEN AUTHORIZATION_STATUS = 'CANCELLED' THEN 1 ELSE 0 END"}``).
        The expression is inserted verbatim into the SELECT list.
    source_system:
        Identifier recorded in ``ods_*.source_system`` (default ``"EBS"``).
    """

    source_table: str
    watermark_column: str
    column_mapping: dict[str, str] = field(default_factory=dict)
    derived_columns: dict[str, str] = field(default_factory=dict)
    source_system: str = "EBS"

    @property
    def ods_columns(self) -> list[str]:
        """All ODS columns produced by this mapping (mapped + derived)."""
        return list(self.column_mapping.keys()) + list(self.derived_columns.keys())

    def build_select_list(self) -> str:
        """Build the comma-separated SELECT list for extraction.

        Each entry is ``<source_expr> AS <ods_column>`` so the returned
        rows can be addressed by ODS column name regardless of whether
        the column is a direct mapping or a derived expression.
        """
        parts: list[str] = []
        for ods_col, src_col in self.column_mapping.items():
            parts.append(f"{src_col} AS {ods_col}")
        for ods_col, expr in self.derived_columns.items():
            parts.append(f"({expr}) AS {ods_col}")
        return ", ".join(parts)


class ERPConnector(ABC):
    """Abstract base class for ERP source-system connectors.

    All methods are async. Implementations are expected to be safe to
    instantiate once and reuse across many ``extract`` calls (i.e.
    ``connect`` once, extract many, ``disconnect`` at shutdown).
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying connection / pool."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Release the underlying connection / pool."""

    @abstractmethod
    async def extract(
        self,
        table: str,
        since: datetime | None = None,
        batch_size: int = 1000,
    ) -> AsyncIterator[list[dict]]:
        """Stream rows from the source table in batches.

        Parameters
        ----------
        table:
            ODS table name (e.g. ``"ods_purchase_order"``). The connector
            resolves it to a :class:`TableMapping` to determine the
            source table, columns and watermark.
        since:
            Watermark lower bound (exclusive). ``None`` means full
            extract.
        batch_size:
            Maximum number of rows per yielded batch. The final batch
            may be smaller.

        Yields
        ------
        list[dict]
            A batch of rows. Each row is a ``{ods_column: value}`` dict
            using native Python types. An empty list is never yielded;
            the iterator simply ends when no more rows remain.
        """

    @abstractmethod
    async def get_source_watermark(self, table: str) -> datetime | None:
        """Return ``MAX(watermark_column)`` from the source table.

        ``None`` is returned when the source table is empty. Used for
        diagnostics and freshness checks, not for driving the loader
        (the loader uses the ODS-side watermark for self-healing).
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Return ``True`` if the source is reachable and healthy."""
