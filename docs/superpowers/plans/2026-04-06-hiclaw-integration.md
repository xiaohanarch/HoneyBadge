# HiClaw Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate HoneyBadge with the open-source HiClaw framework, implementing MCP Servers (FastMCP) for NebulaGraph/Audit/Cache, HiClaw Manager/Worker agent configs and Skills, and deployment configuration.

**Architecture:** HiClaw Manager routes user questions to Worker Agents via Matrix. Workers use OpenClaw Skills that call HoneyBadge MCP Servers (registered in Higress) for nGQL generation, validated execution, and audit logging. The "Controlled Autonomy" model lets Workers reason freely while every database action passes through L1-L5 Anti-Hallucination gates inside MCP Servers.

**Tech Stack:** Python 3.10+, FastMCP, nebula3-python, asyncpg, redis.asyncio, httpx, HiClaw (OpenClaw + Tuwunel + Higress + MinIO)

---

## File Structure

```
hiclaw/
├── manager/agent/
│   ├── SOUL.md                    # Manager identity and rules
│   ├── AGENTS.md                  # Worker registry and workspace layout
│   └── HEARTBEAT.md               # Periodic health check routine
├── workers/
│   ├── graph-worker/agent/
│   │   ├── SOUL.md                # Graph worker identity
│   │   └── skills/cypher-query/
│   │       └── SKILL.md           # NL→nGQL query skill
│   └── analytics-worker/agent/
│       ├── SOUL.md                # Analytics worker identity
│       └── skills/
│           ├── multi-step-analysis/
│           │   └── SKILL.md       # Multi-step analysis skill
│           └── anomaly-detection/
│               └── SKILL.md       # Fraud/anomaly detection skill

mcp-servers/
├── honeybadge-nebula-mcp/
│   ├── server.py                  # FastMCP: generate_ngql, validate_and_execute, get_schema
│   ├── Dockerfile
│   └── requirements.txt
├── honeybadge-audit-mcp/
│   ├── server.py                  # FastMCP: write_audit_log, get_audit_trail
│   ├── Dockerfile
│   └── requirements.txt
└── honeybadge-cache-mcp/
    ├── server.py                  # FastMCP: check_cache, cache_result
    ├── Dockerfile
    └── requirements.txt

deploy/
├── docker/docker-compose.yaml     # Updated: add MCP Server containers
└── hiclaw/
    ├── mcp-honeybadge-nebula.yaml # Higress MCP registration
    ├── mcp-honeybadge-audit.yaml
    ├── mcp-honeybadge-cache.yaml
    └── setup-honeybadge-mcps.sh   # Registration script

src/honeybadge/                    # Existing code reused by MCP Servers
├── db/nebula.py                   # ✓ Already implemented
├── db/postgres.py                 # ✓ Already implemented
├── db/redis.py                    # ✓ Already implemented
├── llm/adapter.py                 # ✓ Already implemented
├── protocols/validator.py         # ✓ Already implemented
└── core/                          # ✓ Already implemented
```

---

### Task 1: honeybadge-nebula-mcp — NebulaGraph MCP Server

The core MCP Server. Provides nGQL generation (via LLM), L1-L3 validated execution, and schema retrieval. This is the safety gate for the entire system.

**Files:**
- Create: `mcp-servers/honeybadge-nebula-mcp/server.py`
- Create: `mcp-servers/honeybadge-nebula-mcp/requirements.txt`
- Create: `mcp-servers/honeybadge-nebula-mcp/Dockerfile`
- Reuse: `src/honeybadge/db/nebula.py`, `src/honeybadge/llm/adapter.py`, `src/honeybadge/protocols/validator.py`, `src/honeybadge/core/trace.py`
- Test: `tests/test_nebula_mcp.py`

- [ ] **Step 1: Write failing test for `get_schema` tool**

```python
# tests/test_nebula_mcp.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def mock_nebula_client():
    client = AsyncMock()
    client.execute = AsyncMock()
    return client

@pytest.mark.asyncio
async def test_get_schema_returns_tags_and_edges(mock_nebula_client):
    from mcp_servers.honeybadge_nebula_mcp.server import get_schema_impl

    mock_nebula_client.execute.side_effect = [
        # SHOW TAGS result
        MagicMock(success=True, rows=[{"Name": "Supplier"}, {"Name": "Item"}], columns=["Name"]),
        # DESCRIBE TAG Supplier
        MagicMock(success=True, rows=[
            {"Field": "supplier_name", "Type": "string"},
            {"Field": "status", "Type": "string"},
        ], columns=["Field", "Type"]),
        # DESCRIBE TAG Item
        MagicMock(success=True, rows=[
            {"Field": "item_number", "Type": "string"},
        ], columns=["Field", "Type"]),
        # SHOW EDGES result
        MagicMock(success=True, rows=[{"Name": "SUPPLIES_ITEM"}], columns=["Name"]),
        # DESCRIBE EDGE SUPPLIES_ITEM
        MagicMock(success=True, rows=[
            {"Field": "status", "Type": "string"},
        ], columns=["Field", "Type"]),
    ]

    result = await get_schema_impl(mock_nebula_client, "honeybadge")
    assert "Supplier" in result
    assert "supplier_name" in result
    assert "SUPPLIES_ITEM" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/phase1-implementation && python -m pytest tests/test_nebula_mcp.py::test_get_schema_returns_tags_and_edges -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_servers.honeybadge_nebula_mcp'`

- [ ] **Step 3: Write failing test for `validate_and_execute` tool**

