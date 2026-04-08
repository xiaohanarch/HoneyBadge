# HoneyBadge HiClaw Integration Design

## Overview

HoneyBadge integrates with the open-source [HiClaw](https://github.com/alibaba/hiclaw) framework for Agent orchestration. HiClaw provides Manager-Worker multi-agent coordination via Matrix protocol, with Higress as the AI gateway and MinIO for state management.

The key design principle is **Controlled Autonomy**: Worker Agents retain full LLM reasoning capability (multi-step queries, association discovery, flexible exploration) while every external action (nGQL execution, data access) is gated by the Anti-Hallucination Framework (L1-L5) implemented inside MCP Servers.

## Architecture

```
User ──→ Element Web / Custom Frontend
              │ (Matrix Protocol)
              ▼
         Tuwunel (Matrix Server, port 6167)
              │
              ▼
    ┌─────────────────────────┐
    │  HiClaw Manager Agent   │  OpenClaw runtime
    │  - SOUL.md              │  Routes tasks to Workers
    │  - AGENTS.md            │  Creates/stops Workers
    │  - Skills:              │  Heartbeat monitoring
    │    worker-management    │
    │    mcp-server-management│
    └────────┬────────────────┘
             │ @mention in Matrix Room
             ▼
    ┌─────────────────────────┐
    │  HiClaw Worker Agents   │  OpenClaw containers (stateless)
    │                         │
    │  graph-worker:          │  Skills: cypher-query
    │    - Multi-step nGQL    │  Config pulled from MinIO
    │    - Association explore│
    │                         │
    │  analytics-worker:      │  Skills: multi-step-analysis
    │    - Fraud detection    │  anomaly-detection
    │    - Three-way matching │
    └────────┬────────────────┘
             │ mcporter CLI via Higress (port 8080)
             ▼
    ┌─────────────────────────────────────────────┐
    │  MCP Servers (registered in Higress)         │
    │                                              │
    │  honeybadge-nebula-mcp (Python, FastMCP)     │
    │    Tools:                                    │
    │    - generate_ngql(question, schema)         │
    │    - validate_and_execute(ngql)  ← L1-L3     │
    │    - get_schema()                            │
    │    - explain_ngql(ngql)                      │
    │                                              │
    │  honeybadge-audit-mcp (Python, FastMCP)      │
    │    Tools:                                    │
    │    - write_audit_log(trace_id, ...)  ← L5    │
    │    - get_audit_trail(trace_id)               │
    │                                              │
    │  honeybadge-cache-mcp (Python, FastMCP)      │
    │    Tools:                                    │
    │    - check_cache(question_hash)              │
    │    - cache_result(key, value, ttl)           │
    └────────┬────────────────────────────────────┘
             │
             ▼
    ┌─────────────────────────┐
    │  Infrastructure          │
    │  - NebulaGraph 3.8       │
    │  - PostgreSQL 16         │
    │  - Redis 7               │
    │  - MinIO (HiClaw state)  │
    └──────────────────────────┘
```

## Controlled Autonomy Model

### What the Agent CAN do (autonomy)

- Decide to query multiple times based on intermediate results
- Discover unexpected associations between entities
- Choose which schema areas to explore
- Combine results from multiple queries into coherent insights
- Decide query strategy based on question complexity

### What the Agent CANNOT do (control)

- Execute any nGQL without L1-L3 validation passing
- Modify or fabricate query results (L4: raw passthrough)
- Skip audit logging (L5: every tool call is logged)
- Access databases directly (only through MCP Server tools)
- Execute write operations (MCP Server rejects INSERT/UPDATE/DELETE)

### How it works

```
Agent reasoning (free):
  "User asks about supplier payment anomalies.
   I should: 1) check three-way matching 2) look at payment history"

Agent action (gated):
  → call generate_ngql("查供应商三单匹配情况")
    → MCP Server calls LLM, returns nGQL
  → call validate_and_execute(ngql)
    → L1: syntax check ✓
    → L2: schema compliance ✓
    → L3: permission filter ✓
    → execute on NebulaGraph
    → return raw results + write audit log

Agent reasoning (free):
  "Found 3 mismatches. Let me investigate these suppliers further."

Agent action (gated):
  → call generate_ngql("查这3个供应商的历史付款记录")
  → call validate_and_execute(ngql)  ... (same validation)

Agent final:
  → summarize all results for user (L4: numbers unchanged)
  → call write_audit_log(full chain)
```

## Component Specifications

### 1. Manager Agent Configuration

**Location**: `hiclaw/manager/agent/`

**SOUL.md** — Manager identity:
- Name: HoneyBadge Manager
- Role: ERP Knowledge Graph assistant coordinator
- Language: Chinese (primary), English (secondary)
- Behavior: Route user questions to appropriate Workers
- Never answer business questions directly — always delegate to Workers

**AGENTS.md** — Worker registry and routing:
- graph-worker: General queries (查询/查找/搜索/列出/多少)
- analytics-worker: Analysis tasks (分析/趋势/异常/检测/对比)
- Default: graph-worker

**HEARTBEAT.md** — Periodic checks:
- Verify MCP Server connectivity
- Check Worker health
- Report stale sessions

### 2. Worker Skills

#### cypher-query Skill (graph-worker)

**Location**: `hiclaw/workers/graph-worker/agent/skills/cypher-query/SKILL.md`

Purpose: Handle natural language queries over the knowledge graph.

Behavior:
1. Receive user question from Manager
2. Call `get_schema()` to load current NebulaGraph schema
3. Call `generate_ngql(question, schema)` to get nGQL
4. Call `validate_and_execute(ngql)` — this handles L1-L3 + execution
5. Examine results. If more investigation needed, repeat steps 3-4
6. Summarize findings for user (preserve all original numbers/dates)
7. Call `write_audit_log()` with full chain

Constraints embedded in Skill:
- Maximum 5 query rounds per user question
- Always preserve original data values in summaries
- If validation fails 3 times, report the error to user
- Always include trace_id in responses

#### multi-step-analysis Skill (analytics-worker)

**Location**: `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/SKILL.md`

Purpose: Complex analytical queries requiring decomposition.

Additional behaviors:
- Decompose complex questions into sub-queries
- Cross-reference results across entity types
- Detect anomalies (three-way matching, amount deviations)
- Support fraud detection patterns

#### anomaly-detection Skill (analytics-worker)

**Location**: `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/SKILL.md`

Purpose: Proactive anomaly and fraud detection.

Patterns:
- Three-way matching (PO vs Receipt vs Invoice)
- Duplicate invoice detection
- Unusual payment patterns
- Supplier concentration risk

### 3. MCP Servers

All MCP Servers are Python services using FastMCP, registered in Higress gateway.

#### honeybadge-nebula-mcp

**Tools:**

| Tool | Description | Anti-Hallucination |
|------|-------------|-------------------|
| `get_schema` | Return NebulaGraph schema (tags, edges, properties) | — |
| `generate_ngql` | Call LLM to generate nGQL from NL question + schema | — |
| `validate_and_execute` | L1-L3 validate, then execute nGQL, return raw results | L1+L2+L3+L4 |
| `explain_ngql` | EXPLAIN without executing (dry run) | L1 |

`validate_and_execute` is the core safety gate:
```python
async def validate_and_execute(ngql: str, user_context: dict) -> dict:
    # L1: Syntax validation
    syntax_result = validator.validate_syntax(ngql)
    if not syntax_result.valid:
        return {"success": False, "error": "L1_SYNTAX", "details": syntax_result.errors}

    # L2: Schema compliance
    schema_result = validator.validate_schema(ngql)
    if not schema_result.valid:
        return {"success": False, "error": "L2_SCHEMA", "details": schema_result.errors}

    # L3: Permission filter check
    perm_result = validator.validate_permissions(ngql, user_context)
    if not perm_result.valid:
        return {"success": False, "error": "L3_PERMISSION", "details": perm_result.errors}

    # Execute and return raw results (L4: no modification)
    result = await nebula_client.execute(ngql, space="honeybadge")
    return {
        "success": True,
        "columns": result.columns,
        "rows": result.rows,           # L4: raw passthrough
        "row_count": result.row_count,
        "execution_time_ms": result.execution_time_ms,
    }
```

**Infrastructure**: Uses `db/nebula.py` (nebula3-python) and `llm/adapter.py` (OpenAI-compatible).

#### honeybadge-audit-mcp

**Tools:**

| Tool | Description |
|------|-------------|
| `write_audit_log` | Write full-chain audit entry (question → nGQL → result → summary) |
| `get_audit_trail` | Retrieve audit trail by trace_id |

**Infrastructure**: Uses `db/postgres.py` (asyncpg).

#### honeybadge-cache-mcp

**Tools:**

| Tool | Description |
|------|-------------|
| `check_cache` | Check if a similar query was recently executed |
| `cache_result` | Cache query result with TTL |

**Infrastructure**: Uses `db/redis.py` (redis.asyncio).

### 4. LLM Integration

nGQL generation uses the existing `llm/adapter.py` OpenAI-compatible adapter. The LLM is called **inside the MCP Server** (honeybadge-nebula-mcp), not by the Worker directly.

Flow:
```
Worker → mcporter → Higress → honeybadge-nebula-mcp.generate_ngql()
                                    ↓
                              LLM API (GLM/Qwen via Higress AI Gateway)
                                    ↓
                              nGQL string returned to Worker
```

This means the Worker Agent (OpenClaw) uses one LLM for reasoning/planning, and the MCP Server uses another LLM call for nGQL generation. These can be different models:
- Worker reasoning: GLM-4-Flash (fast, cheap)
- nGQL generation: GLM-5 or Qwen-Max (accurate, expensive)

### 5. Deployment

#### Docker Compose Structure

HiClaw core (installed via `hiclaw-install.sh`):
- `hiclaw-manager-agent` — Manager container
- `hiclaw-higress` — AI Gateway (port 8080)
- `hiclaw-tuwunel` — Matrix Server (port 6167)
- `hiclaw-minio` — File storage (port 9000)
- `hiclaw-element-web` — Web UI (port 18088)

HoneyBadge infrastructure (our docker-compose.yaml):
- `nebula-metad` / `nebula-storaged` / `nebula-graphd` — NebulaGraph
- `postgres` — Audit log
- `redis` — Cache
- `honeybadge-nebula-mcp` — NebulaGraph MCP Server
- `honeybadge-audit-mcp` — Audit MCP Server
- `honeybadge-cache-mcp` — Cache MCP Server

Workers are created dynamically by the Manager through conversation.

#### Network Integration

HiClaw and HoneyBadge services share a Docker network. MCP Servers register in Higress via YAML config or `setup-mcp-server.sh`.

### 6. File Structure (New/Modified)

```
.worktrees/phase1-implementation/
├── hiclaw/                              # NEW: HiClaw agent configs
│   ├── manager/
│   │   └── agent/
│   │       ├── SOUL.md                  # Manager identity
│   │       ├── AGENTS.md                # Worker registry
│   │       ├── HEARTBEAT.md             # Health checks
│   │       └── skills/                  # Manager-only skills (if any)
│   └── workers/
│       ├── graph-worker/
│       │   └── agent/
│       │       ├── SOUL.md              # Worker identity
│       │       └── skills/
│       │           └── cypher-query/
│       │               └── SKILL.md     # Query pipeline skill
│       └── analytics-worker/
│           └── agent/
│               ├── SOUL.md
│               └── skills/
│                   ├── multi-step-analysis/
│                   │   └── SKILL.md
│                   └── anomaly-detection/
│                       └── SKILL.md
│
├── mcp-servers/                         # MODIFIED: Real MCP Server implementations
│   ├── honeybadge-nebula-mcp/
│   │   ├── __init__.py
│   │   ├── server.py                    # FastMCP server with tools
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── honeybadge-audit-mcp/
│   │   ├── __init__.py
│   │   ├── server.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── honeybadge-cache-mcp/
│       ├── __init__.py
│       ├── server.py
│       ├── Dockerfile
│       └── requirements.txt
│
├── deploy/
│   ├── docker/
│   │   ├── docker-compose.yaml          # MODIFIED: HoneyBadge infra only
│   │   └── ...
│   └── hiclaw/
│       ├── mcp-honeybadge-nebula.yaml   # NEW: Higress MCP registration
│       ├── mcp-honeybadge-audit.yaml
│       ├── mcp-honeybadge-cache.yaml
│       └── setup-honeybadge-mcps.sh     # NEW: Register all MCP servers
│
├── src/honeybadge/                      # EXISTING: Reused by MCP Servers
│   ├── db/nebula.py                     # ✓ Already implemented
│   ├── db/postgres.py                   # ✓ Already implemented
│   ├── db/redis.py                      # ✓ Already implemented
│   ├── llm/adapter.py                   # ✓ Already implemented
│   ├── protocols/validator.py           # ✓ Already implemented
│   └── core/                            # ✓ Already implemented
│
└── prompts/                             # EXISTING: Used by nebula-mcp
    ├── cypher_system.md
    ├── cypher_constraints.md
    ├── summarize_system.md
    └── ontology/
```

### 7. What We Reuse vs What We Build New

**Reuse as-is:**
- `src/honeybadge/db/nebula.py` — NebulaGraph client (just implemented)
- `src/honeybadge/db/postgres.py` — PostgreSQL client (just implemented)
- `src/honeybadge/db/redis.py` — Redis client (just implemented)
- `src/honeybadge/llm/adapter.py` — LLM adapter with OpenAI-compatible API
- `src/honeybadge/protocols/validator.py` — L1-L3 nGQL validator
- `src/honeybadge/core/` — Trace ID, exceptions, constants
- `prompts/` — Prompt templates for nGQL generation

**Build new:**
- HiClaw Manager configs (SOUL.md, AGENTS.md, HEARTBEAT.md)
- HiClaw Worker configs and Skills (cypher-query, multi-step-analysis, anomaly-detection)
- MCP Servers using FastMCP (honeybadge-nebula-mcp, honeybadge-audit-mcp, honeybadge-cache-mcp)
- Higress MCP registration YAML
- Docker Compose updates

**Delete:**
- `src/honeybadge/manager.py` — Already deleted (was incorrectly from-scratch)
- `src/honeybadge/mcp.py` — No longer needed (MCP Servers are standalone)
- `src/honeybadge/__main__.py` — Rework to just launch MCP Servers
- Old `mcp-servers/` stubs — Replace with FastMCP implementations
