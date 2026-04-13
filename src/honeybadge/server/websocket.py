"""WebSocket query handler for HoneyBadge server.

Receives QueryRequest messages, processes them through the LLM+NebulaGraph pipeline,
and returns QueryResponse messages with trace_id and execution_time_ms.
"""

import time
from pathlib import Path
from typing import Any

import structlog

from honeybadge.core.trace import generate_trace_id
from honeybadge.db.nebula import NebulaGraphClient
from honeybadge.db.postgres import PostgreSQLClient
from honeybadge.llm.adapter import OpenAICompatibleAdapter
from honeybadge.llm.adapter import generate_ngql as llm_generate_ngql
from honeybadge.llm.adapter import summarize_results as llm_summarize_results

logger = structlog.get_logger()

# Path to prompts directory (resolved relative to src/honeybadge/)
_PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"

# In-memory schema cache
_schema_cache: dict[str, str] = {}


async def get_schema_str(nebula: NebulaGraphClient, space: str = "honeybadge") -> str:
    """Get formatted NebulaGraph schema string."""
    if space in _schema_cache:
        return _schema_cache[space]

    lines = [f"# Schema for space: {space}\n"]

    # Tags
    tags_result = await nebula.execute("SHOW TAGS", space=space)
    tag_names = []
    if tags_result.success:
        for row in tags_result.rows:
            name = row.get("Name") or row.get("name") or ""
            if name:
                tag_names.append(str(name))

    lines.append("## Tags")
    for tag in tag_names:
        desc_result = await nebula.execute(f"DESCRIBE TAG `{tag}`", space=space)
        if desc_result.success:
            lines.append(f"### {tag}")
            for row in desc_result.rows:
                col = row.get("Field") or row.get("field") or ""
                typ = row.get("Type") or row.get("type") or ""
                null = row.get("Null") or row.get("null") or ""
                default = row.get("Default") or row.get("default") or ""
                extra = row.get("Extra") or row.get("extra") or ""
                props_str = f"{typ}"
                if null == "NO":
                    props_str += " NOT NULL"
                if default:
                    props_str += f" DEFAULT {default}"
                if extra:
                    props_str += f" {extra}"
                lines.append(f"  - {col}: {props_str}")

    # Edges
    edges_result = await nebula.execute("SHOW EDGES", space=space)
    edge_names = []
    if edges_result.success:
        for row in edges_result.rows:
            name = row.get("Name") or row.get("name") or ""
            if name:
                edge_names.append(str(name))

    lines.append("\n## Edges")
    for edge in edge_names:
        desc_result = await nebula.execute(f"DESCRIBE EDGE `{edge}`", space=space)
        if desc_result.success:
            lines.append(f"### {edge}")
            for row in desc_result.rows:
                col = row.get("Field") or row.get("field") or ""
                typ = row.get("Type") or row.get("type") or ""
                null = row.get("Null") or row.get("null") or ""
                default = row.get("Default") or row.get("default") or ""
                extra = row.get("Extra") or row.get("extra") or ""
                props_str = f"{typ}"
                if null == "NO":
                    props_str += " NOT NULL"
                if default:
                    props_str += f" DEFAULT {default}"
                if extra:
                    props_str += f" {extra}"
                lines.append(f"  - {col}: {props_str}")

    schema_str = "\n".join(lines)
    _schema_cache[space] = schema_str
    return schema_str


def load_ontology_str() -> str:
    """Load ontology text from prompts/ontology/ directory."""
    ontology_dir = _PROMPTS_DIR / "ontology"
    if not ontology_dir.exists():
        return ""

    parts = []
    for md_file in sorted(ontology_dir.glob("*.md")):
        parts.append(f"# {md_file.stem}\n")
        parts.append(md_file.read_text(encoding="utf-8"))
        parts.append("\n")
    return "\n".join(parts)


