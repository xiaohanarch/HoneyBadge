"""ETL configuration loader.

Loads ``deploy/docker/etl-config.yaml`` plus environment-variable
overrides into a typed :class:`ETLConfig` dataclass. We deliberately
avoid pulling in Pydantic for the ETL subsystem (the rest of the
codebase uses it, but the ETL runner is a standalone process and we
keep its dependency surface small).

Environment variable expansion
------------------------------
YAML values may reference env vars with ``${VAR_NAME}`` syntax. Unknown
vars resolve to an empty string (matching docker-compose behaviour).
Critical secrets (Oracle password, Postgres DSN) should always come
from env vars, never from the committed YAML.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


@dataclass
class OracleConfig:
    """Oracle EBS connection parameters."""

    host: str = "localhost"
    port: int = 1521
    service_name: str = "ORCLPDB1"
    user: str = ""
    password: str = ""

    def to_dsn(self) -> str:
        """Return an oracledb EZCONNECT DSN ``host:port/service_name``."""
        return f"{self.host}:{self.port}/{self.service_name}"


@dataclass
class CSVConnectorConfig:
    """CSV connector parameters."""

    dir: str = "deploy/test-data/ptp_csv/"


@dataclass
class PipelineSection:
    """Pipeline settings (mirrors :class:`PipelineConfig` defaults)."""

    load_mode: str = "incremental"  # full | incremental
    tables: list[str] | None = None  # None = ENABLED_TABLES_P3
    postgres_dsn: str = "postgresql://honeybadge:honeybadge123@localhost:5432/honeybadge_ods"
    nebula_host: str = "localhost"
    nebula_port: int = 9669


@dataclass
class SchedulerSection:
    """Scheduler settings."""

    cron: str = "0 2 * * *"
    timezone: str = "Asia/Shanghai"
    skip_if_running: bool = True
    stale_timeout_sec: int = 7200


@dataclass
class ETLConfig:
    """Top-level ETL config loaded from YAML + env vars."""

    connector_type: str = "csv"  # csv | oracle_ebs
    oracle: OracleConfig = field(default_factory=OracleConfig)
    csv: CSVConnectorConfig = field(default_factory=CSVConnectorConfig)
    pipeline: PipelineSection = field(default_factory=PipelineSection)
    scheduler: SchedulerSection = field(default_factory=SchedulerSection)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ETLConfig":
        """Load config from a YAML file with ``${ENV_VAR}`` expansion."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"ETL config not found: {path}")

        raw = path.read_text(encoding="utf-8")
        expanded = _expand_env_vars(raw)
        data: dict[str, Any] = yaml.safe_load(expanded) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ETLConfig":
        """Build :class:`ETLConfig` from a parsed dict."""
        connector = data.get("connector", {}) or {}
        pipeline = data.get("pipeline", {}) or {}
        scheduler = data.get("scheduler", {}) or {}

        oracle = OracleConfig(
            host=connector.get("oracle", {}).get("host", "localhost"),
            port=int(connector.get("oracle", {}).get("port", 1521)),
            service_name=connector.get("oracle", {}).get("service_name", "ORCLPDB1"),
            user=connector.get("oracle", {}).get("user", ""),
            password=connector.get("oracle", {}).get("password", ""),
        )
        csv_cfg = CSVConnectorConfig(
            dir=connector.get("csv", {}).get("dir", "deploy/test-data/ptp_csv/"),
        )
        pipeline_section = PipelineSection(
            load_mode=pipeline.get("load_mode", "incremental"),
            tables=pipeline.get("tables"),
            postgres_dsn=pipeline.get(
                "postgres_dsn",
                "postgresql://honeybadge:honeybadge123@localhost:5432/honeybadge_ods",
            ),
            nebula_host=pipeline.get("nebula_host", "localhost"),
            nebula_port=int(pipeline.get("nebula_port", 9669)),
        )
        scheduler_section = SchedulerSection(
            cron=scheduler.get("cron", "0 2 * * *"),
            timezone=scheduler.get("timezone", "Asia/Shanghai"),
            skip_if_running=bool(scheduler.get("skip_if_running", True)),
            stale_timeout_sec=int(scheduler.get("stale_timeout_sec", 7200)),
        )
        return cls(
            connector_type=connector.get("type", "csv"),
            oracle=oracle,
            csv=csv_cfg,
            pipeline=pipeline_section,
            scheduler=scheduler_section,
        )


def _expand_env_vars(text: str) -> str:
    """Replace ``${VAR_NAME}`` with the matching environment variable.

    Unknown variables resolve to an empty string. This is intentionally
    simple — no default-value syntax — so that missing secrets fail
    loudly at the point of use rather than silently falling back.
    """

    def repl(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return _ENV_VAR_PATTERN.sub(repl, text)