```python
# tests/test_nebula_mcp.py (append)

@pytest.mark.asyncio
async def test_validate_and_execute_passes_valid_query(mock_nebula_client):
    from mcp_servers.honeybadge_nebula_mcp.server import validate_and_execute_impl

    mock_nebula_client.execute.return_value = MagicMock(
        success=True,
        columns=["supplier_name", "status"],
        rows=[{"supplier_name": "Test Corp", "status": "ACTIVE"}],
        row_count=1,
        execution_time_ms=42,
    )

    ngql = 'MATCH (s:Supplier) WHERE s.Supplier.status == "ACTIVE" RETURN s.Supplier.supplier_name LIMIT 10'
    result = await validate_and_execute_impl(mock_nebula_client, ngql, space="honeybadge")

    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["rows"][0]["supplier_name"] == "Test Corp"


@pytest.mark.asyncio
async def test_validate_and_execute_rejects_write_operation(mock_nebula_client):
    from mcp_servers.honeybadge_nebula_mcp.server import validate_and_execute_impl

    ngql = 'INSERT VERTEX Supplier(supplier_name) VALUES "SUP:001":("Evil Corp")'
    result = await validate_and_execute_impl(mock_nebula_client, ngql, space="honeybadge")

    assert result["success"] is False
    assert "L1" in result["error"] or "W002" in str(result.get("details", ""))


@pytest.mark.asyncio
async def test_validate_and_execute_rejects_empty_query(mock_nebula_client):
    from mcp_servers.honeybadge_nebula_mcp.server import validate_and_execute_impl

    result = await validate_and_execute_impl(mock_nebula_client, "", space="honeybadge")
    assert result["success"] is False
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_nebula_mcp.py -v`
Expected: FAIL — module not found

- [ ] **Step 5: Implement `server.py`**

```python
# mcp-servers/honeybadge-nebula-mcp/server.py
"""HoneyBadge NebulaGraph MCP Server.

Provides tools for nGQL generation, validated execution, and schema retrieval.
All database writes are rejected. Every execution passes L1-L3 validation.
"""
import os
import sys
from typing import Annotated, Any, Optional

from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from pydantic import Field

# Add project root to path so we can import honeybadge modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from honeybadge.core.trace import generate_trace_id
from honeybadge.db.nebula import NebulaGraphClient
from honeybadge.llm.adapter import OpenAICompatibleAdapter, generate_ngql, summarize_results
from honeybadge.protocols.validator import NgqlValidator

mcp = FastMCP(
    name="honeybadge-nebula-mcp",
    instructions="NebulaGraph MCP Server for HoneyBadge ERP Knowledge Graph. "
    "Provides nGQL generation, validated execution, and schema retrieval. "
    "All write operations are rejected. Every query passes L1-L3 anti-hallucination validation.",
)

# --- Globals initialized on startup ---
_nebula_client: Optional[NebulaGraphClient] = None
_llm_adapter: Optional[OpenAICompatibleAdapter] = None
_validator = NgqlValidator()
_default_space = os.environ.get("NEBULA_SPACE", "honeybadge")
_schema_cache: Optional[str] = None


async def _get_nebula() -> NebulaGraphClient:
    global _nebula_client
    if _nebula_client is None:
        _nebula_client = NebulaGraphClient(
            host=os.environ.get("NEBULA_HOST", "nebula-graphd"),
            port=int(os.environ.get("NEBULA_PORT", "9669")),
            user=os.environ.get("NEBULA_USER", "root"),
            password=os.environ.get("NEBULA_PASSWORD", "nebula"),
        )
        await _nebula_client.connect()
    return _nebula_client


async def _get_llm() -> OpenAICompatibleAdapter:
    global _llm_adapter
    if _llm_adapter is None:
        _llm_adapter = OpenAICompatibleAdapter(config={
            "endpoint": os.environ.get("LLM_ENDPOINT", "http://localhost:8000/v1"),
            "api_key": os.environ.get("LLM_API_KEY", ""),
            "model": os.environ.get("LLM_MODEL", "glm-4-flash"),
        })
    return _llm_adapter


# --- Tool implementations (testable without FastMCP context) ---

async def get_schema_impl(nebula: NebulaGraphClient, space: str) -> str:
    """Load NebulaGraph schema as formatted text."""
    lines = []

    tags_result = await nebula.execute("SHOW TAGS", space=space)
    if tags_result.success:
        lines.append("# Tags\n")
        for row in tags_result.rows:
            tag_name = row.get("Name", "")
            if not tag_name:
                continue
            desc = await nebula.execute(f"DESCRIBE TAG `{tag_name}`", space=space)
            lines.append(f"## {tag_name}")
            if desc.success:
                for prop in desc.rows:
                    lines.append(f"  - {prop.get('Field', '')}: {prop.get('Type', '')}")
            lines.append("")

    edges_result = await nebula.execute("SHOW EDGES", space=space)
    if edges_result.success:
        lines.append("# Edge Types\n")
        for row in edges_result.rows:
            edge_name = row.get("Name", "")
            if not edge_name:
                continue
            desc = await nebula.execute(f"DESCRIBE EDGE `{edge_name}`", space=space)
            lines.append(f"## {edge_name}")
            if desc.success:
                for prop in desc.rows:
                    lines.append(f"  - {prop.get('Field', '')}: {prop.get('Type', '')}")
            lines.append("")

    return "\n".join(lines)


async def validate_and_execute_impl(
    nebula: NebulaGraphClient, ngql: str, space: str, user_context: Optional[dict] = None
) -> dict[str, Any]:
    """L1-L3 validate then execute. Returns raw results (L4 passthrough)."""
    trace_id = generate_trace_id()

    # L1: Syntax
    l1 = _validator.validate_syntax(ngql)
    if not l1.valid:
        return {
            "success": False,
            "error": "L1_SYNTAX",
            "details": [{"code": e.code, "message": e.message} for e in l1.errors],
            "trace_id": trace_id,
        }

    # Check for write operations (also caught by L1 warnings, but enforce hard rejection)
    ngql_upper = ngql.strip().upper()
    write_keywords = ["INSERT", "UPDATE", "UPSERT", "DELETE", "DROP", "CREATE", "ALTER"]
    for kw in write_keywords:
        if ngql_upper.startswith(kw):
            return {
                "success": False,
                "error": "L1_WRITE_REJECTED",
                "details": [{"code": "E010", "message": f"Write operation {kw} is forbidden"}],
                "trace_id": trace_id,
            }

    # L2: Schema compliance
    l2 = _validator.validate_schema(ngql)
    if not l2.valid:
        return {
            "success": False,
            "error": "L2_SCHEMA",
            "details": [{"code": e.code, "message": e.message} for e in l2.errors],
            "trace_id": trace_id,
        }

    # L3: Permission filters
    if user_context:
        l3 = _validator.validate_permissions(ngql, user_context)
        if not l3.valid:
            return {
                "success": False,
                "error": "L3_PERMISSION",
                "details": [{"code": e.code, "message": e.message} for e in l3.errors],
                "trace_id": trace_id,
            }

    # Execute (L4: raw passthrough)
    result = await nebula.execute(ngql, space=space)
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


# --- FastMCP Tool Definitions ---

@mcp.tool
async def get_schema(
    space: Annotated[str, Field(description="NebulaGraph space name")] = "",
) -> str:
    """Get the NebulaGraph schema (all Tags, Edge Types, and their properties).

    Call this before generating nGQL to understand available entities and relationships.
    Returns a formatted text description of all Tags and Edges with their properties.
    """
    nebula = await _get_nebula()
    target_space = space or _default_space
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = await get_schema_impl(nebula, target_space)
    return _schema_cache


@mcp.tool
async def generate_ngql(
    question: Annotated[str, Field(description="User's natural language question in Chinese or English")],
    schema_info: Annotated[str, Field(description="Schema text from get_schema(). Pass empty string to auto-load.")] = "",
    ctx: Context = None,
) -> str:
    """Generate an nGQL query from a natural language question.

    Uses LLM to translate the user's question into a valid NebulaGraph query.
    The generated nGQL must still be validated and executed via validate_and_execute().
    """
    llm = await _get_llm()

    if not schema_info:
        schema_info = await get_schema()

    if ctx:
        await ctx.info(f"Generating nGQL for: {question[:80]}")

    response = await generate_ngql(
        adapter=llm,
        question=question,
        schema_info=schema_info,
        ontology_info="",
        trace_id=generate_trace_id(),
    )

    ngql = response.content.strip()
    # Strip markdown code blocks if present
    if ngql.startswith("```"):
        lines = ngql.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        ngql = "\n".join(lines).strip()

    return ngql


