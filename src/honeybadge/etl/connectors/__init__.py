"""ERP source-system connectors for the HoneyBadge ETL pipeline.

Connectors abstract the extraction step (ERP -> ODS) behind a uniform
async interface so that the incremental loader does not need to know
whether rows originate from Oracle EBS, a CSV fixture, or a future
custom ERP.

Public API:
    ERPConnector   -- abstract base class implemented by every connector
    TableMapping   -- per-table source/column mapping configuration
"""

from honeybadge.etl.connectors.base import ERPConnector, TableMapping

__all__ = ["ERPConnector", "TableMapping"]
