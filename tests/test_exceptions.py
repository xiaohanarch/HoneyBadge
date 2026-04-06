"""Tests for exception module."""

import pytest

from honeybadge.core.exceptions import (
    DatabaseError,
    HoneyBadgeError,
    LLMError,
    LLMGenerationError,
    LLMTimeoutError,
    NebulaGraphError,
    PermissionValidationError,
    PostgreSQLError,
    RedisError,
    SchemaValidationError,
    SyntaxValidationError,
    ValidationError,
    WorkerError,
    WorkerTimeoutError,
    WorkerUnavailableError,
)


class TestHoneyBadgeError:
    """Tests for HoneyBadgeError base class."""

    def test_has_message_and_code(self):
        """Should have message and code."""
        error = HoneyBadgeError("Test error", "TEST_CODE")
        assert error.message == "Test error"
        assert error.code == "TEST_CODE"

    def test_default_code_is_internal_error(self):
        """Should have default code INTERNAL_ERROR."""
        error = HoneyBadgeError("Test error")
        assert error.code == "INTERNAL_ERROR"

    def test_str_returns_message(self):
        """Should return message when cast to string."""
        error = HoneyBadgeError("Test error")
        assert str(error) == "Test error"


class TestValidationErrors:
    """Tests for validation error classes."""

    def test_validation_error_has_code(self):
        """ValidationError should have VALIDATION_FAILED code."""
        error = ValidationError("Test")
        assert error.code == "VALIDATION_FAILED"

    def test_syntax_validation_error(self):
        """SyntaxValidationError should have SYNTAX_ERROR code."""
        error = SyntaxValidationError("Invalid syntax", ngql="MATCH (n)")
        assert error.code == "SYNTAX_ERROR"
        assert error.ngql == "MATCH (n)"

    def test_schema_validation_error(self):
        """SchemaValidationError should have SCHEMA_ERROR code."""
        error = SchemaValidationError(
            "Invalid property",
            invalid_properties=["unknown_prop"],
        )
        assert error.code == "SCHEMA_ERROR"
        assert "unknown_prop" in error.invalid_properties

    def test_permission_validation_error(self):
        """PermissionValidationError should have PERMISSION_DENIED code."""
        error = PermissionValidationError(
            "Missing filter",
            missing_filters=["org_id"],
        )
        assert error.code == "PERMISSION_DENIED"
        assert "org_id" in error.missing_filters


class TestDatabaseErrors:
    """Tests for database error classes."""

    def test_database_error(self):
        """DatabaseError should have DATABASE_ERROR code."""
        error = DatabaseError("DB error")
        assert error.code == "DATABASE_ERROR"

    def test_nebula_graph_error(self):
        """NebulaGraphError should store query."""
        error = NebulaGraphError("Query failed", query="MATCH (n) RETURN n")
        assert error.code == "NEBULA_ERROR"
        assert error.query == "MATCH (n) RETURN n"

    def test_redis_error(self):
        """RedisError should have REDIS_ERROR code."""
        error = RedisError("Redis connection failed")
        assert error.code == "REDIS_ERROR"

    def test_postgresql_error(self):
        """PostgreSQLError should have POSTGRESQL_ERROR code."""
        error = PostgreSQLError("PostgreSQL connection failed")
        assert error.code == "POSTGRESQL_ERROR"


class TestLLMErrors:
    """Tests for LLM error classes."""

    def test_llm_error(self):
        """LLMError should have LLM_ERROR code."""
        error = LLMError("LLM failed")
        assert error.code == "LLM_ERROR"

    def test_llm_generation_error(self):
        """LLMGenerationError should store question."""
        error = LLMGenerationError("Generation failed", question="Test question")
        assert error.code == "GENERATION_ERROR"
        assert error.question == "Test question"

    def test_llm_timeout_error(self):
        """LLMTimeoutError should have LLM_TIMEOUT code."""
        error = LLMTimeoutError()
        assert error.code == "LLM_TIMEOUT"
        assert "timed out" in error.message


class TestWorkerErrors:
    """Tests for worker error classes."""

    def test_worker_error(self):
        """WorkerError should have WORKER_ERROR code."""
        error = WorkerError("Worker failed")
        assert error.code == "WORKER_ERROR"

    def test_worker_timeout_error(self):
        """WorkerTimeoutError should have TIMEOUT code."""
        error = WorkerTimeoutError()
        assert error.code == "TIMEOUT"

    def test_worker_unavailable_error(self):
        """WorkerUnavailableError should store worker group."""
        error = WorkerUnavailableError("graph-worker")
        assert error.code == "SERVICE_UNAVAILABLE"
        assert error.worker_group == "graph-worker"