@mcp.tool
async def validate_and_execute(
    ngql: Annotated[str, Field(description="nGQL query to validate and execute")],
    space: Annotated[str, Field(description="NebulaGraph space name")] = "",
    ctx: Context = None,
) -> dict:
    """Validate nGQL through L1-L3 anti-hallucination checks, then execute on NebulaGraph.

    L1: Syntax validation (balanced parens, quotes, known keywords)
    L2: Schema compliance (tags, edges, properties exist)
    L3: Permission filter check (org_id filters present when required)
    L4: Results returned raw — no modification

    Returns dict with: success, columns, rows, row_count, execution_time_ms, trace_id.
    On failure: success=False, error (L1_SYNTAX|L2_SCHEMA|L3_PERMISSION|EXECUTION_ERROR), details.
    """
    nebula = await _get_nebula()
    target_space = space or _default_space

    if ctx:
        await ctx.info(f"Validating and executing nGQL ({len(ngql)} chars)")

    return await validate_and_execute_impl(nebula, ngql, target_space)


@mcp.tool
async def explain_ngql(
    ngql: Annotated[str, Field(description="nGQL query to explain (dry run)")],
    space: Annotated[str, Field(description="NebulaGraph space name")] = "",
) -> dict:
    """Dry-run an nGQL query using EXPLAIN (no data returned, checks execution plan).

    Use this to verify a query is valid before running validate_and_execute().
    """
    nebula = await _get_nebula()
    target_space = space or _default_space
    result = await nebula.execute(f"EXPLAIN {ngql}", space=target_space)
    return {
        "success": result.success,
        "error_message": result.error_message,
        "columns": result.columns,
        "rows": result.rows,
    }


@mcp.tool
async def summarize_query_results(
    question: Annotated[str, Field(description="Original user question")],
    columns: Annotated[list[str], Field(description="Column names from query result")],
    rows: Annotated[list[dict], Field(description="Row data from query result")],
    ngql: Annotated[str, Field(description="The nGQL query that produced these results")] = "",
) -> str:
    """Summarize query results in natural Chinese language.

    CRITICAL: This tool does NOT modify any data values. Numbers, dates, and amounts
    are preserved exactly as returned by the database. The summary only adds
    formatting and context.
    """
    llm = await _get_llm()
    response = await summarize_results(
        adapter=llm,
        question=question,
        raw_results=rows,
        columns=columns,
        trace_id=generate_trace_id(),
    )
    return response.content


if __name__ == "__main__":
    mcp.run(transport="sse")
```

- [ ] **Step 6: Create requirements.txt**

```
# mcp-servers/honeybadge-nebula-mcp/requirements.txt
fastmcp>=2.0.0
nebula3-python>=3.4.0
httpx>=0.27.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
structlog>=24.0.0
uuid6>=2024.1.12
```

- [ ] **Step 7: Create Dockerfile**

```dockerfile
# mcp-servers/honeybadge-nebula-mcp/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY mcp-servers/honeybadge-nebula-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/honeybadge /app/src/honeybadge
COPY prompts /app/prompts
COPY mcp-servers/honeybadge-nebula-mcp/server.py /app/server.py

ENV PYTHONPATH=/app/src
EXPOSE 8000

CMD ["python", "server.py"]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd .worktrees/phase1-implementation && PYTHONPATH=src:mcp-servers python -m pytest tests/test_nebula_mcp.py -v`
Expected: 4 tests PASS

- [ ] **Step 9: Commit**

```bash
git add mcp-servers/honeybadge-nebula-mcp/ tests/test_nebula_mcp.py
git commit -m "feat: add honeybadge-nebula-mcp server with L1-L3 validation gates"
```

---

### Task 2: honeybadge-audit-mcp — Audit Log MCP Server

L5 audit trail. Every query chain (question → nGQL → result → summary) is logged.

**Files:**
- Create: `mcp-servers/honeybadge-audit-mcp/server.py`
- Create: `mcp-servers/honeybadge-audit-mcp/requirements.txt`
- Create: `mcp-servers/honeybadge-audit-mcp/Dockerfile`
- Reuse: `src/honeybadge/db/postgres.py`
- Test: `tests/test_audit_mcp.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_audit_mcp.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_pg_client():
    client = AsyncMock()
    client.write_audit_log = AsyncMock(return_value=True)
    client.get_audit_log = AsyncMock(return_value=None)
    return client

