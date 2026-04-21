"""HoneyBadge NebulaGraph MCP Server.

Provides tools for nGQL query generation, L1-L3 validated execution,
schema retrieval, and result summarization via FastMCP.

This is the safety gate for the entire HoneyBadge system — every query
passes through the Anti-Hallucination Framework (L1-L3) before execution.
"""

import os
import re
import sys

# Add src/ to path so we can import honeybadge modules
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_project_root, "src"))

import httpx
import structlog
from dataclasses import asdict
from fastmcp import FastMCP

from honeybadge.core.trace import generate_trace_id
from honeybadge.db.nebula import NebulaGraphClient, NebulaQueryResult
from honeybadge.llm.adapter import (
    OpenAICompatibleAdapter,
    generate_ngql as llm_generate_ngql,
    summarize_results as llm_summarize_results,
)
from honeybadge.protocols.validator import NgqlValidator

# Add mcp-servers/honeybadge-nebula-mcp to path for permission_enforcer
_nebula_mcp_path = os.path.dirname(os.path.abspath(__file__))
if _nebula_mcp_path not in sys.path:
    sys.path.insert(0, _nebula_mcp_path)
from permission_enforcer import PermissionEnforcer, PermissionViolationError
from honeybadge.permission_service.config import PERMISSION_CONFIG
from honeybadge.permission_service.models import PermissionContext

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# FastMCP app
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "honeybadge-nebula-mcp",
    instructions="NebulaGraph MCP Server for HoneyBadge — nGQL generation, "
    "L1-L3 validated execution, schema retrieval, and result summarization.",
)

# ---------------------------------------------------------------------------
# Schema cache — L1 in-process dict, L2 Redis (shared across replicas)
# ---------------------------------------------------------------------------

_schema_cache: dict[str, str] = {}
_SCHEMA_REDIS_PREFIX = "honeybadge:schema:"
_SCHEMA_TTL = int(os.environ.get("SCHEMA_CACHE_TTL", "3600"))  # seconds

_redis_client = None  # redis.asyncio.Redis, lazily initialized