async def process_query(
    question: str,
    session_id: str,
    nebula: NebulaGraphClient,
    pg: PostgreSQLClient,
    llm_adapter: OpenAICompatibleAdapter,
    space: str = "honeybadge",
    user_id: str = "anonymous",
) -> dict[str, Any]:
    """
    Process a natural language query and return a result dict.

    Returns dict with: summary, raw_data, columns, cypher, trace_id, execution_time_ms, row_count
    """
    trace_id = generate_trace_id()
    start_time = time.time()

    logger.info("ws_query_start", trace_id=trace_id, question=question[:50])

    try:
        # Step 1: Get schema
        schema_str = await get_schema_str(nebula, space)
        ontology_str = load_ontology_str()

        # Step 2: Generate nGQL
        ngql_response = await llm_generate_ngql(
            adapter=llm_adapter,
            question=question,
            schema_info=schema_str,
            ontology_info=ontology_str,
        )
        if not ngql_response.success:
            raise Exception(f"nGQL generation failed: {ngql_response.error_message}")

        ngql = ngql_response.content.strip()
        logger.info("ws_ngql_generated", trace_id=trace_id, ngql=ngql[:100])

        # Step 3: Execute
        query_result = await nebula.execute(ngql, space=space)
        execution_time_ms = int((time.time() - start_time) * 1000)

        if not query_result.success:
            raise Exception(f"Query execution failed: {query_result.error_message}")

        # Step 4: Summarize
        summary_response = await llm_summarize_results(
            adapter=llm_adapter,
            question=question,
            raw_results=query_result.rows,
            columns=query_result.columns,
        )
        summary = summary_response.content if summary_response.success else "摘要生成失败"

        # Step 5: Write audit log
        from honeybadge.db.postgres import AuditLogEntry

        try:
            audit_entry = AuditLogEntry(
                trace_id=trace_id,
                question=question,
                cypher=ngql,
                raw_result={"columns": query_result.columns, "rows": query_result.rows},
                summary=summary,
                user_id=user_id,
                session_id=session_id,
                execution_time_ms=execution_time_ms,
                row_count=query_result.row_count,
            )
            await pg.write_audit_log(audit_entry)
        except Exception as audit_err:
            logger.warning("ws_audit_write_failed", trace_id=trace_id, error=str(audit_err))

        logger.info(
            "ws_query_complete",
            trace_id=trace_id,
            execution_time_ms=execution_time_ms,
            row_count=query_result.row_count,
        )

        return {
            "summary": summary,
            "raw_data": query_result.rows,
            "columns": query_result.columns,
            "cypher": ngql,
            "trace_id": trace_id,
            "execution_time_ms": execution_time_ms,
            "row_count": query_result.row_count,
        }

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        logger.error("ws_query_error", trace_id=trace_id, error=str(e))

        # Try to write error audit
        try:
            from honeybadge.db.postgres import AuditLogEntry

            audit_entry = AuditLogEntry(
                trace_id=trace_id,
                question=question,
                cypher="",
                raw_result={"error": str(e)},
                summary=f"查询失败: {str(e)}",
                user_id=user_id,
                session_id=session_id,
                execution_time_ms=execution_time_ms,
                row_count=0,
                error_message=str(e),
            )
            await pg.write_audit_log(audit_entry)
        except Exception:
            pass

        return {
            "summary": f"查询处理失败: {str(e)}",
            "raw_data": [],
            "columns": [],
            "cypher": "",
            "trace_id": trace_id,
            "execution_time_ms": execution_time_ms,
            "row_count": 0,
            "error": str(e),
        }


def build_query_response(result: dict[str, Any]) -> dict[str, Any]:
    """Build a WSMessage QueryResponse from a query result dict."""
    return {
        "type": "response",
        "payload": {
            "summary": result["summary"],
            "raw_data": result["raw_data"],
            "columns": result["columns"],
            "cypher": result["cypher"],
            "trace_id": result["trace_id"],
            "execution_time_ms": result["execution_time_ms"],
            "row_count": result["row_count"],
        },
        "trace_id": result["trace_id"],
        "timestamp": int(time.time() * 1000),
    }