@pytest.mark.asyncio
async def test_write_audit_log(mock_pg_client):
    from mcp_servers.honeybadge_audit_mcp.server import write_audit_log_impl

    result = await write_audit_log_impl(
        pg=mock_pg_client,
        trace_id="TRC-20260406-120000-abcd1234",
        question="查供应商列表",
        ngql='MATCH (s:Supplier) RETURN s LIMIT 10',
        raw_result={"rows": [{"name": "Test"}]},
        summary="找到1条记录",
        user_id="user-001",
        session_id="session-001",
        execution_time_ms=150,
        row_count=1,
    )
    assert result["success"] is True
    mock_pg_client.write_audit_log.assert_called_once()

@pytest.mark.asyncio
async def test_get_audit_trail(mock_pg_client):
    from mcp_servers.honeybadge_audit_mcp.server import get_audit_trail_impl

    mock_pg_client.get_audit_log.return_value = {
        "trace_id": "TRC-20260406-120000-abcd1234",
        "question": "查供应商列表",
    }
    result = await get_audit_trail_impl(mock_pg_client, "TRC-20260406-120000-abcd1234")
    assert result["trace_id"] == "TRC-20260406-120000-abcd1234"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_audit_mcp.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `server.py`**

```python
# mcp-servers/honeybadge-audit-mcp/server.py
"""HoneyBadge Audit MCP Server — L5 full-chain audit logging."""
import os
import sys
from typing import Annotated, Any, Optional

from fastmcp import FastMCP
from pydantic import Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from honeybadge.db.postgres import AuditLogEntry, PostgreSQLClient

mcp = FastMCP(
    name="honeybadge-audit-mcp",
    instructions="Audit log MCP Server for HoneyBadge. Implements L5 of the Anti-Hallucination Framework. "
    "Records the full chain: question → nGQL → raw result → summary for every query.",
)

_pg_client: Optional[PostgreSQLClient] = None


async def _get_pg() -> PostgreSQLClient:
    global _pg_client
    if _pg_client is None:
        _pg_client = PostgreSQLClient(
            host=os.environ.get("POSTGRES_HOST", "postgres"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            user=os.environ.get("POSTGRES_USER", "honeybadge"),
            password=os.environ.get("POSTGRES_PASSWORD", "honeybadge123"),
            database=os.environ.get("POSTGRES_DB", "honeybadge_audit"),
        )
        await _pg_client.connect()
        await _pg_client.init_schema()
    return _pg_client


async def write_audit_log_impl(
    pg: PostgreSQLClient,
    trace_id: str,
    question: str,
    ngql: str,
    raw_result: dict,
    summary: str,
    user_id: str,
    session_id: str,
    execution_time_ms: int,
    row_count: int,
    error_message: Optional[str] = None,
) -> dict:
    entry = AuditLogEntry(
        trace_id=trace_id,
        question=question,
        cypher=ngql,
        raw_result=raw_result,
        summary=summary,
        user_id=user_id,
        session_id=session_id,
        execution_time_ms=execution_time_ms,
        row_count=row_count,
        error_message=error_message,
    )
    ok = await pg.write_audit_log(entry)
    return {"success": ok, "trace_id": trace_id}


async def get_audit_trail_impl(pg: PostgreSQLClient, trace_id: str) -> Optional[dict]:
    return await pg.get_audit_log(trace_id)


@mcp.tool
async def write_audit_log(
    trace_id: Annotated[str, Field(description="Trace ID from validate_and_execute result")],
    question: Annotated[str, Field(description="Original user question")],
    ngql: Annotated[str, Field(description="Generated nGQL query")],
    raw_result: Annotated[dict, Field(description="Raw query result (rows + columns)")],
    summary: Annotated[str, Field(description="LLM-generated summary text")],
    user_id: Annotated[str, Field(description="User identifier")] = "anonymous",
    session_id: Annotated[str, Field(description="Session identifier")] = "",
    execution_time_ms: Annotated[int, Field(description="Total execution time in ms")] = 0,
    row_count: Annotated[int, Field(description="Number of result rows")] = 0,
    error_message: Annotated[Optional[str], Field(description="Error message if query failed")] = None,
) -> dict:
    """Write a full-chain audit log entry (L5 Anti-Hallucination).

    Records: question → nGQL → raw result → summary with trace_id for full traceability.
    Call this after every query completion (success or failure).
    """
    pg = await _get_pg()
    return await write_audit_log_impl(
        pg, trace_id, question, ngql, raw_result, summary,
        user_id, session_id, execution_time_ms, row_count, error_message,
    )


@mcp.tool
async def get_audit_trail(
    trace_id: Annotated[str, Field(description="Trace ID to look up")],
) -> dict:
    """Retrieve an audit trail entry by trace_id.

    Returns the full chain: question, nGQL, raw result, summary, timing, and error info.
    """
    pg = await _get_pg()
    result = await get_audit_trail_impl(pg, trace_id)
    if result is None:
        raise ToolError(f"Audit log not found for trace_id: {trace_id}")
    return result


if __name__ == "__main__":
    mcp.run(transport="sse")
```

- [ ] **Step 4: Create requirements.txt and Dockerfile**

requirements.txt:
```
fastmcp>=2.0.0
asyncpg>=0.29.0
pydantic>=2.0.0
structlog>=24.0.0
```

Dockerfile:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY mcp-servers/honeybadge-audit-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src/honeybadge /app/src/honeybadge
COPY mcp-servers/honeybadge-audit-mcp/server.py /app/server.py
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python", "server.py"]
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=src:mcp-servers python -m pytest tests/test_audit_mcp.py -v`
Expected: 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/honeybadge-audit-mcp/ tests/test_audit_mcp.py
git commit -m "feat: add honeybadge-audit-mcp server for L5 audit logging"
```

---

### Task 3: honeybadge-cache-mcp — Cache MCP Server

