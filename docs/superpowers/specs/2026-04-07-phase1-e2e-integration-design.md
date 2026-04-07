# Phase 1 E2E Integration Design

**Date:** 2026-04-07
**Status:** Draft
**Goal:** Build a FastAPI backend server that connects the Vue 3 frontend to all Phase 1 infrastructure (NebulaGraph, Redis, PostgreSQL, LLM) for end-to-end demo and validation.

---

## 1. Architecture Overview

```
Vue3 Frontend (5173)
  ├── HTTP → FastAPI Backend (8090)
  │     ├── /api/auth/*      → AuthRouter (JWT, demo users)
  │     ├── /api/sessions/*  → SessionRouter (PostgreSQL CRUD)
  │     └── /api/health      → HealthRouter (service status)
  └── WS  → FastAPI Backend (8090)
        └── /ws?token=xxx    → WebSocketHandler
              └── QueryOrchestrator (interface)
                    ├── [Phase 1] DirectPipelineOrchestrator
                    │     LLM → Validator → NebulaGraph → LLM Summary → Audit
                    └── [Future] HiClawOrchestrator
                          Matrix Room → Manager → Worker Pool → ...
```

All infrastructure services run via Docker Compose:
- NebulaGraph (9669) — graph database
- Redis (6379) — session cache
- PostgreSQL (5432) — audit log + sessions + messages
- Milvus (19530/9091) — vector DB (started by default, used later for semantic cache)

## 2. QueryOrchestrator Interface (HiClaw Migration Point)

The WebSocket handler does NOT contain query processing logic. It delegates to a `QueryOrchestrator` abstraction:

```python
class QueryOrchestrator(ABC):
    """Abstract orchestrator — swap implementation to change routing."""

    @abstractmethod
    async def execute_query(
        self,
        question: str,
        session_id: str,
        user_context: dict,
        callbacks: PipelineCallbacks,
    ) -> QueryResult:
        """Process a natural language query end-to-end."""
        ...

@dataclass
class PipelineCallbacks:
    """Callbacks for streaming progress to the WebSocket client."""
    on_progress: Callable[[int, int, str, str | None], Awaitable[None]]
    on_stream: Callable[[str, StreamPhase, bool], Awaitable[None]]

@dataclass
class QueryResult:
    summary: str
    raw_data: list[dict]
    columns: list[str]
    cypher: str
    trace_id: str
    execution_time_ms: int
    row_count: int
    error: str | None = None
```

**Phase 1:** `DirectPipelineOrchestrator` — calls LLM, validator, NebulaGraph, summarizer, audit logger directly.

**Future HiClaw migration:** Create `HiClawOrchestrator` implementing the same interface. It will:
1. Create/reuse a Matrix room for the session
2. Post the question as a Matrix event
3. Manager agent picks up the event, routes to Worker
4. Worker executes the pipeline (same graph-worker logic)
5. Stream Matrix events back through the WebSocket via callbacks

The WebSocket handler, auth, sessions, health — all remain unchanged. Only the orchestrator implementation changes.

### Migration-Ready Design Points

- `PipelineCallbacks` is transport-agnostic (works with WebSocket or Matrix event streams)
- `QueryResult` is the same data structure regardless of orchestration path
- `DirectPipelineOrchestrator` reuses the same worker logic that `HiClawOrchestrator` will delegate to
- Factory function `create_orchestrator(config)` selects implementation based on config:
  ```python
  def create_orchestrator(config: ServerConfig) -> QueryOrchestrator:
      if config.orchestrator_type == "hiclaw":
          return HiClawOrchestrator(config.matrix_url, config.hiclaw_config)
      return DirectPipelineOrchestrator(config.nebula, config.llm, config.pg, config.redis)
  ```

## 3. Backend Server Components

### 3.1 App Factory (`src/honeybadge/server/app.py`)

FastAPI application with:
- CORS middleware (allow frontend origin)
- Lifespan handler: connect all DB clients on startup, disconnect on shutdown
- Mount routers: auth, sessions, health, websocket
- Create `QueryOrchestrator` instance from config

### 3.2 Auth Router (`src/honeybadge/server/auth.py`)

Simple JWT authentication for demo:

**Demo users** (hardcoded, loaded from config in production):
| Username | Password | Display Name | Roles | org_id |
|----------|----------|-------------|-------|--------|
| admin | admin123 | 系统管理员 | ["admin"] | 1 |
| analyst | analyst123 | 数据分析师 | ["analyst"] | 1 |
| auditor | auditor123 | 审计员 | ["auditor"] | 1 |

**Endpoints:**
- `POST /api/auth/login` — validate credentials, return JWT + refresh token + user
- `GET /api/auth/me` — return current user from JWT
- `POST /api/auth/logout` — invalidate token (Redis blacklist)
- `POST /api/auth/refresh` — issue new JWT from refresh token

