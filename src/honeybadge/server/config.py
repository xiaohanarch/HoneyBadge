"""ServerConfig dataclass for HoneyBadge FastAPI server.

All configuration fields are loaded from environment variables with
sensible defaults for local development.

Security: In production (ENV=production), insecure default secrets are
rejected at startup. See ``_validate_production_config``.
"""

import os
import sys
from dataclasses import dataclass, field

# Known insecure default values — rejected in production mode
_INSECURE_JWT_DEFAULTS = frozenset({
    "change-me-in-production",
    "honeybadge-dev-secret-change-in-prod",
})
_INSECURE_NEBULA_DEFAULTS = frozenset({"nebula", ""})
_INSECURE_HICLAW_DEFAULTS = frozenset({"admin1234", "hiclaw-manager-password-dev", ""})


@dataclass
class ServerConfig:
    """Server configuration loaded from environment variables.

    All fields have defaults suitable for local development. In production,
    override via environment variables (e.g. in Kubernetes secrets/configmaps).
    """

    # -------------------------------------------------------------------------
    # Server networking
    # -------------------------------------------------------------------------
    host: str = field(default="0.0.0.0")
    port: int = field(default=8090)

    # -------------------------------------------------------------------------
    # NebulaGraph connection
    # -------------------------------------------------------------------------
    nebula_host: str = field(default="localhost")
    nebula_port: int = field(default=9669)
    nebula_user: str = field(default="root")
    nebula_password: str = field(default="nebula")
    nebula_space: str = field(default="honeybadge")

    # -------------------------------------------------------------------------
    # LLM service
    # -------------------------------------------------------------------------
    llm_endpoint: str = field(default="http://localhost:8000/v1")
    llm_api_key: str = field(default="")
    llm_model: str = field(default="glm-4")

    # -------------------------------------------------------------------------
    # PostgreSQL (audit log)
    # -------------------------------------------------------------------------
    pg_host: str = field(default="localhost")
    pg_port: int = field(default=5432)
    pg_user: str = field(default="honeybadge")
    pg_password: str = field(default="")
    pg_database: str = field(default="honeybadge")

    # -------------------------------------------------------------------------
    # Redis (cache)
    # -------------------------------------------------------------------------
    redis_host: str = field(default="localhost")
    redis_port: int = field(default=6379)
    redis_password: str = field(default="")

    # -------------------------------------------------------------------------
    # JWT authentication
    # -------------------------------------------------------------------------
    jwt_secret: str = field(default="change-me-in-production")
    jwt_access_expire_minutes: int = field(default=60)
    jwt_refresh_expire_days: int = field(default=7)

    # -------------------------------------------------------------------------
    # Milvus (vector DB, reserved for Phase 2)
    # -------------------------------------------------------------------------
    milvus_host: str = field(default="localhost")
    milvus_port: int = field(default=19530)

    # -------------------------------------------------------------------------
    # Reserved URLs (HiClaw / Matrix Room integration, Phase 2+)
    # -------------------------------------------------------------------------
    matrix_url: str = field(default="")
    hiclaw_manager_url: str = field(default="")

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Create a ServerConfig by reading environment variables.

        Each field maps to an env var (see field names above for the mapping).
        Missing env vars fall back to the dataclass field defaults.

        In production (``ENV=production``), insecure defaults are rejected
        and startup aborts. See ``_validate_production_config``.

        Returns:
            A populated ServerConfig instance.
        """
        config = cls(
            # Server networking
            host=os.environ.get("SERVER_HOST", "0.0.0.0"),
            port=int(os.environ.get("SERVER_PORT", "8090")),
            # NebulaGraph
            nebula_host=os.environ.get("NEBULA_HOST", "localhost"),
            nebula_port=int(os.environ.get("NEBULA_PORT", "9669")),
            nebula_user=os.environ.get("NEBULA_USER", "root"),
            nebula_password=os.environ.get("NEBULA_PASSWORD", "nebula"),
            nebula_space=os.environ.get("NEBULA_SPACE", "honeybadge"),
            # LLM
            llm_endpoint=os.environ.get("LLM_ENDPOINT", "http://localhost:8000/v1"),
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
            llm_model=os.environ.get("LLM_MODEL", "glm-4"),
            # PostgreSQL
            pg_host=os.environ.get("PG_HOST", "localhost"),
            pg_port=int(os.environ.get("PG_PORT", "5432")),
            pg_user=os.environ.get("PG_USER", "honeybadge"),
            pg_password=os.environ.get("PG_PASSWORD", ""),
            pg_database=os.environ.get("PG_DATABASE", "honeybadge"),
            # Redis
            redis_host=os.environ.get("REDIS_HOST", "localhost"),
            redis_port=int(os.environ.get("REDIS_PORT", "6379")),
            redis_password=os.environ.get("REDIS_PASSWORD", ""),
            # JWT
            jwt_secret=os.environ.get("JWT_SECRET", "change-me-in-production"),
            jwt_access_expire_minutes=int(os.environ.get("JWT_ACCESS_EXPIRE_MINUTES", "60")),
            jwt_refresh_expire_days=int(os.environ.get("JWT_REFRESH_EXPIRE_DAYS", "7")),
            # Milvus (reserved)
            milvus_host=os.environ.get("MILVUS_HOST", "localhost"),
            milvus_port=int(os.environ.get("MILVUS_PORT", "19530")),
            # Reserved URLs
            matrix_url=os.environ.get("MATRIX_URL", ""),
            hiclaw_manager_url=os.environ.get("HICLAW_MANAGER_URL", ""),
        )

        if os.environ.get("ENV") == "production":
            cls._validate_production_config(config)

        return config

    @staticmethod
    def _validate_production_config(config: "ServerConfig") -> None:
        """Reject insecure defaults when running in production.

        Called from ``from_env`` when ``ENV=production``. Aborts startup
        via ``SystemExit`` so misconfigured deployments fail fast rather
        than silently running with weak secrets.

        Args:
            config: The ServerConfig to validate.

        Raises:
            SystemExit: If any secret retains a known insecure default.
        """
        errors: list[str] = []

        if config.jwt_secret in _INSECURE_JWT_DEFAULTS or len(config.jwt_secret) < 32:
            errors.append(
                "JWT_SECRET must be set to a random value >= 32 chars in production "
                "(current value is an insecure default or too short)."
            )

        if config.nebula_password in _INSECURE_NEBULA_DEFAULTS:
            errors.append(
                "NEBULA_PASSWORD must be set in production (empty/'nebula' defaults rejected)."
            )

        if config.llm_api_key == "":
            errors.append("LLM_API_KEY must be set in production.")

        if errors:
            for e in errors:
                print(f"[security] FATAL: {e}", file=sys.stderr)
            raise SystemExit(1)