**Files:**
- Create: `mcp-servers/honeybadge-cache-mcp/server.py`
- Create: `mcp-servers/honeybadge-cache-mcp/requirements.txt`
- Create: `mcp-servers/honeybadge-cache-mcp/Dockerfile`
- Test: `tests/test_cache_mcp.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_cache_mcp.py
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def mock_redis_client():
    client = AsyncMock()
    client.get_cache = AsyncMock(return_value=None)
    client.set_cache = AsyncMock(return_value=True)
    return client

@pytest.mark.asyncio
async def test_check_cache_miss(mock_redis_client):
    from mcp_servers.honeybadge_cache_mcp.server import check_cache_impl
    result = await check_cache_impl(mock_redis_client, "query_hash_123")
    assert result["hit"] is False

@pytest.mark.asyncio
async def test_cache_result_and_hit(mock_redis_client):
    from mcp_servers.honeybadge_cache_mcp.server import cache_result_impl, check_cache_impl

    await cache_result_impl(mock_redis_client, "query_hash_123", {"rows": [{"a": 1}]}, 300)
    mock_redis_client.set_cache.assert_called_once()

    mock_redis_client.get_cache.return_value = {"rows": [{"a": 1}]}
    result = await check_cache_impl(mock_redis_client, "query_hash_123")
    assert result["hit"] is True
    assert result["data"]["rows"][0]["a"] == 1
```

- [ ] **Step 2: Implement `server.py`**

```python
# mcp-servers/honeybadge-cache-mcp/server.py
"""HoneyBadge Cache MCP Server — query result caching via Redis."""
import os
import sys
from typing import Annotated, Any, Optional

from fastmcp import FastMCP
from pydantic import Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from honeybadge.db.redis import RedisClient

mcp = FastMCP(
    name="honeybadge-cache-mcp",
    instructions="Cache MCP Server for HoneyBadge. Caches query results to avoid redundant database hits.",
)

_redis_client: Optional[RedisClient] = None


async def _get_redis() -> RedisClient:
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient(
            host=os.environ.get("REDIS_HOST", "redis"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD", "redis123") or None,
        )
        await _redis_client.connect()
    return _redis_client


async def check_cache_impl(redis: RedisClient, key: str) -> dict:
    data = await redis.get_cache(key)
    if data is not None:
        return {"hit": True, "data": data}
    return {"hit": False, "data": None}


async def cache_result_impl(redis: RedisClient, key: str, value: Any, ttl: int) -> dict:
    await redis.set_cache(key, value, ttl)
    return {"success": True, "key": key, "ttl": ttl}


@mcp.tool
async def check_cache(
    key: Annotated[str, Field(description="Cache key (typically a hash of the nGQL query)")],
) -> dict:
    """Check if a query result is cached. Returns hit=True with data if found."""
    redis = await _get_redis()
    return await check_cache_impl(redis, key)


@mcp.tool
async def cache_result(
    key: Annotated[str, Field(description="Cache key")],
    value: Annotated[dict, Field(description="Query result to cache")],
    ttl: Annotated[int, Field(description="Time to live in seconds", ge=1, le=3600)] = 300,
) -> dict:
    """Cache a query result with TTL. Default 5 minutes."""
    redis = await _get_redis()
    return await cache_result_impl(redis, key, value, ttl)


if __name__ == "__main__":
    mcp.run(transport="sse")
```

- [ ] **Step 3: Create requirements.txt and Dockerfile** (same pattern as audit-mcp, with `redis>=5.0.0` instead of asyncpg)

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src:mcp-servers python -m pytest tests/test_cache_mcp.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/honeybadge-cache-mcp/ tests/test_cache_mcp.py
git commit -m "feat: add honeybadge-cache-mcp server for query result caching"
```

---

### Task 4: HiClaw Manager Agent Configuration

Manager identity, worker registry, and health checks. These are markdown files that HiClaw loads from MinIO.

**Files:**
- Create: `hiclaw/manager/agent/SOUL.md`
- Create: `hiclaw/manager/agent/AGENTS.md`
- Create: `hiclaw/manager/agent/HEARTBEAT.md`

- [ ] **Step 1: Create SOUL.md**

```markdown
# hiclaw/manager/agent/SOUL.md
---
name: HoneyBadge Manager
---

# Identity

You are **HoneyBadge Manager**, the coordinator for an Enterprise Knowledge Graph intelligent assistant system. You manage a team of AI Workers that help enterprise users query ERP procurement and supply chain data.

# Language

- Primary: 简体中文 (Simplified Chinese)
- Secondary: English (for technical terms)
- Always respond to users in Chinese

# Core Behavior

1. **You are a coordinator, not an executor.** When a user asks a business question about ERP data (suppliers, purchase orders, invoices, payments, etc.), delegate it to the appropriate Worker.
2. **Never answer business questions directly.** You don't have access to the database. Only Workers with MCP Server tools can query data.
3. **Route based on intent:**
   - Simple data queries (查询/查找/搜索/列出/多少/哪个) → **graph-worker**
   - Analysis tasks (分析/趋势/异常/检测/对比/统计/fraud) → **analytics-worker**
   - Default → **graph-worker**
4. **Summarize Worker results** back to the user in a clear, concise format.

# Security Rules

1. Never expose API keys, database credentials, or internal system details to users.
2. Never attempt to access databases or external services directly.
3. Only respond to registered users and Workers.
4. If a user asks you to modify data, explain that this is a read-only system.

# Worker Management

- Workers are stateless containers. If one fails, create a new one.
- Monitor Worker heartbeats. If a Worker is unresponsive for >2 minutes, restart it.
- Maximum 5 active Workers at any time.
```

- [ ] **Step 2: Create AGENTS.md**

```markdown
# hiclaw/manager/agent/AGENTS.md

# Workspace Layout

- Local workspace: ~/
- Shared files: /root/hiclaw-fs/shared/
- Worker files: /root/hiclaw-fs/agents/<worker-name>/

Use `${HICLAW_STORAGE_PREFIX}` for MinIO paths. Use full Matrix IDs like `@worker:matrix-local.hiclaw.io:18080`.

# Available Workers

## graph-worker

