"""Tests for ServerConfig dataclass."""

import os

import pytest

from honeybadge.server.config import ServerConfig


class TestDefaultConfig:
    """Tests for ServerConfig default values."""

    def test_default_host(self):
        """Should default host to 0.0.0.0."""
        config = ServerConfig()
        assert config.host == "0.0.0.0"

    def test_default_port(self):
        """Should default port to 8090."""
        config = ServerConfig()
        assert config.port == 8090

    def test_default_orchestrator_type(self):
        """Should default orchestrator_type to 'direct'."""
        config = ServerConfig()
        assert config.orchestrator_type == "direct"

    def test_default_nebula_fields(self):
        """Should have sensible NebulaGraph defaults."""
        config = ServerConfig()
        assert config.nebula_host == "localhost"
        assert config.nebula_port == 9669
        assert config.nebula_user == "root"
        assert config.nebula_password == "nebula"
        assert config.nebula_space == "honeybadge"

    def test_default_llm_fields(self):
        """Should have LLM defaults."""
        config = ServerConfig()
        assert config.llm_endpoint == "http://localhost:8000/v1"
        assert config.llm_api_key == ""
        assert config.llm_model == "glm-4"

    def test_default_pg_fields(self):
        """Should have PostgreSQL defaults."""
        config = ServerConfig()
        assert config.pg_host == "localhost"
        assert config.pg_port == 5432
        assert config.pg_user == "honeybadge"
        assert config.pg_password == ""
        assert config.pg_database == "honeybadge"

    def test_default_redis_fields(self):
        """Should have Redis defaults."""
        config = ServerConfig()
        assert config.redis_host == "localhost"
        assert config.redis_port == 6379
        assert config.redis_password == ""

    def test_default_jwt_fields(self):
        """Should have JWT defaults."""
        config = ServerConfig()
        assert config.jwt_secret == "change-me-in-production"
        assert config.jwt_access_expire_minutes == 60
        assert config.jwt_refresh_expire_days == 7

    def test_default_milvus_fields(self):
        """Should have reserved Milvus defaults."""
        config = ServerConfig()
        assert config.milvus_host == "localhost"
        assert config.milvus_port == 19530

    def test_default_reserved_urls(self):
        """Should have reserved URL defaults."""
        config = ServerConfig()
        assert config.matrix_url == ""
        assert config.hiclaw_manager_url == ""

    def test_default_matrix_fields(self):
        """Should have Matrix client defaults pointing to HiClaw Tuwunel."""
        config = ServerConfig()
        assert config.matrix_homeserver_url == "http://localhost:6167"
        assert config.matrix_user_id == "@honeybadge-gateway:matrix-local.hiclaw.io"
        assert config.matrix_user_password == ""

    def test_default_config(self):
        """test_default_config: verify all defaults are correct types."""
        config = ServerConfig()
        assert isinstance(config.host, str)
        assert isinstance(config.port, int)
        assert isinstance(config.orchestrator_type, str)
        assert isinstance(config.jwt_access_expire_minutes, int)
        assert isinstance(config.jwt_refresh_expire_days, int)


