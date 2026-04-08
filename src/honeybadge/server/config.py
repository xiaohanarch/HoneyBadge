"""ServerConfig dataclass for HoneyBadge FastAPI server.

All configuration fields are loaded from environment variables with
sensible defaults for local development.
"""

import os
from dataclasses import dataclass, field


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
    # Orchestrator selection
    # -------------------------------------------------------------------------
    orchestrator_type: str = field(default="direct")

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

    # -------------------------------------------------------------------------
    # Matrix client (honeybadge-gateway bot user, connects to HiClaw Tuwunel :6167)
    # -------------------------------------------------------------------------
    matrix_homeserver_url: str = field(default="http://localhost:6167")
    matrix_user_id: str = field(default="@honeybadge-gateway:matrix-local.hiclaw.io")
    matrix_user_password: str = field(default="")

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Create a ServerConfig by reading environment variables.

        Each field maps to an env var (see field names above for the mapping).
        Missing env vars fall back to the dataclass field defaults.

        Returns:
            A populated ServerConfig instance.
        """
        return cls(
            # Server networking
            host=os.environ.get("SERVER_HOST", "0.0.0.0"),
            port=int(os.environ.get("SERVER_PORT", "8090")),
            # Orchestrator
            orchestrator_type=os.environ.get("ORCHESTRATOR_TYPE", "direct"),
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
            # Matrix client
            matrix_homeserver_url=os.environ.get("MATRIX_HOMESERVER_URL", "http://localhost:6167"),
            matrix_user_id=os.environ.get("MATRIX_USER_ID", "@honeybadge-gateway:matrix-local.hiclaw.io"),
            matrix_user_password=os.environ.get("MATRIX_USER_PASSWORD", ""),
        )