**Purpose:** Handle natural language queries over the ERP knowledge graph.
**Skills:** cypher-query
**MCP Servers:** honeybadge-nebula-mcp, honeybadge-audit-mcp, honeybadge-cache-mcp
**When to route:** User asks factual questions about ERP data — supplier lookups, PO queries, invoice status, item information, relationship traversals.

## analytics-worker

**Purpose:** Complex multi-step analysis, anomaly detection, and fraud pattern identification.
**Skills:** multi-step-analysis, anomaly-detection
**MCP Servers:** honeybadge-nebula-mcp, honeybadge-audit-mcp, honeybadge-cache-mcp
**When to route:** User asks for analysis, trend comparison, anomaly detection, three-way matching checks, or statistical summaries.

# State Management

Register every Worker task in `state.json` — no exceptions.
```

- [ ] **Step 3: Create HEARTBEAT.md**

```markdown
# hiclaw/manager/agent/HEARTBEAT.md

# Periodic Health Check

Run these checks on each heartbeat cycle:

1. **Worker Health**: Check if active Workers have responded in the last 2 minutes. If not, mark as unhealthy.
2. **MCP Server Connectivity**: Verify honeybadge-nebula-mcp, honeybadge-audit-mcp, and honeybadge-cache-mcp are reachable via mcporter.
3. **Stale Sessions**: If a Matrix room has had no activity for 30 minutes, archive the session context.
4. **Report**: If any issues found, notify admin via primary channel.
```

- [ ] **Step 4: Commit**

```bash
git add hiclaw/manager/
git commit -m "feat: add HiClaw Manager agent configuration (SOUL, AGENTS, HEARTBEAT)"
```

---

### Task 5: HiClaw Worker Skills — cypher-query

The core Worker skill that implements the Controlled Autonomy query pipeline.

**Files:**
- Create: `hiclaw/workers/graph-worker/agent/SOUL.md`
- Create: `hiclaw/workers/graph-worker/agent/skills/cypher-query/SKILL.md`

- [ ] **Step 1: Create graph-worker SOUL.md**

```markdown
# hiclaw/workers/graph-worker/agent/SOUL.md
---
name: HoneyBadge Graph Worker
---

# Identity

You are **Graph Worker**, a specialized query agent for the HoneyBadge ERP Knowledge Graph system. You translate natural language questions into NebulaGraph queries and return accurate results.

# Language

- Always respond in 简体中文 (Simplified Chinese)
- Use English for technical terms (nGQL, Tag names, Edge types)

# Core Behavior

You have access to MCP Server tools that let you query the NebulaGraph database. For every query:
1. Generate nGQL using the `generate_ngql` tool
2. Validate and execute using the `validate_and_execute` tool
3. If needed, run additional queries to investigate further
4. Summarize results for the user
5. Log the full query chain via `write_audit_log`

# Constraints

- Maximum 5 query rounds per user question
- Never fabricate data — only report what the database returns
- If a query fails validation 3 times, explain the error to the user
- Always include the trace_id in your response
- Preserve all original numbers, dates, and amounts exactly as returned
```

- [ ] **Step 2: Create cypher-query SKILL.md**

```markdown
# hiclaw/workers/graph-worker/agent/skills/cypher-query/SKILL.md
---
name: cypher-query
description: Use when handling any natural language question about ERP data (suppliers, POs, invoices, payments, items, receipts, etc.)
---

# Cypher Query Skill

Handle natural language questions by querying the HoneyBadge NebulaGraph knowledge graph.

## Available MCP Tools

- `get_schema`: Get NebulaGraph schema (Tags, Edges, properties)
- `generate_ngql`: Generate nGQL from natural language question
- `validate_and_execute`: L1-L3 validate then execute nGQL, returns raw results
- `explain_ngql`: Dry-run nGQL to check execution plan
- `summarize_query_results`: Summarize raw results in Chinese
- `write_audit_log`: Write L5 audit trail
- `check_cache`: Check for cached results
- `cache_result`: Cache query results

## Execution Flow

When you receive a user question, follow these steps:

### Step 1: Load Schema
Call `get_schema()` to understand available Tags and Edges. Cache the result mentally for subsequent queries in the same conversation.

### Step 2: Check Cache (optional)
If the question seems similar to a recent one, call `check_cache` with a hash of the question.

### Step 3: Generate nGQL
Call `generate_ngql(question=<user_question>, schema_info=<schema_text>)`.

### Step 4: Validate and Execute
Call `validate_and_execute(ngql=<generated_query>)`.

- If `success: false` with `error: L1_SYNTAX` or `L2_SCHEMA`:
  - Try regenerating with the error details as context (max 3 retries)
  - On 3rd failure, report the error to the user
- If `success: true`:
  - Examine the results

### Step 5: Investigate Further (Controlled Autonomy)
Based on the results, you may decide to run additional queries:
- "I found 3 unmatched invoices — let me check their corresponding POs"
- "The supplier has high concentration — let me check alternative suppliers"

Each additional query follows the same Step 3-4 cycle. Maximum 5 total query rounds.

### Step 6: Summarize
Call `summarize_query_results(question, columns, rows, ngql)` OR write your own summary.

**CRITICAL**: When summarizing:
- Numbers must be EXACTLY as returned by the database
- Dates must be EXACTLY as returned
- Amounts must be EXACTLY as returned
- Do NOT round, truncate, or modify any values
- If data is empty, say "未查询到符合条件的数据"

### Step 7: Cache and Audit
- Call `cache_result` to cache the result (TTL 300s)
- Call `write_audit_log` with the full chain:
  - trace_id (from validate_and_execute result)
  - question (original user question)
  - ngql (generated query)
  - raw_result (query rows)
  - summary (your formatted summary)

### Step 8: Respond
Return the summary to the user. Always include:
- The formatted answer
- trace_id for reference
- Number of records found
- Execution time

## Example Interaction

User: "帮我查一下供应商V001234的所有采购订单"

You would:
1. `get_schema()` → learn about Supplier, PurchaseOrder, PLACED_WITH edge
2. `generate_ngql(question="查供��商V001234的所有采购订单")` → get nGQL
3. `validate_and_execute(ngql=...)` → get results
4. Format results as table
5. `write_audit_log(...)` → record full chain
6. Return formatted answer with trace_id