class TestConfigFromEnv:
    """Tests for ServerConfig loading from environment variables."""

    def test_config_from_env(self, monkeypatch):
        """test_config_from_env: env vars should override defaults."""
        monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
        monkeypatch.setenv("SERVER_PORT", "9000")
        monkeypatch.setenv("ORCHESTRATOR_TYPE", "hiclaw")
        monkeypatch.setenv("NEBULA_HOST", "nebula-server")
        monkeypatch.setenv("NEBULA_PORT", "9670")
        monkeypatch.setenv("NEBULA_USER", "admin")
        monkeypatch.setenv("NEBULA_PASSWORD", "secret")
        monkeypatch.setenv("NEBULA_SPACE", "production")
        monkeypatch.setenv("LLM_ENDPOINT", "http://llm.example.com/v1")
        monkeypatch.setenv("LLM_API_KEY", "my-api-key")
        monkeypatch.setenv("LLM_MODEL", "glm-5")
        monkeypatch.setenv("PG_HOST", "pg-server")
        monkeypatch.setenv("PG_PORT", "5433")
        monkeypatch.setenv("PG_USER", "pguser")
        monkeypatch.setenv("PG_PASSWORD", "pgpass")
        monkeypatch.setenv("PG_DATABASE", "mydb")
        monkeypatch.setenv("REDIS_HOST", "redis-server")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_PASSWORD", "redispass")
        monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-key")
        monkeypatch.setenv("JWT_ACCESS_EXPIRE_MINUTES", "30")
        monkeypatch.setenv("JWT_REFRESH_EXPIRE_DAYS", "14")
        monkeypatch.setenv("MILVUS_HOST", "milvus-server")
        monkeypatch.setenv("MILVUS_PORT", "19531")
        monkeypatch.setenv("MATRIX_URL", "http://matrix.example.com")
        monkeypatch.setenv("HICLAW_MANAGER_URL", "http://hiclaw.example.com")
        monkeypatch.setenv("MATRIX_HOMESERVER_URL", "http://hiclaw.example.com:6167")
        monkeypatch.setenv("MATRIX_USER_ID", "@honeybadge-gateway:hiclaw.example.com")
        monkeypatch.setenv("MATRIX_USER_PASSWORD", "secret")

        config = ServerConfig.from_env()

        assert config.host == "127.0.0.1"
        assert config.port == 9000
        assert config.orchestrator_type == "hiclaw"
        assert config.nebula_host == "nebula-server"
        assert config.nebula_port == 9670
        assert config.nebula_user == "admin"
        assert config.nebula_password == "secret"
        assert config.nebula_space == "production"
        assert config.llm_endpoint == "http://llm.example.com/v1"
        assert config.llm_api_key == "my-api-key"
        assert config.llm_model == "glm-5"
        assert config.pg_host == "pg-server"
        assert config.pg_port == 5433
        assert config.pg_user == "pguser"
        assert config.pg_password == "pgpass"
        assert config.pg_database == "mydb"
        assert config.redis_host == "redis-server"
        assert config.redis_port == 6380
        assert config.redis_password == "redispass"
        assert config.jwt_secret == "super-secret-jwt-key"
        assert config.jwt_access_expire_minutes == 30
        assert config.jwt_refresh_expire_days == 14
        assert config.milvus_host == "milvus-server"
        assert config.milvus_port == 19531
        assert config.matrix_url == "http://matrix.example.com"
        assert config.hiclaw_manager_url == "http://hiclaw.example.com"
        assert config.matrix_homeserver_url == "http://hiclaw.example.com:6167"
        assert config.matrix_user_id == "@honeybadge-gateway:hiclaw.example.com"
        assert config.matrix_user_password == "secret"

    def test_partial_env_override(self, monkeypatch):
        """Partial env vars should override only those fields."""
        monkeypatch.setenv("SERVER_PORT", "8888")
        monkeypatch.setenv("NEBULA_SPACE", "test_space")

        config = ServerConfig.from_env()

        assert config.port == 8888
        assert config.nebula_space == "test_space"
        # Other fields remain at defaults
        assert config.host == "0.0.0.0"
        assert config.nebula_host == "localhost"

    def test_from_env_matrix_defaults_to_hiclaw_tuwunel(self, monkeypatch):
        """When no Matrix env vars are set, from_env() should default to HiClaw Tuwunel."""
        # Ensure no Matrix env vars are set
        monkeypatch.delenv("MATRIX_HOMESERVER_URL", raising=False)
        monkeypatch.delenv("MATRIX_USER_ID", raising=False)
        monkeypatch.delenv("MATRIX_USER_PASSWORD", raising=False)

        config = ServerConfig.from_env()
        assert config.matrix_homeserver_url == "http://localhost:6167"
        assert config.matrix_user_id == "@honeybadge-gateway:matrix-local.hiclaw.io"
        assert config.matrix_user_password == ""


def test_hiclaw_query_timeout_default():
    from honeybadge.server.config import ServerConfig
    config = ServerConfig()
    assert config.hiclaw_query_timeout == 60.0


def test_hiclaw_query_timeout_from_env(monkeypatch):
    monkeypatch.setenv("HICLAW_QUERY_TIMEOUT", "120")
    from honeybadge.server.config import ServerConfig
    config = ServerConfig.from_env()
    assert config.hiclaw_query_timeout == 120.0
