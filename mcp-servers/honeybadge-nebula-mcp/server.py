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

import structlog
from fastmcp import FastMCP

from honeybadge.core.trace import generate_trace_id
from honeybadge.db.nebula import NebulaGraphClient, NebulaQueryResult
from honeybadge.llm.adapter import (
    OpenAICompatibleAdapter,
    generate_ngql as llm_generate_ngql,
    summarize_results as llm_summarize_results,
)
from honeybadge.protocols.validator import NgqlValidator

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
# Global schema cache
# ---------------------------------------------------------------------------

_schema_cache: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Write-operation keywords (must be rejected before execution)
# ---------------------------------------------------------------------------

_WRITE_OPS = re.compile(
    r"^\s*(INSERT|UPDATE|UPSERT|DELETE|DROP|CREATE|ALTER)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Lazy singletons (initialized from env vars on first use)
# ---------------------------------------------------------------------------

_nebula_client: NebulaGraphClient | None = None
_llm_adapter: OpenAICompatibleAdapter | None = None
_validator: NgqlValidator | None = None


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

    Results are cached in the global ``_schema_cache`` keyed by space name.
    """
    target_space = space or _default_space()

    if target_space in _schema_cache:
        return _schema_cache[target_space]

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
    _schema_cache[target_space] = schema_text
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

    # --- L3: Permission filters -----------------------------------------
    if user_context:
        l3 = validator.validate_permissions(ngql, user_context)
        if not l3.valid:
            return {
                "success": False,
                "error": "L3_PERMISSION",
                "details": [{"code": e.code, "message": e.message} for e in l3.errors],
                "trace_id": trace_id,
            }

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
async def get_schema(space: str = "") -> str:
    """Load NebulaGraph schema (tags, edges, properties).

    Returns formatted text describing all tags, edges, and their properties
    for the given graph space. Results are cached.

    Args:
        space: NebulaGraph space name. Uses NEBULA_SPACE env var if empty.
    """
    return await get_schema_impl(_get_nebula(), space=space)


@mcp.tool()
async def generate_query(question: str, schema_info: str = "") -> dict:
    """Generate nGQL query from a natural-language question.

    Calls the LLM to translate a user question into an nGQL (NebulaGraph
    Query Language) statement. Automatically loads the schema if
    *schema_info* is not provided. Strips markdown code fences.

    Args:
        question: User's natural-language question.
        schema_info: Optional pre-loaded schema text. Auto-loaded if empty.
    """
    return await generate_ngql_impl(
        _get_llm(), _get_nebula(), question, schema_info=schema_info
    )


@mcp.tool()
async def validate_and_execute(ngql: str, space: str = "") -> dict:
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
    """
    return await validate_and_execute_impl(
        _get_nebula(), _get_validator(), ngql, space=space
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
    mcp.run()
