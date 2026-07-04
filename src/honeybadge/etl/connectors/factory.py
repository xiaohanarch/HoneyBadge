"""Connector factory.

Resolves an :class:`ETLConfig` into a concrete :class:`ERPConnector`
instance. Keeps the loader / scheduler decoupled from the specific
connector implementation.
"""

from __future__ import annotations

from honeybadge.etl.config import ETLConfig
from honeybadge.etl.connectors.base import ERPConnector
from honeybadge.etl.connectors.csv_connector import CSVConnector
from honeybadge.etl.connectors.oracle_ebs import OracleEBSConnector


def create_connector(config: ETLConfig) -> ERPConnector:
    """Instantiate the connector selected by ``config.connector_type``.

    Raises
    ------
    ValueError
        If ``connector_type`` is not ``csv`` or ``oracle_ebs``.
    """
    if config.connector_type == "csv":
        return CSVConnector(config.csv.dir)
    if config.connector_type == "oracle_ebs":
        return OracleEBSConnector(
            user=config.oracle.user,
            password=config.oracle.password,
            dsn=config.oracle.to_dsn(),
        )
    raise ValueError(
        f"Unknown connector type: {config.connector_type!r}. "
        f"Expected one of: csv, oracle_ebs"
    )