**JWT payload:** `{sub: user_id, username, roles, org_id, exp, iat}`
**Token expiry:** access=1h, refresh=7d
**Secret:** from env var `JWT_SECRET` (default for dev: `honeybadge-dev-secret-change-in-prod`)

### 3.3 Session Router (`src/honeybadge/server/sessions.py`)

Uses existing PostgreSQL tables (`chat_sessions`, `chat_messages` from init-postgres.sql):

**Endpoints:**
- `GET /api/sessions` — list user's sessions (filtered by JWT user_id)
- `POST /api/sessions` — create new session, return ChatSession
- `GET /api/sessions/{id}` — get session detail
- `PUT /api/sessions/{id}` — update title
- `DELETE /api/sessions/{id}` — soft delete (set status='deleted')
- `GET /api/sessions/{id}/messages` — get messages for session

Response shapes match the frontend TypeScript types exactly (ChatSession, ChatMessage).

### 3.4 Health Router (`src/honeybadge/server/health.py`)

**Endpoint:** `GET /api/health`

Returns status of each infrastructure service:
```json
{
  "status": "healthy",
  "services": {
    "nebula": {"status": "up", "latency_ms": 5},
    "redis": {"status": "up", "latency_ms": 2},
    "postgres": {"status": "up", "latency_ms": 3},
    "llm": {"status": "up", "latency_ms": 120},
    "milvus": {"status": "up", "latency_ms": 10}
  },
  "version": "1.0.0"
}
```

### 3.5 WebSocket Handler (`src/honeybadge/server/websocket.py`)

- Accepts connection at `/ws?token=xxx`
- Validates JWT from query param
- Handles message types: `query`, `heartbeat`
- For `query`: delegates to `QueryOrchestrator.execute_query()` with callbacks that send WS messages
- For `heartbeat`: responds with `heartbeat_ack`
- Graceful disconnect handling

### 3.6 Direct Pipeline Orchestrator (`src/honeybadge/server/orchestrator.py`)

`DirectPipelineOrchestrator` implements `QueryOrchestrator`:

```
Step 1: on_progress(1, 5, "理解问题")
        on_stream(thinking_text, "thinking", false)
Step 2: LLM generates nGQL
        on_progress(2, 5, "生成查询")
        on_stream(ngql, "cypher", false)
Step 3: L1-L3 validation
        on_progress(3, 5, "校验查询")
        If validation fails: retry with error feedback (max 2 retries)
Step 4: Execute on NebulaGraph
        on_progress(4, 5, "执行查询")
Step 5: LLM summarizes results
        on_progress(5, 5, "生成摘要")
        on_stream(summary_chunks, "summarizing", false)
        on_stream("", "summarizing", true)  # done
Step 6: Write L5 audit log (async, don't block response)
Step 7: Return QueryResult
```

Uses existing classes directly:
- `OpenAICompatibleAdapter` for LLM calls
- `NgqlValidator` for L1-L3
- `NebulaGraphClient` for query execution
- `PostgreSQLClient` for audit logging
- `RedisClient` for session cache

### 3.7 Server Config (`src/honeybadge/server/config.py`)

Dataclass loaded from environment variables:

```python
@dataclass
class ServerConfig:
    # Server
    host: str = "0.0.0.0"
    port: int = 8090

    # Orchestrator
    orchestrator_type: str = "direct"  # "direct" or "hiclaw" (future)

    # NebulaGraph
    nebula_host: str = "localhost"
    nebula_port: int = 9669
    nebula_user: str = "root"
    nebula_password: str = "nebula"
    nebula_space: str = "honeybadge"

    # LLM
    llm_endpoint: str = "http://localhost:8080/v1"
    llm_api_key: str = ""
    llm_model: str = "glm-4-flash"

    # PostgreSQL
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "honeybadge"
    pg_password: str = "honeybadge123"
    pg_database: str = "honeybadge_audit"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = "redis123"

    # JWT
    jwt_secret: str = "honeybadge-dev-secret-change-in-prod"
    jwt_access_expire_minutes: int = 60
    jwt_refresh_expire_days: int = 7

    # Milvus (reserved for future semantic cache)
    milvus_host: str = "localhost"
    milvus_port: int = 19530

    # HiClaw (reserved for future orchestration)
    matrix_url: str = "http://localhost:8008"
    hiclaw_manager_url: str = ""
```

## 4. Docker Compose Changes

### 4.1 Add Backend Server Service