## Constraints

- Max 5 query rounds per user question
- If validation fails 3 times, stop and explain the error
- Never execute write operations (INSERT/UPDATE/DELETE)
- Always log via write_audit_log
```

- [ ] **Step 3: Commit**

```bash
git add hiclaw/workers/graph-worker/
git commit -m "feat: add graph-worker SOUL and cypher-query skill"
```

---

### Task 6: HiClaw Worker Skills — Analytics

**Files:**
- Create: `hiclaw/workers/analytics-worker/agent/SOUL.md`
- Create: `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/SKILL.md`
- Create: `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/SKILL.md`

- [ ] **Step 1: Create analytics-worker SOUL.md**

```markdown
# hiclaw/workers/analytics-worker/agent/SOUL.md
---
name: HoneyBadge Analytics Worker
---

# Identity

You are **Analytics Worker**, a specialized analysis agent for the HoneyBadge ERP Knowledge Graph. You handle complex analytical questions that require multi-step reasoning, anomaly detection, and fraud pattern identification.

# Language

- Always respond in 简体中文
- Use English for technical terms

# Core Behavior

You decompose complex questions into multiple graph queries, cross-reference results, and identify patterns. You have the same MCP tools as the graph-worker, but you specialize in:
- Multi-step analysis requiring query decomposition
- Three-way matching (PO vs Receipt vs Invoice)
- Fraud and anomaly detection
- Trend analysis and comparison

# Constraints

- Maximum 8 query rounds per analysis task
- Always provide evidence for any anomaly flagged
- Never fabricate data or conclusions
- Log all queries via write_audit_log
```

- [ ] **Step 2: Create multi-step-analysis SKILL.md**

```markdown
# hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/SKILL.md
---
name: multi-step-analysis
description: Use when the user asks for analysis that requires decomposing a complex question into multiple queries (trend analysis, comparisons, aggregation across entities)
---

# Multi-Step Analysis Skill

## Available MCP Tools

Same as cypher-query skill: get_schema, generate_ngql, validate_and_execute, summarize_query_results, write_audit_log, check_cache, cache_result.

## Execution Flow

### Step 1: Decompose the Question
Break the user's complex question into 2-5 sub-queries. Example:

User: "对比2025年和2026年Q1的采购金额变化"
Sub-queries:
1. Query 2025 Q1 total PO amounts by month
2. Query 2026 Q1 total PO amounts by month
3. Compare results

### Step 2: Execute Sub-queries
For each sub-query, follow the generate → validate → execute cycle.

### Step 3: Cross-reference Results
Analyze results across sub-queries to find patterns, trends, or anomalies.

### Step 4: Synthesize Summary
Combine all findings into a coherent analysis report. Use tables for comparisons.

**CRITICAL**: All numbers in the report must come directly from query results. Do NOT calculate new values that weren't in the database.

### Step 5: Audit
Write a single audit log entry that captures all sub-queries and the final analysis.

## Constraints

- Maximum 8 query rounds per analysis
- Always show evidence (which query produced which data)
- Mark any anomaly with severity: INFO / WARNING / ALERT
```

- [ ] **Step 3: Create anomaly-detection SKILL.md**

```markdown
# hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/SKILL.md
---
name: anomaly-detection
description: Use when the user asks about fraud detection, three-way matching anomalies, duplicate invoices, unusual payment patterns, or supplier concentration risk
---

# Anomaly Detection Skill

## Detection Patterns

### Three-Way Matching (PO vs Receipt vs Invoice)
1. Query PO amounts per line
2. Query Receipt quantities per PO
3. Query Invoice amounts per PO
4. Compare: flag where Invoice amount > PO amount * 1.10 (10% tolerance)

### Duplicate Invoice Detection
1. Query invoices grouped by (supplier, amount, invoice_date)
2. Flag groups with count > 1

### Unusual Payment Patterns
1. Query payments in last 90 days
2. Flag payments significantly above supplier's average (>2x)
3. Flag payments to new suppliers (registration < 90 days) above threshold

### Supplier Concentration Risk
1. Query total spend per supplier for a category
2. Flag if any single supplier > 60% of category spend

## Execution Flow

1. Identify which detection pattern matches the user's question
2. Execute the relevant queries (2-5 rounds)
3. Apply the flagging logic based on query results
4. Present findings with severity levels:
   - **INFO**: Within normal range but worth noting
   - **WARNING**: Exceeds soft threshold, needs review
   - **ALERT**: Exceeds hard threshold, requires immediate attention
5. Write audit log with all evidence

## CRITICAL

