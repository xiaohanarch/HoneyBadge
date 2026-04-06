"""Constants for HoneyBadge."""

# =============================================================================
# Version Info
# =============================================================================

VERSION = "1.0.0"
APP_NAME = "HoneyBadge"

# =============================================================================
# NebulaGraph Configuration
# =============================================================================

NEBULA_DEFAULT_HOST = "localhost"
NEBULA_DEFAULT_PORT = 9669
NEBULA_DEFAULT_USER = "root"
NEBULA_DEFAULT_PASSWORD = "nebula"
NEBULA_DEFAULT_SPACE = "honeybadge"
NEBULA_CONNECTION_TIMEOUT = 30  # seconds
NEBULA_QUERY_TIMEOUT = 120  # seconds

# =============================================================================
# Redis Configuration
# =============================================================================

REDIS_DEFAULT_HOST = "localhost"
REDIS_DEFAULT_PORT = 6379
REDIS_DEFAULT_DB = 0
REDIS_SESSION_TTL = 1800  # 30 minutes
REDIS_CACHE_TTL = 300  # 5 minutes

# =============================================================================
# PostgreSQL Configuration (Audit Log)
# =============================================================================

POSTGRESQL_DEFAULT_HOST = "localhost"
POSTGRESQL_DEFAULT_PORT = 5432
POSTGRESQL_DEFAULT_USER = "honeybadge"
POSTGRESQL_DEFAULT_DATABASE = "honeybadge_audit"

# =============================================================================
# LLM Configuration
# =============================================================================

LLM_DEFAULT_ENDPOINT = "http://localhost:8000/v1"
LLM_DEFAULT_MODEL = "glm-4-flash"
LLM_COMPLEX_MODEL = "glm-5"
LLM_GENERATION_TIMEOUT = 60  # seconds
LLM_SUMMARIZATION_TIMEOUT = 30  # seconds
LLM_MAX_RETRIES = 3

# =============================================================================
# WebSocket Configuration
# =============================================================================

WS_HEARTBEAT_INTERVAL = 30  # seconds
WS_HEARTBEAT_TIMEOUT = 10  # seconds
WS_MESSAGE_MAX_SIZE = 10 * 1024 * 1024  # 10 MB

# =============================================================================
# Worker Configuration
# =============================================================================

WORKER_MAX_WORKERS = 8
WORKER_IDLE_TIMEOUT = 300  # seconds (5 minutes)
WORKER_TASK_TIMEOUT = 120  # seconds (2 minutes)
WORKER_MAX_RETRIES = 3

# =============================================================================
# Message Types (WebSocket Protocol)
# =============================================================================

# Client → Server
MSG_TYPE_QUERY = "query"
MSG_TYPE_HEARTBEAT = "heartbeat"

# Server → Client
MSG_TYPE_PROGRESS = "progress"
MSG_TYPE_STREAM = "stream"
MSG_TYPE_RESPONSE = "response"
MSG_TYPE_ERROR = "error"

# =============================================================================
# Stream Phases
# =============================================================================

STREAM_PHASE_THINKING = "thinking"
STREAM_PHASE_CYPHER = "cypher"
STREAM_PHASE_EXECUTING = "executing"
STREAM_PHASE_SUMMARIZING = "summarizing"

# =============================================================================
# Error Codes
# =============================================================================

ERR_VALIDATION_FAILED = "VALIDATION_FAILED"
ERR_EXECUTION_ERROR = "EXECUTION_ERROR"
ERR_LLM_ERROR = "LLM_ERROR"
ERR_TIMEOUT = "TIMEOUT"
ERR_RATE_LIMIT = "RATE_LIMIT"
ERR_SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
ERR_INTERNAL_ERROR = "INTERNAL_ERROR"
ERR_PERMISSION_DENIED = "PERMISSION_DENIED"

# =============================================================================
# Query Types (for routing)
# =============================================================================

QUERY_TYPE_GRAPH = "graph"
QUERY_TYPE_ANALYTICS = "analytics"
QUERY_TYPE_FEDERATED = "federated"

# =============================================================================
# Document Status Values
# =============================================================================

# Purchase Order Status
PO_STATUS_DRAFT = "DRAFT"
PO_STATUS_APPROVED = "APPROVED"
PO_STATUS_OPEN = "OPEN"
PO_STATUS_CLOSED = "CLOSED"
PO_STATUS_CANCELLED = "CANCELLED"

# Invoice Status
INV_STATUS_DRAFT = "DRAFT"
INV_STATUS_VALIDATED = "VALIDATED"
INV_STATUS_APPROVED = "APPROVED"
INV_STATUS_PAID = "PAID"
INV_STATUS_CANCELLED = "CANCELLED"

# Sales Order Status
SO_STATUS_DRAFT = "DRAFT"
SO_STATUS_BOOKED = "BOOKED"
SO_STATUS_SHIPPED = "SHIPPED"
SO_STATUS_INVOICED = "INVOICED"
SO_STATUS_CLOSED = "CLOSED"
SO_STATUS_CANCELLED = "CANCELLED"

# Three-way Matching Status
MATCH_STATUS_MATCHED = "MATCHED"
MATCH_STATUS_UNMATCHED = "UNMATCHED"
MATCH_STATUS_PARTIAL = "PARTIAL"

# =============================================================================
# Entity Prefix for VID Generation
# =============================================================================

VID_PREFIX_SUPPLIER = "SUP"
VID_PREFIX_CUSTOMER = "CUS"
VID_PREFIX_ITEM = "ITM"
VID_PREFIX_ORG = "ORG"
VID_PREFIX_EMPLOYEE = "EMP"
VID_PREFIX_WAREHOUSE = "WH"
VID_PREFIX_BOM = "BOM"
VID_PREFIX_BOM_COMP = "BOMC"
VID_PREFIX_PR = "PR"
VID_PREFIX_PR_LINE = "PRL"
VID_PREFIX_PO = "PO"
VID_PREFIX_PO_LINE = "POL"
VID_PREFIX_RECEIPT = "RCV"
VID_PREFIX_RECEIPT_LINE = "RCVL"
VID_PREFIX_QUALIFICATION = "SQ"
VID_PREFIX_INVOICE = "INV"
VID_PREFIX_INVOICE_LINE = "INVL"
VID_PREFIX_PAYMENT = "PAY"
VID_PREFIX_PAYMENT_BATCH = "PB"
VID_PREFIX_SO = "SO"
VID_PREFIX_SO_LINE = "SOL"
VID_PREFIX_SHIPMENT = "SHP"
VID_PREFIX_SHIPMENT_LINE = "SHPL"
VID_PREFIX_AR_INVOICE = "ARI"
VID_PREFIX_AR_RECEIPT = "ARR"
VID_PREFIX_GL_ACCOUNT = "GLA"
VID_PREFIX_JOURNAL = "JLE"
VID_PREFIX_JOURNAL_LINE = "JLL"
VID_PREFIX_XLA_EVENT = "XLA"
VID_PREFIX_ACCT_DIST = "ACD"
VID_PREFIX_APPROVAL = "APR"
VID_PREFIX_CONTRACT = "CNT"

# =============================================================================
# Matrix/Chat Configuration
# =============================================================================

MATRIX_HOMESERVER_URL = "http://localhost:8008"
MATRIX_BOT_USER = "@honeybadge-manager:matrix.local"

# Session cleanup
SESSION_IDLE_TIMEOUT = 1800  # 30 minutes
SESSION_ARCHIVE_DAYS = 7  # Archive sessions after 7 days of inactivity