```yaml
honeybadge-server:
  build:
    context: ../..
    dockerfile: deploy/docker/Dockerfile.server
  container_name: honeybadge-server
  hostname: honeybadge-server
  restart: unless-stopped
  ports:
    - "8090:8090"
  environment:
    - NEBULA_HOST=nebula-graphd
    - NEBULA_PORT=9669
    - REDIS_HOST=redis
    - REDIS_PASSWORD=redis123
    - POSTGRES_HOST=postgres
    - POSTGRES_PASSWORD=honeybadge123
    - LLM_ENDPOINT=${LLM_ENDPOINT:-http://host.docker.internal:8000/v1}
    - LLM_API_KEY=${LLM_API_KEY:-}
    - LLM_MODEL=${LLM_MODEL:-glm-4-flash}
    - JWT_SECRET=${JWT_SECRET:-honeybadge-dev-secret-change-in-prod}
    - ORCHESTRATOR_TYPE=direct
  depends_on:
    nebula-graphd: { condition: service_healthy }
    redis: { condition: service_healthy }
    postgres: { condition: service_healthy }
  networks:
    - honeybadge-net
```

### 4.2 Fix Milvus

- Expose port `19530:19530` (gRPC) in addition to `9091:9091` (HTTP)
- Remove `profiles: [vector]` so Milvus starts with default `docker-compose up`
- Keep etcd and minio as dependencies

### 4.3 Frontend Dev Proxy

Add `vite.config.ts` proxy to forward `/api` and `/ws` to backend (port 8090) during development.

### 4.4 NebulaGraph Init

The existing `init-nebula.sh` will:
1. Wait for graphd to be ready
2. Create space `honeybadge`
3. Create tags and edges per `deploy/nebula/schema.ngql`
4. Load test data from `deploy/test-data/`

## 5. Test Data

Use existing CSV test data in `deploy/test-data/` to populate:
- Suppliers (5-10 records)
- Items (10-20 records)
- Purchase Orders (5-10 with line items)
- Invoices + Receipts (for three-way matching demo)
- At least 1 anomaly case (PO-Invoice amount mismatch) for fraud detection demo

## 6. Frontend Changes

Minimal — the frontend is already well-built. Only needed:

1. **`vite.config.ts`** — add proxy config for `/api` → `http://localhost:8090` and `/ws` → `ws://localhost:8090`
2. **`src/composables/useAuth.ts`** — no changes, already calls correct endpoints
3. **`src/composables/useChat.ts`** — no changes, WS URL already uses `window.location.host`

## 7. Files to Create/Modify

### New Files
| File | Purpose |
|------|---------|
| `src/honeybadge/server/__init__.py` | Package init |
| `src/honeybadge/server/app.py` | FastAPI app factory |
| `src/honeybadge/server/config.py` | Server configuration |
| `src/honeybadge/server/auth.py` | JWT auth router |
| `src/honeybadge/server/sessions.py` | Session CRUD router |
| `src/honeybadge/server/health.py` | Health check router |
| `src/honeybadge/server/websocket.py` | WebSocket handler |
| `src/honeybadge/server/orchestrator.py` | QueryOrchestrator interface + DirectPipelineOrchestrator |
| `src/honeybadge/server/dependencies.py` | FastAPI dependency injection (DB clients, orchestrator) |
| `deploy/docker/Dockerfile.server` | Backend server Dockerfile |
| `tests/test_integration.py` | E2E integration tests |

### Modified Files
| File | Change |
|------|--------|
| `deploy/docker/docker-compose.yaml` | Add server service, fix Milvus ports/profile |
| `frontend/vite.config.ts` | Add dev proxy |
| `requirements.txt` | Add fastapi, uvicorn, python-jose, passlib |
| `pyproject.toml` | Add server entry point |

## 8. Demo Validation Scenarios

After integration, these scenarios must work E2E:

1. **Login** — `admin/admin123` → JWT → redirect to chat
2. **Create session** — new chat session appears in sidebar
3. **Simple query** — "查询所有供应商" → nGQL generated → results displayed
4. **PTP query** — "查询采购订单PO-001的详细信息" → PO + line items
5. **Anomaly detection** — "检查三单匹配异常" → flag mismatched PO/Invoice/Receipt
6. **Streaming** — progress steps visible, summary streams in
7. **Audit trail** — trace_id visible, audit log written to PostgreSQL
8. **Health check** — `/api/health` shows all services green
9. **Reconnection** — kill WS, frontend auto-reconnects
10. **Multi-session** — switch between sessions, messages persist

## 9. HiClaw Migration Path (Future)

When ready to migrate to HiClaw/Matrix:

1. Implement `HiClawOrchestrator` with same `QueryOrchestrator` interface
2. Use Matrix client SDK to:
   - Register bot users (manager, workers) on Conduit
   - Create rooms per session
   - Post query events, listen for response events
3. Set `ORCHESTRATOR_TYPE=hiclaw` in config
4. The existing graph-worker skill logic moves into the HiClaw worker agent
5. All server endpoints, auth, sessions, health — zero changes
6. Frontend — zero changes

The `DirectPipelineOrchestrator` remains available as fallback/testing mode.