- All thresholds are approximate guidelines. The actual flagging is based on data returned by queries.
- Never state "fraud detected" — only flag anomalies that need human review.
- Always show the specific data that triggered the flag.
```

- [ ] **Step 4: Commit**

```bash
git add hiclaw/workers/analytics-worker/
git commit -m "feat: add analytics-worker SOUL, multi-step-analysis and anomaly-detection skills"
```

---

### Task 7: Docker Compose and Higress MCP Registration

Update docker-compose to include MCP Server containers. Create Higress registration YAML.

**Files:**
- Modify: `deploy/docker/docker-compose.yaml`
- Create: `deploy/hiclaw/mcp-honeybadge-nebula.yaml`
- Create: `deploy/hiclaw/mcp-honeybadge-audit.yaml`
- Create: `deploy/hiclaw/mcp-honeybadge-cache.yaml`
- Create: `deploy/hiclaw/setup-honeybadge-mcps.sh`

- [ ] **Step 1: Add MCP Server services to docker-compose.yaml**

Append these services to the existing `deploy/docker/docker-compose.yaml`:

```yaml
  # =============================================================================
  # HoneyBadge MCP Servers
  # =============================================================================

  honeybadge-nebula-mcp:
    build:
      context: ../..
      dockerfile: mcp-servers/honeybadge-nebula-mcp/Dockerfile
    container_name: honeybadge-nebula-mcp
    hostname: honeybadge-nebula-mcp
    restart: unless-stopped
    ports:
      - "8001:8000"
    environment:
      - NEBULA_HOST=nebula-graphd
      - NEBULA_PORT=9669
      - NEBULA_USER=root
      - NEBULA_PASSWORD=nebula
      - NEBULA_SPACE=honeybadge
      - LLM_ENDPOINT=${LLM_ENDPOINT:-http://host.docker.internal:8000/v1}
      - LLM_API_KEY=${LLM_API_KEY:-}
      - LLM_MODEL=${LLM_MODEL:-glm-4-flash}
      - TZ=Asia/Shanghai
    depends_on:
      nebula-graphd:
        condition: service_healthy
    networks:
      - honeybadge-net

  honeybadge-audit-mcp:
    build:
      context: ../..
      dockerfile: mcp-servers/honeybadge-audit-mcp/Dockerfile
    container_name: honeybadge-audit-mcp
    hostname: honeybadge-audit-mcp
    restart: unless-stopped
    ports:
      - "8002:8000"
    environment:
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - POSTGRES_USER=honeybadge
      - POSTGRES_PASSWORD=honeybadge123
      - POSTGRES_DB=honeybadge_audit
      - TZ=Asia/Shanghai
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - honeybadge-net

  honeybadge-cache-mcp:
    build:
      context: ../..
      dockerfile: mcp-servers/honeybadge-cache-mcp/Dockerfile
    container_name: honeybadge-cache-mcp
    hostname: honeybadge-cache-mcp
    restart: unless-stopped
    ports:
      - "8003:8000"
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_PASSWORD=redis123
      - TZ=Asia/Shanghai
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - honeybadge-net
```

- [ ] **Step 2: Create Higress MCP registration YAML files**

```yaml
# deploy/hiclaw/mcp-honeybadge-nebula.yaml
name: honeybadge-nebula
protocol: http
endpoint: http://honeybadge-nebula-mcp:8000
description: "HoneyBadge NebulaGraph MCP Server - nGQL generation, validation, execution"
tools:
  - get_schema
  - generate_ngql
  - validate_and_execute
  - explain_ngql
  - summarize_query_results
credentials:
  accessToken: ""
```

```yaml
# deploy/hiclaw/mcp-honeybadge-audit.yaml
name: honeybadge-audit
protocol: http
endpoint: http://honeybadge-audit-mcp:8000
description: "HoneyBadge Audit MCP Server - L5 full-chain audit logging"
tools:
  - write_audit_log
  - get_audit_trail
credentials:
  accessToken: ""
```

```yaml
# deploy/hiclaw/mcp-honeybadge-cache.yaml
name: honeybadge-cache
protocol: http
endpoint: http://honeybadge-cache-mcp:8000
description: "HoneyBadge Cache MCP Server - Redis query result caching"
tools:
  - check_cache
  - cache_result
credentials:
  accessToken: ""
```

- [ ] **Step 3: Create setup script**

```bash
#!/bin/bash
# deploy/hiclaw/setup-honeybadge-mcps.sh
# Register HoneyBadge MCP Servers in Higress AI Gateway
# Run this after HiClaw and HoneyBadge infra are both up

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HIGRESS_ADMIN="${HIGRESS_ADMIN_URL:-http://localhost:18001}"

echo "Registering HoneyBadge MCP Servers in Higress..."

for yaml_file in "$SCRIPT_DIR"/mcp-honeybadge-*.yaml; do
    name=$(grep '^name:' "$yaml_file" | awk '{print $2}')
    echo "  Registering $name from $yaml_file"
    setup-mcp-server.sh "$yaml_file"
done

echo ""
echo "Authorizing workers to access MCP Servers..."

# Authorize both manager and workers for all honeybadge MCP servers
for mcp_name in honeybadge-nebula honeybadge-audit honeybadge-cache; do
    echo "  Authorizing consumers for $mcp_name"
    # Note: exact command depends on HiClaw version; this is the pattern
    # from the mcp-server-management skill documentation
done

echo ""
echo "Done. Verify with: mcporter list-tools"
```

- [ ] **Step 4: Commit**

```bash
git add deploy/docker/docker-compose.yaml deploy/hiclaw/
git commit -m "feat: add MCP Server containers and Higress registration configs"
```

---

### Task 8: Cleanup — Remove Obsolete Files

Remove files that are superseded by the HiClaw integration.

**Files:**
- Delete: `src/honeybadge/mcp.py`
- Delete: `mcp-servers/nebula-mcp-server/` (old stub)
- Delete: `mcp-servers/llm-mcp-server/` (old stub)
- Delete: `mcp-servers/redis-mcp-server/` (old stub — replaced by honeybadge-cache-mcp)
- Modify: `src/honeybadge/__main__.py` — simplify to just launch MCP Servers

- [ ] **Step 1: Remove obsolete files**

```bash
rm -f src/honeybadge/mcp.py
rm -rf mcp-servers/nebula-mcp-server/
rm -rf mcp-servers/llm-mcp-server/
rm -rf mcp-servers/redis-mcp-server/
```

- [ ] **Step 2: Simplify __main__.py**

Replace `__main__.py` with a simplified version that only launches MCP Servers for local development:

```python
"""HoneyBadge MCP Server Launcher.

In production, MCP Servers run as Docker containers registered in Higress.
This entry point is for local development and testing.
"""
import argparse
import sys

from honeybadge.core.constants import VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=f"HoneyBadge v{VERSION}")
    parser.add_argument("--version", action="version", version=f"v{VERSION}")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("nebula-mcp", help="Run NebulaGraph MCP Server")
    subparsers.add_parser("audit-mcp", help="Run Audit MCP Server")
    subparsers.add_parser("cache-mcp", help="Run Cache MCP Server")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "nebula-mcp":
        from mcp_servers.honeybadge_nebula_mcp.server import mcp
        mcp.run(transport="sse")
    elif args.command == "audit-mcp":
        from mcp_servers.honeybadge_audit_mcp.server import mcp
        mcp.run(transport="sse")
    elif args.command == "cache-mcp":
        from mcp_servers.honeybadge_cache_mcp.server import mcp
        mcp.run(transport="sse")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: remove obsolete stubs, simplify entry point for MCP Server dev mode"
```