def _get_redis():
    """Return a shared redis.asyncio.Redis client, or None if Redis is unavailable."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.Redis(
                host=os.environ.get("REDIS_HOST", "localhost"),
                port=int(os.environ.get("REDIS_PORT", "6379")),
                password=os.environ.get("REDIS_PASSWORD") or None,
                decode_responses=True,
            )
        except Exception:
            pass
    return _redis_client

# ---------------------------------------------------------------------------
# Write-operation keywords (must be rejected before execution)
# ---------------------------------------------------------------------------

_WRITE_OPS = re.compile(
    r"^\s*(INSERT|UPDATE|UPSERT|DELETE|DROP|CREATE|ALTER)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Permission service
# ---------------------------------------------------------------------------

PERMISSION_SERVICE_URL: str = os.environ.get(
    "PERMISSION_SERVICE_URL", "http://honeybadge-permissions:8092"
)

# Template for unknown users — note: user_id is always overridden at the
# call site with the actual user_id so this field is intentionally a placeholder.
# org_ids=[1] is a POC default; in production replace with org_ids=[] or
# derive from the user's provisioning record.
_DEFAULT_PERMISSION_TEMPLATE = {
    "allowed_processes": ["PTP"],
    "org_ids": [1],
    "dept_ids": None,
    "data_scope": "ORG",
}

# ---------------------------------------------------------------------------
# Lazy singletons (initialized from env vars on first use)
# ---------------------------------------------------------------------------

_nebula_client: NebulaGraphClient | None = None
_llm_adapter: OpenAICompatibleAdapter | None = None
_validator: NgqlValidator | None = None
_enforcer: PermissionEnforcer | None = None


def _get_nebula() -> NebulaGraphClient:
    global _nebula_client
    if _nebula_client is None:
        _nebula_client = NebulaGraphClient(
            host=os.environ.get("NEBULA_HOST", "localhost"),
            port=int(os.environ.get("NEBULA_PORT", "9669")),
            user=os.environ.get("NEBULA_USER", "root"),
            password=os.environ.get("NEBULA_PASSWORD", "nebula"),
        )
    return _nebula_client


def _get_llm() -> OpenAICompatibleAdapter:
    global _llm_adapter
    if _llm_adapter is None:
        _llm_adapter = OpenAICompatibleAdapter(
            config={
                "endpoint": os.environ.get("LLM_ENDPOINT", "http://localhost:8080"),
                "api_key": os.environ.get("LLM_API_KEY", ""),
                "model": os.environ.get("LLM_MODEL", "glm-4-flash"),
            }
        )
    return _llm_adapter


def _get_validator() -> NgqlValidator:
    global _validator
    if _validator is None:
        _validator = NgqlValidator()
    return _validator


def _get_enforcer() -> PermissionEnforcer:
    global _enforcer
    if _enforcer is None:
        _enforcer = PermissionEnforcer()
    return _enforcer


def _default_space() -> str:
    return os.environ.get("NEBULA_SPACE", "honeybadge")


# ---------------------------------------------------------------------------
# Implementation functions (accept explicit dependencies for testability)
# ---------------------------------------------------------------------------


async def get_schema_impl(
    nebula: NebulaGraphClient,
    space: str = "",
) -> str:
    """Load NebulaGraph schema (SHOW TAGS / DESCRIBE TAG / SHOW EDGES / DESCRIBE EDGE).

    Two-level cache: L1 in-process dict, L2 Redis (shared across replicas).
    """
    target_space = space or _default_space()

    # L1: in-process memory
    if target_space in _schema_cache:
        return _schema_cache[target_space]

    # L2: Redis
    redis = _get_redis()
    if redis is not None:
        try:
            cached = await redis.get(f"{_SCHEMA_REDIS_PREFIX}{target_space}")
            if cached:
                _schema_cache[target_space] = cached
                return cached
        except Exception as exc:
            logger.warning("schema_redis_read_failed", error=str(exc))

    lines: list[str] = []
    lines.append(f"# Schema for space: {target_space}\n")

    # --- Tags -----------------------------------------------------------
    tags_result = await nebula.execute("SHOW TAGS", space=target_space)
    tag_names: list[str] = []
    if tags_result.success:
        for row in tags_result.rows:
            # SHOW TAGS returns a single column "Name"
            name = row.get("Name") or row.get("name") or ""
            if name:
                tag_names.append(str(name))

    lines.append("## Tags")
    for tag in tag_names:
        desc = await nebula.execute(f"DESCRIBE TAG `{tag}`", space=target_space)
        lines.append(f"\n### {tag}")
        if desc.success:
            for prop_row in desc.rows:
                prop_name = prop_row.get("Field") or prop_row.get("field") or ""
                prop_type = prop_row.get("Type") or prop_row.get("type") or ""
                lines.append(f"  - {prop_name}: {prop_type}")

    # --- Edges ----------------------------------------------------------
    edges_result = await nebula.execute("SHOW EDGES", space=target_space)
    edge_names: list[str] = []
    if edges_result.success:
        for row in edges_result.rows:
            name = row.get("Name") or row.get("name") or ""
            if name:
                edge_names.append(str(name))

    lines.append("\n## Edges")
    for edge in edge_names:
        desc = await nebula.execute(f"DESCRIBE EDGE `{edge}`", space=target_space)
        lines.append(f"\n### {edge}")
        if desc.success:
            for prop_row in desc.rows:
                prop_name = prop_row.get("Field") or prop_row.get("field") or ""
                prop_type = prop_row.get("Type") or prop_row.get("type") or ""
                lines.append(f"  - {prop_name}: {prop_type}")

    schema_text = "\n".join(lines)

    # Store in L1
    _schema_cache[target_space] = schema_text

    # Store in L2 (Redis), best-effort
    if redis is not None:
        try:
            await redis.setex(f"{_SCHEMA_REDIS_PREFIX}{target_space}", _SCHEMA_TTL, schema_text)
        except Exception as exc:
            logger.warning("schema_redis_write_failed", error=str(exc))

    return schema_text


async def generate_ngql_impl(
    llm: OpenAICompatibleAdapter,
    nebula: NebulaGraphClient,
    question: str,
    schema_info: str = "",
) -> dict:
    """Call LLM to generate nGQL from a natural-language question.

    If *schema_info* is empty, auto-loads the schema first.
    Strips markdown code blocks (```ngql ... ```) from the LLM response.
    """
    trace_id = generate_trace_id()

    if not schema_info:
        schema_info = await get_schema_impl(nebula)

    response = await llm_generate_ngql(
        adapter=llm,
        question=question,
        schema_info=schema_info,
        ontology_info="",
        trace_id=trace_id,
    )

    ngql = response.content.strip()

    # Strip markdown code fences if present
    ngql = re.sub(r"^```(?:ngql|cypher|nGQL)?\s*\n?", "", ngql)
    ngql = re.sub(r"\n?```\s*$", "", ngql)
    ngql = ngql.strip()

    return {
        "ngql": ngql,
        "trace_id": trace_id,
    }


async def validate_and_execute_impl(
    nebula: NebulaGraphClient,
    validator: NgqlValidator,
    ngql: str,
    space: str = "",
    user_context: dict | None = None,
) -> dict:
    """L1-L3 validate then execute an nGQL statement.

    Returns a dict with ``success``, result data, and ``trace_id``.
    """
    trace_id = generate_trace_id()
    target_space = space or _default_space()

    # --- L1: Syntax validation ------------------------------------------
    l1 = validator.validate_syntax(ngql)
    if not l1.valid:
        return {
            "success": False,
            "error": "L1_SYNTAX",
            "details": [{"code": e.code, "message": e.message} for e in l1.errors],
            "trace_id": trace_id,
        }

    # --- Write-operation guard (part of L1) -----------------------------
    if _WRITE_OPS.match(ngql):
        return {
            "success": False,
            "error": "L1_WRITE_REJECTED",
            "details": [
                {
                    "code": "E010",
                    "message": f"Write operations are not allowed: {ngql.split()[0].upper()}",
                }
            ],
            "trace_id": trace_id,
        }

    # --- L2: Schema compliance ------------------------------------------
    l2 = validator.validate_schema(ngql)
    if not l2.valid:
        return {
            "success": False,
            "error": "L2_SCHEMA",
            "details": [{"code": e.code, "message": e.message} for e in l2.errors],
            "trace_id": trace_id,
        }

    # --- L3: Permission enforcement (PermissionEnforcer) ----------------
    # Auto-fetch permissions when caller provides user_id but not the full permissions dict.
    if user_context and user_context.get("user_id") and not user_context.get("permissions"):
        user_id = user_context["user_id"]
        perms_base = os.environ.get("PERMISSION_SERVICE_URL", "http://honeybadge-permissions:8092")
        try:
            async with httpx.AsyncClient() as _client:
                _resp = await _client.get(f"{perms_base}/permissions/{user_id}", timeout=5.0)
            if _resp.status_code == 200:
                user_context = {"user_id": user_id, "permissions": _resp.json()}
                logger.info("l3_permissions_fetched", user_id=user_id, trace_id=trace_id)
            else:
                logger.warning(
                    "l3_permissions_fetch_failed",
                    user_id=user_id, status=_resp.status_code, trace_id=trace_id,
                )
        except Exception as _e:
            logger.warning(
                "l3_permissions_fetch_error",
                user_id=user_id, error=str(_e), trace_id=trace_id,
            )

    if user_context and user_context.get("permissions"):
        try:
            perm_dict = user_context["permissions"]
            ctx = PermissionContext(**perm_dict)
            ngql, perm_warnings = _get_enforcer().enforce(ngql, ctx)
        except PermissionViolationError as exc:
            return {
                "success": False,
                "error": "L3_PERMISSION",
                "details": [{"code": "E300", "message": str(exc)}],
                "trace_id": trace_id,
            }
    else:
        if user_context is None:
            logger.warning("l3_skipped_no_user_context", trace_id=trace_id)
        perm_warnings = []

    # --- Execute --------------------------------------------------------
    result: NebulaQueryResult = await nebula.execute(ngql, space=target_space)
    if not result.success:
        return {
            "success": False,
            "error": "EXECUTION_ERROR",
            "details": [{"code": "E999", "message": result.error_message or "Unknown error"}],
            "trace_id": trace_id,
        }

    return {
        "success": True,
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "execution_time_ms": result.execution_time_ms,
        "trace_id": trace_id,
        "warnings": perm_warnings,
    }


async def explain_ngql_impl(
    nebula: NebulaGraphClient,
    ngql: str,
    space: str = "",
) -> dict:
    """Dry-run an nGQL statement with EXPLAIN prefix."""
    trace_id = generate_trace_id()
    target_space = space or _default_space()

    explain_stmt = f"EXPLAIN {ngql}"
    result = await nebula.execute(explain_stmt, space=target_space)

    if not result.success:
        return {
            "success": False,
            "error": result.error_message or "EXPLAIN failed",
            "trace_id": trace_id,
        }

    return {
        "success": True,
        "columns": result.columns,
        "rows": result.rows,
        "trace_id": trace_id,
    }


async def get_user_permissions_impl(user_id: str) -> dict:
    """Fetch PermissionContext for a user, with local fallback.

    Checks PERMISSION_CONFIG (local dict) first for an instant lookup.
    Falls back to HTTP call to PERMISSION_SERVICE_URL.
    Unknown users (e.g. Google SSO users not in the local config) receive
    a restrictive default (PTP only, org_id=[1]).
    """
    # Local fast path
    ctx = PERMISSION_CONFIG.get(user_id)
    if ctx is not None:
        return asdict(ctx)

    # Remote call
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{PERMISSION_SERVICE_URL}/permissions/{user_id}")
            if r.status_code == 200:
                return r.json()
            logger.warning(
                "permission_service_non_200",
                user_id=user_id,
                status_code=r.status_code,
            )
    except Exception as exc:
        logger.warning("permission_service_unreachable", user_id=user_id, error=str(exc))

    # Default: restrictive (PTP only, org_id=[1])
    logger.warning("using_default_permissions", user_id=user_id)
    return {"user_id": user_id, **_DEFAULT_PERMISSION_TEMPLATE}


async def summarize_query_results_impl(
    llm: OpenAICompatibleAdapter,
    question: str,
    columns: list[str],
    rows: list[dict],
    ngql: str = "",
) -> dict:
    """Call LLM to summarize query results in Chinese."""
    trace_id = generate_trace_id()

    response = await llm_summarize_results(
        adapter=llm,
        question=question,
        raw_results=rows,
        columns=columns,
        trace_id=trace_id,
    )

    return {
        "summary": response.content,
        "trace_id": trace_id,
    }


# ---------------------------------------------------------------------------
# MCP Tool wrappers (use lazy singletons)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_user_permissions(user_id: str) -> dict:
    """Fetch PermissionContext for a user from the PermissionResolver service.

    Workers MUST call this as the first step before any query.
    Returns a PermissionContext dict with allowed_processes, org_ids, data_scope.

    Args:
        user_id: Plain username (e.g. 'admin', 'subsidiary_lead').
                 Extract from the 'username' claim in the x-hb-auth JWT.
    """
    return await get_user_permissions_impl(user_id)


@mcp.tool()
async def get_schema(space: str = "") -> str:
    """Load NebulaGraph schema (tags, edges, properties).

    Returns formatted text describing all tags, edges, and their properties
    for the given graph space. Results are cached.

    Args:
        space: NebulaGraph space name. Uses NEBULA_SPACE env var if empty.
    """
    return await get_schema_impl(_get_nebula(), space=space)


@mcp.tool()
async def generate_query(question: str, schema_info: str = "", user_context: dict | None = None) -> dict:
    """Generate nGQL query from a natural-language question.

    Calls the LLM to translate a user question into an nGQL (NebulaGraph
    Query Language) statement. Automatically loads the schema if
    *schema_info* is not provided. Strips markdown code fences.

    Args:
        question: User's natural-language question.
        schema_info: Optional pre-loaded schema text. Auto-loaded if empty.
        user_context: Optional dict with shape {"user_id": str, "permissions": {...}}.
                      Accepted for compatibility but not used during query generation.
    """
    return await generate_ngql_impl(
        _get_llm(), _get_nebula(), question, schema_info=schema_info
    )


@mcp.tool()
async def validate_and_execute(ngql: str, space: str = "", user_context: dict | None = None) -> dict:
    """Validate (L1-L3) and execute an nGQL query.

    Runs the Anti-Hallucination Framework gates:
      L1 — syntax validation
      L1 — write-operation rejection
      L2 — schema compliance
      L3 — permission filter check (when user_context available)

    Then executes on NebulaGraph and returns raw results with a trace_id.

    Args:
        ngql: nGQL statement to validate and execute.
        space: NebulaGraph space name. Uses NEBULA_SPACE env var if empty.
        user_context: Optional dict with shape {"user_id": str, "permissions": {...}}
                      where "permissions" is a PermissionContext dict containing
                      allowed_processes, org_ids, dept_ids, data_scope.
                      Obtain via get_user_permissions(user_id) before calling this tool.
    """
    return await validate_and_execute_impl(
        _get_nebula(), _get_validator(), ngql, space=space, user_context=user_context
    )


@mcp.tool()
async def explain_ngql(ngql: str, space: str = "") -> dict:
    """Dry-run an nGQL statement with EXPLAIN prefix.

    Returns the query execution plan without actually executing the query.

    Args:
        ngql: nGQL statement to explain.
        space: NebulaGraph space name. Uses NEBULA_SPACE env var if empty.
    """
    return await explain_ngql_impl(_get_nebula(), ngql, space=space)


@mcp.tool()
async def summarize_query_results(
    question: str,
    columns: list[str],
    rows: list[dict],
    ngql: str = "",
) -> dict:
    """Summarize query results in Chinese using the LLM.

    Generates a human-readable summary of raw query results, following
    the L4 passthrough rule (LLM cannot modify data values).

    Args:
        question: Original user question.
        columns: Column names from the query result.
        rows: Row data (list of dicts) from the query result.
        ngql: Optional nGQL statement for context.
    """
    return await summarize_query_results_impl(
        _get_llm(), question, columns, rows, ngql=ngql
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
