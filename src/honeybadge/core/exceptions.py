"""Exception hierarchy for HoneyBadge."""


class HoneyBadgeError(Exception):
    """Base exception for all HoneyBadge errors."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


# =============================================================================
# Validation Errors (L1-L3)
# =============================================================================


class ValidationError(HoneyBadgeError):
    """Base class for validation errors."""

    def __init__(self, message: str, code: str = "VALIDATION_FAILED"):
        super().__init__(message, code)


class SyntaxValidationError(ValidationError):
    """L1: nGQL syntax validation failed."""

    def __init__(self, message: str, ngql: str = ""):
        self.ngql = ngql
        super().__init__(message, "SYNTAX_ERROR")


class SchemaValidationError(ValidationError):
    """L2: Schema compliance validation failed."""

    def __init__(self, message: str, invalid_properties: list = None):
        self.invalid_properties = invalid_properties or []
        super().__init__(message, "SCHEMA_ERROR")


class PermissionValidationError(ValidationError):
    """L3: Permission validation failed."""

    def __init__(self, message: str, missing_filters: list = None):
        self.missing_filters = missing_filters or []
        super().__init__(message, "PERMISSION_DENIED")


# =============================================================================
# Database Errors
# =============================================================================


class DatabaseError(HoneyBadgeError):
    """Base class for database errors."""

    def __init__(self, message: str, code: str = "DATABASE_ERROR"):
        super().__init__(message, code)


class NebulaGraphError(DatabaseError):
    """NebulaGraph database error."""

    def __init__(self, message: str, query: str = ""):
        self.query = query
        super().__init__(message, "NEBULA_ERROR")


class RedisError(DatabaseError):
    """Redis cache error."""

    def __init__(self, message: str):
        super().__init__(message, "REDIS_ERROR")


class PostgreSQLError(DatabaseError):
    """PostgreSQL audit log error."""

    def __init__(self, message: str):
        super().__init__(message, "POSTGRESQL_ERROR")


# =============================================================================
# LLM Errors
# =============================================================================


class LLMError(HoneyBadgeError):
    """Base class for LLM-related errors."""

    def __init__(self, message: str, code: str = "LLM_ERROR"):
        super().__init__(message, code)


class LLMGenerationError(LLMError):
    """Failed to generate nGQL from natural language."""

    def __init__(self, message: str, question: str = ""):
        self.question = question
        super().__init__(message, "GENERATION_ERROR")


class LLMSummarizationError(LLMError):
    """Failed to generate result summary."""

    def __init__(self, message: str):
        super().__init__(message, "SUMMARIZATION_ERROR")


class LLMTimeoutError(LLMError):
    """LLM API timeout."""

    def __init__(self, message: str = "LLM API request timed out"):
        super().__init__(message, "LLM_TIMEOUT")


# =============================================================================
# Worker Errors
# =============================================================================


class WorkerError(HoneyBadgeError):
    """Base class for worker errors."""

    def __init__(self, message: str, code: str = "WORKER_ERROR"):
        super().__init__(message, code)


class WorkerTimeoutError(WorkerError):
    """Worker task timeout."""

    def __init__(self, message: str = "Worker task timed out"):
        super().__init__(message, "TIMEOUT")


class WorkerUnavailableError(WorkerError):
    """No workers available to handle the request."""

    def __init__(self, worker_group: str):
        self.worker_group = worker_group
        super().__init__(
            f"No workers available for group: {worker_group}",
            "SERVICE_UNAVAILABLE",
        )


# =============================================================================
# Message Protocol Errors
# =============================================================================


class ProtocolError(HoneyBadgeError):
    """Base class for protocol errors."""

    def __init__(self, message: str, code: str = "PROTOCOL_ERROR"):
        super().__init__(message, code)


class MessageValidationError(ProtocolError):
    """WebSocket message validation failed."""

    def __init__(self, message: str, message_type: str = ""):
        self.message_type = message_type
        super().__init__(message, "INVALID_MESSAGE")


class SessionError(ProtocolError):
    """Session management error."""

    def __init__(self, message: str, session_id: str = ""):
        self.session_id = session_id
        super().__init__(message, "SESSION_ERROR")
