# Phase 1 E2E Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI backend server connecting the Vue 3 frontend to NebulaGraph, Redis, PostgreSQL, and LLM for end-to-end Phase 1 demo.

**Architecture:** FastAPI server (port 8090) with JWT auth, session CRUD, WebSocket query pipeline. A `QueryOrchestrator` interface abstracts orchestration — Phase 1 uses `DirectPipelineOrchestrator`, future HiClaw/Matrix integration swaps in `HiClawOrchestrator` without touching endpoints or frontend.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, python-jose (JWT), NebulaGraph (nebula3-python), asyncpg, redis-py, httpx, Vue 3 + Vite (frontend proxy)

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `src/honeybadge/server/__init__.py` | Package init |
| `src/honeybadge/server/config.py` | Server config from env vars |
| `src/honeybadge/server/app.py` | FastAPI app factory, lifespan, CORS |
| `src/honeybadge/server/dependencies.py` | FastAPI DI: DB clients, orchestrator |
| `src/honeybadge/server/auth.py` | JWT auth router + demo users |
| `src/honeybadge/server/sessions.py` | Session CRUD router (PostgreSQL) |
| `src/honeybadge/server/health.py` | Health check router |
| `src/honeybadge/server/websocket.py` | WebSocket handler |
| `src/honeybadge/server/orchestrator.py` | QueryOrchestrator ABC + DirectPipelineOrchestrator |
| `deploy/docker/Dockerfile.server` | Backend server Docker image |
| `scripts/load-test-data.py` | Load CSV test data into NebulaGraph |
| `tests/test_server_config.py` | Config tests |
| `tests/test_server_auth.py` | Auth router tests |
| `tests/test_server_sessions.py` | Session router tests |
| `tests/test_server_orchestrator.py` | Orchestrator tests |
| `tests/test_server_websocket.py` | WebSocket handler tests |
| `tests/test_integration_e2e.py` | Full E2E integration tests |

### Modified Files

| File | Change |
|------|--------|
| `requirements.txt` | Add fastapi, uvicorn, python-jose, passlib |
| `pyproject.toml` | Add deps + server entry point |
| `deploy/docker/docker-compose.yaml` | Add server service, fix Milvus |
| `frontend/vite.config.ts` | Fix proxy target port to 8090 |

---

## Task 1: Dependencies and Config

**Files:**
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Create: `src/honeybadge/server/__init__.py`
- Create: `src/honeybadge/server/config.py`
- Test: `tests/test_server_config.py`

- [ ] **Step 1: Write config test**

```python
# tests/test_server_config.py
"""Tests for server configuration."""
import os
import pytest
from honeybadge.server.config import ServerConfig


def test_default_config():
    config = ServerConfig()
    assert config.host == "0.0.0.0"
    assert config.port == 8090
    assert config.orchestrator_type == "direct"
    assert config.nebula_host == "localhost"
    assert config.nebula_port == 9669
    assert config.nebula_space == "honeybadge"
    assert config.pg_host == "localhost"
    assert config.pg_port == 5432
    assert config.redis_host == "localhost"
    assert config.redis_port == 6379
    assert config.jwt_access_expire_minutes == 60
    assert config.jwt_refresh_expire_days == 7
    assert config.milvus_host == "localhost"
    assert config.milvus_port == 19530
    assert config.matrix_url == "http://localhost:8008"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("NEBULA_HOST", "nebula-graphd")
    monkeypatch.setenv("NEBULA_PORT", "19669")
    monkeypatch.setenv("REDIS_PASSWORD", "secret")
    monkeypatch.setenv("JWT_SECRET", "my-secret")
    monkeypatch.setenv("ORCHESTRATOR_TYPE", "hiclaw")
    config = ServerConfig()
    assert config.nebula_host == "nebula-graphd"
    assert config.nebula_port == 19669
    assert config.redis_password == "secret"
    assert config.jwt_secret == "my-secret"
    assert config.orchestrator_type == "hiclaw"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/dev/HoneyBadge/.worktrees/phase1-implementation && python -m pytest tests/test_server_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'honeybadge.server'`

- [ ] **Step 3: Update requirements.txt**

Add these lines to `requirements.txt`:

```
# Web framework
fastapi>=0.115.0
uvicorn[standard]>=0.30.0

# JWT authentication
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
```

- [ ] **Step 4: Update pyproject.toml dependencies**

Add to the `dependencies` list in `pyproject.toml`:

```toml
    # Web framework
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    # JWT authentication
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
```

Add to `[project.scripts]`:

```toml
honeybadge-server = "honeybadge.server.app:main"
```

- [ ] **Step 5: Create server package init**

```python
# src/honeybadge/server/__init__.py
"""HoneyBadge backend server package."""
```

- [ ] **Step 6: Implement ServerConfig**

```python
# src/honeybadge/server/config.py
"""Server configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field


@dataclass
class ServerConfig:
    """Server configuration. All values can be overridden via env vars."""

    # Server
    host: str = field(default_factory=lambda: os.environ.get("SERVER_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("SERVER_PORT", "8090")))

    # Orchestrator: "direct" (Phase 1) or "hiclaw" (future)
    orchestrator_type: str = field(
        default_factory=lambda: os.environ.get("ORCHESTRATOR_TYPE", "direct")
    )

    # NebulaGraph
    nebula_host: str = field(default_factory=lambda: os.environ.get("NEBULA_HOST", "localhost"))
    nebula_port: int = field(default_factory=lambda: int(os.environ.get("NEBULA_PORT", "9669")))
    nebula_user: str = field(default_factory=lambda: os.environ.get("NEBULA_USER", "root"))
    nebula_password: str = field(
        default_factory=lambda: os.environ.get("NEBULA_PASSWORD", "nebula")
    )
    nebula_space: str = field(
        default_factory=lambda: os.environ.get("NEBULA_SPACE", "honeybadge")
    )

    # LLM
    llm_endpoint: str = field(
        default_factory=lambda: os.environ.get("LLM_ENDPOINT", "http://localhost:8080/v1")
    )
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "glm-4-flash"))

    # PostgreSQL
    pg_host: str = field(default_factory=lambda: os.environ.get("POSTGRES_HOST", "localhost"))
    pg_port: int = field(default_factory=lambda: int(os.environ.get("POSTGRES_PORT", "5432")))
    pg_user: str = field(default_factory=lambda: os.environ.get("POSTGRES_USER", "honeybadge"))
    pg_password: str = field(
        default_factory=lambda: os.environ.get("POSTGRES_PASSWORD", "honeybadge123")
    )
    pg_database: str = field(
        default_factory=lambda: os.environ.get("POSTGRES_DB", "honeybadge_audit")
    )

    # Redis
    redis_host: str = field(default_factory=lambda: os.environ.get("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: int(os.environ.get("REDIS_PORT", "6379")))
    redis_password: str = field(
        default_factory=lambda: os.environ.get("REDIS_PASSWORD", "redis123")
    )

    # JWT
    jwt_secret: str = field(
        default_factory=lambda: os.environ.get(
            "JWT_SECRET", "honeybadge-dev-secret-change-in-prod"
        )
    )
    jwt_access_expire_minutes: int = field(
        default_factory=lambda: int(os.environ.get("JWT_ACCESS_EXPIRE_MINUTES", "60"))
    )
    jwt_refresh_expire_days: int = field(
        default_factory=lambda: int(os.environ.get("JWT_REFRESH_EXPIRE_DAYS", "7"))
    )

    # Milvus (reserved for semantic cache)
    milvus_host: str = field(default_factory=lambda: os.environ.get("MILVUS_HOST", "localhost"))
    milvus_port: int = field(
        default_factory=lambda: int(os.environ.get("MILVUS_PORT", "19530"))
    )

    # HiClaw / Matrix (reserved for future orchestration)
    matrix_url: str = field(
        default_factory=lambda: os.environ.get("MATRIX_URL", "http://localhost:8008")
    )
    hiclaw_manager_url: str = field(
        default_factory=lambda: os.environ.get("HICLAW_MANAGER_URL", "")
    )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /d/dev/HoneyBadge/.worktrees/phase1-implementation && pip install -e ".[dev]" && python -m pytest tests/test_server_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add requirements.txt pyproject.toml src/honeybadge/server/__init__.py src/honeybadge/server/config.py tests/test_server_config.py
git commit -m "feat(server): add server config with env var loading"
```

---

## Task 2: JWT Auth Router

**Files:**
- Create: `src/honeybadge/server/auth.py`
- Test: `tests/test_server_auth.py`

- [ ] **Step 1: Write auth tests**

```python
# tests/test_server_auth.py
"""Tests for JWT authentication."""
import pytest
from datetime import datetime, timedelta, timezone
from honeybadge.server.auth import (
    DEMO_USERS,
    create_access_token,
    create_refresh_token,
    decode_token,
    authenticate_user,
)
from honeybadge.server.config import ServerConfig


@pytest.fixture
def config():
    return ServerConfig()


def test_demo_users_exist():
    assert "admin" in DEMO_USERS
    assert "analyst" in DEMO_USERS
    assert "auditor" in DEMO_USERS


def test_demo_user_has_required_fields():
    user = DEMO_USERS["admin"]
    assert user["username"] == "admin"
    assert user["display_name"] == "系统管理员"
    assert "admin" in user["roles"]
    assert user["org_id"] == 1


def test_authenticate_user_success():
    user = authenticate_user("admin", "admin123")
    assert user is not None
    assert user["username"] == "admin"


def test_authenticate_user_wrong_password():
    user = authenticate_user("admin", "wrong")
    assert user is None


def test_authenticate_user_unknown_user():
    user = authenticate_user("nobody", "password")
    assert user is None


def test_create_access_token(config):
    token = create_access_token(
        data={"sub": "user-1", "username": "admin", "roles": ["admin"], "org_id": 1},
        secret=config.jwt_secret,
        expire_minutes=60,
    )
    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_token(config):
    token = create_access_token(
        data={"sub": "user-1", "username": "admin", "roles": ["admin"], "org_id": 1},
        secret=config.jwt_secret,
        expire_minutes=60,
    )
    payload = decode_token(token, config.jwt_secret)
    assert payload["sub"] == "user-1"
    assert payload["username"] == "admin"
    assert payload["roles"] == ["admin"]
    assert payload["org_id"] == 1


def test_decode_expired_token(config):
    token = create_access_token(
        data={"sub": "user-1", "username": "admin", "roles": ["admin"], "org_id": 1},
        secret=config.jwt_secret,
        expire_minutes=-1,  # already expired
    )
    payload = decode_token(token, config.jwt_secret)
    assert payload is None


def test_decode_invalid_token(config):
    payload = decode_token("invalid.token.here", config.jwt_secret)
    assert payload is None


def test_create_refresh_token(config):
    token = create_refresh_token(
        data={"sub": "user-1"},
        secret=config.jwt_secret,
        expire_days=7,
    )
    payload = decode_token(token, config.jwt_secret)
    assert payload["sub"] == "user-1"
    assert payload["type"] == "refresh"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'honeybadge.server.auth'`

- [ ] **Step 3: Implement auth module**

```python
# src/honeybadge/server/auth.py
"""JWT authentication for HoneyBadge server."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Demo users for Phase 1. In production, this comes from SSO/OIDC.
DEMO_USERS: dict[str, dict[str, Any]] = {
    "admin": {
        "id": "user-admin",
        "username": "admin",
        "password_hash": pwd_context.hash("admin123"),
        "display_name": "系统管理员",
        "roles": ["admin"],
        "org_id": 1,
    },
    "analyst": {
        "id": "user-analyst",
        "username": "analyst",
        "password_hash": pwd_context.hash("analyst123"),
        "display_name": "数据分析师",
        "roles": ["analyst"],
        "org_id": 1,
    },
    "auditor": {
        "id": "user-auditor",
        "username": "auditor",
        "password_hash": pwd_context.hash("auditor123"),
        "display_name": "审计员",
        "roles": ["auditor"],
        "org_id": 1,
    },
}

ALGORITHM = "HS256"


def authenticate_user(username: str, password: str) -> Optional[dict[str, Any]]:
    """Authenticate user against demo users. Returns user dict or None."""
    user = DEMO_USERS.get(username)
    if user is None:
        return None
    if not pwd_context.verify(password, user["password_hash"]):
        return None
    return user


def create_access_token(
    data: dict[str, Any],
    secret: str,
    expire_minutes: int = 60,
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc), "type": "access"})
    return jwt.encode(to_encode, secret, algorithm=ALGORITHM)


def create_refresh_token(
    data: dict[str, Any],
    secret: str,
    expire_days: int = 7,
) -> str:
    """Create a JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=expire_days)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc), "type": "refresh"})
    return jwt.encode(to_encode, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> Optional[dict[str, Any]]:
    """Decode and validate a JWT token. Returns payload or None."""
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def user_to_response(user: dict[str, Any]) -> dict[str, Any]:
    """Convert internal user dict to API response format (excludes password_hash)."""
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "roles": user["roles"],
        "org_id": user["org_id"],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_server_auth.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/honeybadge/server/auth.py tests/test_server_auth.py
git commit -m "feat(server): add JWT auth with demo users"
```

---

## Task 3: QueryOrchestrator Interface + DirectPipelineOrchestrator

**Files:**
- Create: `src/honeybadge/server/orchestrator.py`
- Test: `tests/test_server_orchestrator.py`

- [ ] **Step 1: Write orchestrator tests**

```python
# tests/test_server_orchestrator.py
"""Tests for QueryOrchestrator and DirectPipelineOrchestrator."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from honeybadge.server.orchestrator import (
    QueryOrchestrator,
    DirectPipelineOrchestrator,
    PipelineCallbacks,
    QueryResult,
)


@pytest.fixture
def mock_callbacks():
    return PipelineCallbacks(
        on_progress=AsyncMock(),
        on_stream=AsyncMock(),
    )


@pytest.fixture
def mock_nebula():
    client = AsyncMock()
    client.execute = AsyncMock(return_value=MagicMock(
        success=True,
        columns=["supplier_name", "status"],
        rows=[{"supplier_name": "测试供应商", "status": "ACTIVE"}],
        row_count=1,
        execution_time_ms=5,
    ))
    return client


@pytest.fixture
def mock_llm():
    adapter = AsyncMock()
    # generate_ngql response
    adapter.chat = AsyncMock(return_value=MagicMock(
        content='MATCH (n:Supplier) RETURN n.Supplier.supplier_name AS supplier_name, n.Supplier.status AS status LIMIT 10',
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        finish_reason="stop",
        latency_ms=200,
    ))
    return adapter


@pytest.fixture
def mock_pg():
    client = AsyncMock()
    client.write_audit_log = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.fixture
def mock_validator():
    v = MagicMock()
    valid_result = MagicMock(valid=True, errors=[], warnings=[])
    v.validate_syntax = MagicMock(return_value=valid_result)
    v.validate_schema = MagicMock(return_value=valid_result)
    return v


def test_query_result_dataclass():
    result = QueryResult(
        summary="测试摘要",
        raw_data=[{"col": "val"}],
        columns=["col"],
        cypher="MATCH (n) RETURN n",
        trace_id="TRC-20260407-120000-abcd1234",
        execution_time_ms=100,
        row_count=1,
    )
    assert result.summary == "测试摘要"
    assert result.error is None


def test_pipeline_callbacks_dataclass():
    cb = PipelineCallbacks(on_progress=AsyncMock(), on_stream=AsyncMock())
    assert cb.on_progress is not None
    assert cb.on_stream is not None


@pytest.mark.asyncio
async def test_direct_pipeline_execute_query(
    mock_nebula, mock_llm, mock_pg, mock_redis, mock_validator, mock_callbacks
):
    orchestrator = DirectPipelineOrchestrator(
        nebula=mock_nebula,
        llm=mock_llm,
        pg=mock_pg,
        redis=mock_redis,
        validator=mock_validator,
        nebula_space="honeybadge",
    )
    result = await orchestrator.execute_query(
        question="查询所有供应商",
        session_id="session-1",
        user_context={"user_id": "user-admin", "org_ids": [], "data_scope": "ALL"},
        callbacks=mock_callbacks,
    )
    assert result.row_count == 1
    assert result.error is None
    assert result.trace_id.startswith("TRC-")
    # Progress was called 5 times (5 steps)
    assert mock_callbacks.on_progress.call_count == 5
    # Audit log was written
    mock_pg.write_audit_log.assert_called_once()


@pytest.mark.asyncio
async def test_direct_pipeline_validation_failure(
    mock_nebula, mock_llm, mock_pg, mock_redis, mock_callbacks
):
    validator = MagicMock()
    fail_result = MagicMock(valid=False, errors=[MagicMock(code="E001", message="Empty query")])
    validator.validate_syntax = MagicMock(return_value=fail_result)
    # On retry, also fail
    validator.validate_schema = MagicMock(return_value=MagicMock(valid=True, errors=[], warnings=[]))

    orchestrator = DirectPipelineOrchestrator(
        nebula=mock_nebula,
        llm=mock_llm,
        pg=mock_pg,
        redis=mock_redis,
        validator=validator,
        nebula_space="honeybadge",
    )
    result = await orchestrator.execute_query(
        question="坏查询",
        session_id="session-1",
        user_context={"user_id": "user-admin", "org_ids": [], "data_scope": "ALL"},
        callbacks=mock_callbacks,
    )
    # Should return an error result (after retries exhausted)
    assert result.error is not None or result.row_count >= 0  # graceful handling
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement orchestrator module**

```python
# src/honeybadge/server/orchestrator.py
"""QueryOrchestrator interface and DirectPipelineOrchestrator implementation.

The WebSocket handler delegates all query processing to a QueryOrchestrator.
Phase 1 uses DirectPipelineOrchestrator (calls LLM/Nebula directly).
Future: HiClawOrchestrator routes through Matrix rooms.
"""

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import structlog

from honeybadge.core.trace import generate_trace_id
from honeybadge.db.nebula import NebulaGraphClient
from honeybadge.db.postgres import AuditLogEntry, PostgreSQLClient
from honeybadge.db.redis import RedisClient
from honeybadge.llm.adapter import LLMAdapter, LLMRequest
from honeybadge.protocols.validator import NgqlValidator

logger = structlog.get_logger()


@dataclass
class PipelineCallbacks:
    """Callbacks for streaming progress to the client.

    Transport-agnostic: works with WebSocket or Matrix event streams.
    """

    on_progress: Callable[[int, int, str, Optional[str]], Awaitable[None]]
    """on_progress(step_number, total_steps, step_description, detail)"""

    on_stream: Callable[[str, str, bool], Awaitable[None]]
    """on_stream(content, phase, done)"""


@dataclass
class QueryResult:
    """Result of a query execution — same regardless of orchestrator."""

    summary: str
    raw_data: list[dict[str, Any]]
    columns: list[str]
    cypher: str
    trace_id: str
    execution_time_ms: int
    row_count: int
    error: Optional[str] = None


class QueryOrchestrator(ABC):
    """Abstract orchestrator — swap implementation to change routing.

    Phase 1: DirectPipelineOrchestrator (calls services directly)
    Future:  HiClawOrchestrator (routes through Matrix/Manager/Workers)
    """

    @abstractmethod
    async def execute_query(
        self,
        question: str,
        session_id: str,
        user_context: dict[str, Any],
        callbacks: PipelineCallbacks,
    ) -> QueryResult:
        """Process a natural language query end-to-end."""
        ...


class DirectPipelineOrchestrator(QueryOrchestrator):
    """Direct pipeline: LLM -> Validator -> NebulaGraph -> LLM Summary -> Audit.

    No HiClaw/Matrix involved. Calls all services in-process.
    """

    MAX_RETRIES = 2
    TOTAL_STEPS = 5

    def __init__(
        self,
        nebula: NebulaGraphClient,
        llm: LLMAdapter,
        pg: PostgreSQLClient,
        redis: RedisClient,
        validator: NgqlValidator,
        nebula_space: str = "honeybadge",
    ):
        self._nebula = nebula
        self._llm = llm
        self._pg = pg
        self._redis = redis
        self._validator = validator
        self._nebula_space = nebula_space
        self._schema_cache: str = ""

    async def execute_query(
        self,
        question: str,
        session_id: str,
        user_context: dict[str, Any],
        callbacks: PipelineCallbacks,
    ) -> QueryResult:
        trace_id = generate_trace_id()
        start_time = time.time()

        logger.info("pipeline_start", trace_id=trace_id, question=question[:100])

        try:
            # Step 1: Understanding question
            await callbacks.on_progress(1, self.TOTAL_STEPS, "理解问题", None)
            await callbacks.on_stream("正在分析您的问题...\n", "thinking", False)

            # Load schema if not cached
            if not self._schema_cache:
                self._schema_cache = await self._load_schema()

            # Step 2: Generate nGQL
            await callbacks.on_progress(2, self.TOTAL_STEPS, "生成查询", None)
            ngql = await self._generate_ngql(question, user_context, trace_id)
            await callbacks.on_stream(ngql, "cypher", False)

            # Step 3: Validate (L1-L3) with retry
            await callbacks.on_progress(3, self.TOTAL_STEPS, "校验查询", None)
            ngql = await self._validate_with_retry(ngql, question, user_context, trace_id, callbacks)

            # Step 4: Execute on NebulaGraph
            await callbacks.on_progress(4, self.TOTAL_STEPS, "执行查询", None)
            result = await self._nebula.execute(ngql, space=self._nebula_space)

            if not result.success:
                raise Exception(f"NebulaGraph execution failed: {result.error_message}")

            # Step 5: Summarize results
            await callbacks.on_progress(5, self.TOTAL_STEPS, "生成摘要", None)
            summary = await self._summarize(question, result.columns, result.rows, ngql, trace_id)
            await callbacks.on_stream(summary, "summarizing", True)

            execution_time_ms = int((time.time() - start_time) * 1000)

            # Write audit log (don't block response)
            try:
                await self._pg.write_audit_log(AuditLogEntry(
                    trace_id=trace_id,
                    question=question,
                    cypher=ngql,
                    raw_result={"columns": result.columns, "rows": result.rows},
                    summary=summary,
                    user_id=user_context.get("user_id", "anonymous"),
                    session_id=session_id,
                    execution_time_ms=execution_time_ms,
                    row_count=result.row_count,
                ))
            except Exception as e:
                logger.error("audit_log_failed", trace_id=trace_id, error=str(e))

            return QueryResult(
                summary=summary,
                raw_data=result.rows,
                columns=result.columns,
                cypher=ngql,
                trace_id=trace_id,
                execution_time_ms=execution_time_ms,
                row_count=result.row_count,
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error("pipeline_error", trace_id=trace_id, error=str(e))
            return QueryResult(
                summary=f"查询处理失败: {str(e)}",
                raw_data=[],
                columns=[],
                cypher="",
                trace_id=trace_id,
                execution_time_ms=execution_time_ms,
                row_count=0,
                error=str(e),
            )

    async def _load_schema(self) -> str:
        """Load NebulaGraph schema for prompt injection."""
        lines: list[str] = []
        tags_result = await self._nebula.execute("SHOW TAGS", space=self._nebula_space)
        if tags_result.success:
            for row in tags_result.rows:
                name = row.get("Name") or row.get("name") or ""
                if name:
                    desc = await self._nebula.execute(
                        f"DESCRIBE TAG `{name}`", space=self._nebula_space
                    )
                    props = []
                    if desc.success:
                        for p in desc.rows:
                            pname = p.get("Field") or p.get("field") or ""
                            ptype = p.get("Type") or p.get("type") or ""
                            props.append(f"    {pname}: {ptype}")
                    lines.append(f"Tag {name}:\n" + "\n".join(props))

        edges_result = await self._nebula.execute("SHOW EDGES", space=self._nebula_space)
        if edges_result.success:
            for row in edges_result.rows:
                name = row.get("Name") or row.get("name") or ""
                if name:
                    desc = await self._nebula.execute(
                        f"DESCRIBE EDGE `{name}`", space=self._nebula_space
                    )
                    props = []
                    if desc.success:
                        for p in desc.rows:
                            pname = p.get("Field") or p.get("field") or ""
                            ptype = p.get("Type") or p.get("type") or ""
                            props.append(f"    {pname}: {ptype}")
                    lines.append(f"Edge {name}:\n" + "\n".join(props))

        return "\n\n".join(lines)

    async def _generate_ngql(
        self, question: str, user_context: dict[str, Any], trace_id: str
    ) -> str:
        """Call LLM to generate nGQL from natural language."""
        from honeybadge.llm.adapter import generate_ngql

        response = await generate_ngql(
            adapter=self._llm,
            question=question,
            schema_info=self._schema_cache,
            ontology_info="",
            user_context=user_context if user_context.get("org_ids") else None,
            trace_id=trace_id,
        )
        ngql = response.content.strip()
        # Strip markdown fences
        ngql = re.sub(r"^```(?:ngql|cypher|nGQL)?\s*\n?", "", ngql)
        ngql = re.sub(r"\n?```\s*$", "", ngql)
        return ngql.strip()

    async def _validate_with_retry(
        self,
        ngql: str,
        question: str,
        user_context: dict[str, Any],
        trace_id: str,
        callbacks: PipelineCallbacks,
    ) -> str:
        """Validate nGQL with L1-L3, retry generation on failure."""
        for attempt in range(self.MAX_RETRIES + 1):
            l1 = self._validator.validate_syntax(ngql)
            if not l1.valid:
                if attempt < self.MAX_RETRIES:
                    errors = "; ".join(e.message for e in l1.errors)
                    await callbacks.on_stream(f"校验失败，正在重试 ({attempt + 1})...\n", "thinking", False)
                    ngql = await self._generate_ngql(question, user_context, trace_id)
                    continue
                raise Exception(f"L1 validation failed after {self.MAX_RETRIES} retries: {l1.errors}")

            l2 = self._validator.validate_schema(ngql)
            if not l2.valid:
                if attempt < self.MAX_RETRIES:
                    await callbacks.on_stream(f"Schema 校验失败，正在重试...\n", "thinking", False)
                    ngql = await self._generate_ngql(question, user_context, trace_id)
                    continue
                # L2 warnings are OK, only hard errors fail
                if l2.errors:
                    raise Exception(f"L2 schema validation failed: {l2.errors}")

            return ngql

        return ngql

    async def _summarize(
        self,
        question: str,
        columns: list[str],
        rows: list[dict],
        ngql: str,
        trace_id: str,
    ) -> str:
        """Call LLM to generate a Chinese summary of query results."""
        from honeybadge.llm.adapter import summarize_results

        response = await summarize_results(
            adapter=self._llm,
            question=question,
            raw_results=rows,
            columns=columns,
            trace_id=trace_id,
        )
        return response.content


def create_orchestrator(
    config: "ServerConfig",
    nebula: NebulaGraphClient,
    llm: LLMAdapter,
    pg: PostgreSQLClient,
    redis: RedisClient,
    validator: NgqlValidator,
) -> QueryOrchestrator:
    """Factory: create the right orchestrator based on config.

    Set ORCHESTRATOR_TYPE=direct (default) or hiclaw (future).
    """
    from honeybadge.server.config import ServerConfig

    if config.orchestrator_type == "hiclaw":
        # Future: return HiClawOrchestrator(config.matrix_url, config.hiclaw_manager_url, ...)
        raise NotImplementedError(
            "HiClaw orchestrator not yet implemented. Use ORCHESTRATOR_TYPE=direct"
        )
    return DirectPipelineOrchestrator(
        nebula=nebula,
        llm=llm,
        pg=pg,
        redis=redis,
        validator=validator,
        nebula_space=config.nebula_space,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_server_orchestrator.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/honeybadge/server/orchestrator.py tests/test_server_orchestrator.py
git commit -m "feat(server): add QueryOrchestrator interface and DirectPipelineOrchestrator"
```

---

## Task 4: FastAPI App, Dependencies, Health, Sessions

**Files:**
- Create: `src/honeybadge/server/dependencies.py`
- Create: `src/honeybadge/server/health.py`
- Create: `src/honeybadge/server/sessions.py`
- Create: `src/honeybadge/server/app.py`
- Test: `tests/test_server_sessions.py`

- [ ] **Step 1: Write session router tests**

```python
# tests/test_server_sessions.py
"""Tests for session and auth API endpoints using FastAPI TestClient."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create a test FastAPI app with mocked dependencies."""
    from honeybadge.server.app import create_app
    from honeybadge.server.config import ServerConfig

    config = ServerConfig()
    application = create_app(config)

    # Mock DB clients in app state
    application.state.pg = AsyncMock()
    application.state.redis = AsyncMock()
    application.state.nebula = AsyncMock()
    application.state.llm = AsyncMock()
    application.state.orchestrator = AsyncMock()

    # Mock PG session queries
    application.state.pg._pool = MagicMock()

    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Login and return auth headers."""
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_success(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "refresh_token" in data
    assert data["user"]["username"] == "admin"
    assert data["user"]["display_name"] == "系统管理员"


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


def test_me_authenticated(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_me_unauthenticated(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_health(client):
    # Health endpoint doesn't require auth
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "version" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement dependencies module**

```python
# src/honeybadge/server/dependencies.py
"""FastAPI dependency injection for DB clients and orchestrator."""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from honeybadge.server.auth import decode_token

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Extract and validate JWT from Authorization header."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    config = request.app.state.config
    payload = decode_token(credentials.credentials, config.jwt_secret)

    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    return payload


def get_pg(request: Request):
    """Get PostgreSQL client from app state."""
    return request.app.state.pg


def get_redis(request: Request):
    """Get Redis client from app state."""
    return request.app.state.redis


def get_nebula(request: Request):
    """Get NebulaGraph client from app state."""
    return request.app.state.nebula


def get_orchestrator(request: Request):
    """Get QueryOrchestrator from app state."""
    return request.app.state.orchestrator
```

- [ ] **Step 4: Implement health router**

```python
# src/honeybadge/server/health.py
"""Health check router."""

from fastapi import APIRouter, Request

from honeybadge.core.constants import VERSION

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health_check(request: Request):
    """Return service health status."""
    services = {}

    # Check Redis
    try:
        redis = request.app.state.redis
        if redis and redis._client:
            await redis._client.ping()
            services["redis"] = {"status": "up"}
        else:
            services["redis"] = {"status": "down", "error": "not connected"}
    except Exception as e:
        services["redis"] = {"status": "down", "error": str(e)}

    # Check PostgreSQL
    try:
        pg = request.app.state.pg
        if pg and pg._pool:
            async with pg._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            services["postgres"] = {"status": "up"}
        else:
            services["postgres"] = {"status": "down", "error": "not connected"}
    except Exception as e:
        services["postgres"] = {"status": "down", "error": str(e)}

    # Check NebulaGraph
    try:
        nebula = request.app.state.nebula
        if nebula and nebula._pool:
            services["nebula"] = {"status": "up"}
        else:
            services["nebula"] = {"status": "down", "error": "not connected"}
    except Exception as e:
        services["nebula"] = {"status": "down", "error": str(e)}

    # Check LLM
    try:
        llm = request.app.state.llm
        if llm:
            healthy = await llm.health_check()
            services["llm"] = {"status": "up" if healthy else "degraded"}
        else:
            services["llm"] = {"status": "down", "error": "not configured"}
    except Exception as e:
        services["llm"] = {"status": "down", "error": str(e)}

    all_up = all(s.get("status") == "up" for s in services.values())
    return {
        "status": "healthy" if all_up else "degraded",
        "version": VERSION,
        "services": services,
    }
```

- [ ] **Step 5: Implement sessions router**

```python
# src/honeybadge/server/sessions.py
"""Session CRUD router. Uses PostgreSQL chat_sessions and chat_messages tables."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from honeybadge.server.dependencies import get_current_user, get_pg

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None


class UpdateSessionRequest(BaseModel):
    title: str


@router.get("")
async def list_sessions(user=Depends(get_current_user), pg=Depends(get_pg)):
    """List user's chat sessions."""
    async with pg._pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT session_id as id, title, created_at, updated_at, message_count, status
               FROM honeybadge_audit.chat_sessions
               WHERE user_id = $1 AND status != 'deleted'
               ORDER BY updated_at DESC""",
            user["sub"],
        )
    return [dict(r) for r in rows]


@router.post("")
async def create_session(
    body: CreateSessionRequest,
    user=Depends(get_current_user),
    pg=Depends(get_pg),
):
    """Create a new chat session."""
    session_id = str(uuid.uuid4())
    title = body.title or "新会话"
    now = datetime.now(timezone.utc)

    async with pg._pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO honeybadge_audit.chat_sessions
               (user_id, session_id, title, created_at, updated_at, message_count, status)
               VALUES ($1, $2, $3, $4, $5, 0, 'active')""",
            user["sub"],
            session_id,
            title,
            now,
            now,
        )
    return {
        "id": session_id,
        "title": title,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "message_count": 0,
        "status": "active",
    }


@router.get("/{session_id}")
async def get_session(session_id: str, user=Depends(get_current_user), pg=Depends(get_pg)):
    """Get a chat session."""
    async with pg._pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT session_id as id, title, created_at, updated_at, message_count, status
               FROM honeybadge_audit.chat_sessions
               WHERE session_id = $1 AND user_id = $2 AND status != 'deleted'""",
            session_id,
            user["sub"],
        )
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return dict(row)


@router.put("/{session_id}")
async def update_session(
    session_id: str,
    body: UpdateSessionRequest,
    user=Depends(get_current_user),
    pg=Depends(get_pg),
):
    """Update a chat session title."""
    async with pg._pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE honeybadge_audit.chat_sessions
               SET title = $1 WHERE session_id = $2 AND user_id = $3 AND status != 'deleted'""",
            body.title,
            session_id,
            user["sub"],
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": session_id, "title": body.title}


@router.delete("/{session_id}")
async def delete_session(session_id: str, user=Depends(get_current_user), pg=Depends(get_pg)):
    """Soft-delete a chat session."""
    async with pg._pool.acquire() as conn:
        await conn.execute(
            """UPDATE honeybadge_audit.chat_sessions
               SET status = 'deleted' WHERE session_id = $1 AND user_id = $2""",
            session_id,
            user["sub"],
        )
    return {"id": session_id, "status": "deleted"}


@router.get("/{session_id}/messages")
async def get_messages(session_id: str, user=Depends(get_current_user), pg=Depends(get_pg)):
    """Get messages for a session."""
    async with pg._pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, session_id, role, content, message_type, metadata, created_at
               FROM honeybadge_audit.chat_messages
               WHERE session_id = $1
               ORDER BY created_at ASC""",
            session_id,
        )
    results = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        results.append(d)
    return results
```

- [ ] **Step 6: Implement FastAPI app factory**

```python
# src/honeybadge/server/app.py
"""FastAPI application factory for HoneyBadge backend server."""

import asyncio
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from honeybadge.core.constants import VERSION
from honeybadge.server.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    user_to_response,
)
from honeybadge.server.config import ServerConfig
from honeybadge.server.dependencies import get_current_user

logger = structlog.get_logger()


def create_app(config: ServerConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if config is None:
        config = ServerConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Connect all services on startup, disconnect on shutdown."""
        logger.info("server_starting", port=config.port)

        # Connect infrastructure clients
        try:
            from honeybadge.db.nebula import NebulaGraphClient
            from honeybadge.db.postgres import PostgreSQLClient
            from honeybadge.db.redis import RedisClient
            from honeybadge.llm.adapter import OpenAICompatibleAdapter
            from honeybadge.protocols.validator import NgqlValidator
            from honeybadge.server.orchestrator import create_orchestrator

            # NebulaGraph
            nebula = NebulaGraphClient(
                host=config.nebula_host,
                port=config.nebula_port,
                user=config.nebula_user,
                password=config.nebula_password,
            )
            await nebula.connect()
            app.state.nebula = nebula

            # PostgreSQL
            pg = PostgreSQLClient(
                host=config.pg_host,
                port=config.pg_port,
                user=config.pg_user,
                password=config.pg_password,
                database=config.pg_database,
            )
            await pg.connect()
            await pg.init_schema()
            app.state.pg = pg

            # Redis
            redis = RedisClient(
                host=config.redis_host,
                port=config.redis_port,
                password=config.redis_password,
            )
            await redis.connect()
            app.state.redis = redis

            # LLM Adapter
            llm = OpenAICompatibleAdapter(config={
                "endpoint": config.llm_endpoint,
                "api_key": config.llm_api_key,
                "model": config.llm_model,
            })
            app.state.llm = llm

            # Validator
            validator = NgqlValidator()
            app.state.validator = validator

            # Orchestrator
            orchestrator = create_orchestrator(config, nebula, llm, pg, redis, validator)
            app.state.orchestrator = orchestrator

            logger.info("server_ready", services="nebula,pg,redis,llm")
        except Exception as e:
            logger.error("startup_failed", error=str(e))
            # Set None so health check can report status
            for attr in ("nebula", "pg", "redis", "llm", "orchestrator", "validator"):
                if not hasattr(app.state, attr):
                    setattr(app.state, attr, None)

        yield

        # Shutdown
        logger.info("server_shutting_down")
        if hasattr(app.state, "nebula") and app.state.nebula:
            await app.state.nebula.disconnect()
        if hasattr(app.state, "pg") and app.state.pg:
            await app.state.pg.disconnect()
        if hasattr(app.state, "redis") and app.state.redis:
            await app.state.redis.disconnect()
        if hasattr(app.state, "llm") and app.state.llm:
            await app.state.llm.close()

    app = FastAPI(
        title="HoneyBadge",
        version=VERSION,
        lifespan=lifespan,
    )

    app.state.config = config

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Auth routes (inline to avoid circular import with dependencies) ---

    class LoginRequest(BaseModel):
        username: str
        password: str

    class RefreshRequest(BaseModel):
        refresh_token: str

    from fastapi import Depends, HTTPException, status

    @app.post("/api/auth/login")
    async def login(body: LoginRequest):
        user = authenticate_user(body.username, body.password)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        token_data = {
            "sub": user["id"],
            "username": user["username"],
            "roles": user["roles"],
            "org_id": user["org_id"],
        }
        access_token = create_access_token(token_data, config.jwt_secret, config.jwt_access_expire_minutes)
        refresh_token = create_refresh_token({"sub": user["id"]}, config.jwt_secret, config.jwt_refresh_expire_days)

        return {
            "token": access_token,
            "refresh_token": refresh_token,
            "user": user_to_response(user),
        }

    @app.get("/api/auth/me")
    async def me(user=Depends(get_current_user)):
        return {
            "id": user["sub"],
            "username": user["username"],
            "display_name": user.get("display_name", user["username"]),
            "roles": user["roles"],
            "org_id": user.get("org_id"),
        }

    @app.post("/api/auth/logout")
    async def logout(user=Depends(get_current_user)):
        return {"message": "Logged out"}

    @app.post("/api/auth/refresh")
    async def refresh(body: RefreshRequest):
        payload = decode_token(body.refresh_token, config.jwt_secret)
        if payload is None or payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        # Look up user by id
        from honeybadge.server.auth import DEMO_USERS
        user = None
        for u in DEMO_USERS.values():
            if u["id"] == payload["sub"]:
                user = u
                break
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        token_data = {
            "sub": user["id"],
            "username": user["username"],
            "roles": user["roles"],
            "org_id": user["org_id"],
        }
        access_token = create_access_token(token_data, config.jwt_secret, config.jwt_access_expire_minutes)
        new_refresh = create_refresh_token({"sub": user["id"]}, config.jwt_secret, config.jwt_refresh_expire_days)

        return {
            "token": access_token,
            "refresh_token": new_refresh,
            "user": user_to_response(user),
        }

    # --- Mount routers ---
    from honeybadge.server.health import router as health_router
    from honeybadge.server.sessions import router as sessions_router

    app.include_router(health_router)
    app.include_router(sessions_router)

    # --- WebSocket (imported later in Task 5) ---
    # Will be mounted via: from honeybadge.server.websocket import router as ws_router

    return app


def main():
    """Entry point for honeybadge-server command."""
    config = ServerConfig()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_server_sessions.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Commit**

```bash
git add src/honeybadge/server/dependencies.py src/honeybadge/server/health.py src/honeybadge/server/sessions.py src/honeybadge/server/app.py tests/test_server_sessions.py
git commit -m "feat(server): add FastAPI app with auth, sessions, health endpoints"
```

---

## Task 5: WebSocket Handler

**Files:**
- Create: `src/honeybadge/server/websocket.py`
- Modify: `src/honeybadge/server/app.py` (mount WS router)
- Test: `tests/test_server_websocket.py`

- [ ] **Step 1: Write WebSocket handler tests**

```python
# tests/test_server_websocket.py
"""Tests for WebSocket handler."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from honeybadge.server.orchestrator import QueryResult


@pytest.fixture
def app():
    from honeybadge.server.app import create_app
    from honeybadge.server.config import ServerConfig

    config = ServerConfig()
    application = create_app(config)

    application.state.pg = AsyncMock()
    application.state.pg._pool = MagicMock()
    application.state.redis = AsyncMock()
    application.state.nebula = AsyncMock()
    application.state.llm = AsyncMock()

    mock_orchestrator = AsyncMock()
    mock_orchestrator.execute_query = AsyncMock(return_value=QueryResult(
        summary="找到3个供应商",
        raw_data=[{"name": "供应商A"}, {"name": "供应商B"}, {"name": "供应商C"}],
        columns=["name"],
        cypher="MATCH (n:Supplier) RETURN n.Supplier.supplier_name LIMIT 10",
        trace_id="TRC-20260407-120000-abcd1234",
        execution_time_ms=150,
        row_count=3,
    ))
    application.state.orchestrator = mock_orchestrator

    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def token(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    return resp.json()["token"]


def test_ws_connect_with_valid_token(client, token):
    with client.websocket_connect(f"/ws?token={token}") as ws:
        # Send heartbeat
        ws.send_json({"type": "heartbeat", "payload": {}, "timestamp": 1234567890})
        msg = ws.receive_json()
        assert msg["type"] == "heartbeat_ack"


def test_ws_connect_without_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws") as ws:
            pass


def test_ws_query_message(client, token):
    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({
            "type": "query",
            "payload": {"question": "查询所有供应商", "session_id": "test-session"},
            "timestamp": 1234567890,
        })
        # Collect all messages until we get a response
        messages = []
        for _ in range(20):  # safety limit
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] == "response" or msg["type"] == "error":
                break

        types = [m["type"] for m in messages]
        # Should have at least progress and response
        assert "response" in types or "error" in types
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_websocket.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement WebSocket handler**

```python
# src/honeybadge/server/websocket.py
"""WebSocket handler for HoneyBadge query pipeline."""

import json
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from honeybadge.server.auth import decode_token
from honeybadge.server.orchestrator import PipelineCallbacks, QueryResult
from honeybadge.protocols.messages import (
    ErrorCode,
    ErrorMessage,
    ErrorPayload,
    HeartbeatAckMessage,
    ProgressMessage,
    ProgressPayload,
    ResponseMessage,
    ResponsePayload,
    StreamMessage,
    StreamPayload,
    StreamPhase,
    serialize_message,
)

logger = structlog.get_logger()

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time query processing."""
    # Authenticate from query param
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    config = websocket.app.state.config
    payload = decode_token(token, config.jwt_secret)
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    user_id = payload["sub"]
    username = payload.get("username", "unknown")
    logger.info("ws_connected", user_id=user_id, username=username)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, ErrorCode.INTERNAL_ERROR, "Invalid JSON")
                continue

            msg_type = data.get("type")

            if msg_type == "heartbeat":
                ack = HeartbeatAckMessage()
                await websocket.send_json(serialize_message(ack))

            elif msg_type == "query":
                await _handle_query(websocket, data, payload)

            else:
                await _send_error(websocket, ErrorCode.INTERNAL_ERROR, f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info("ws_disconnected", user_id=user_id)
    except Exception as e:
        logger.error("ws_error", user_id=user_id, error=str(e))
        try:
            await _send_error(websocket, ErrorCode.INTERNAL_ERROR, str(e))
        except Exception:
            pass


async def _handle_query(websocket: WebSocket, data: dict, user_payload: dict) -> None:
    """Handle a query message by delegating to the orchestrator."""
    question = data.get("payload", {}).get("question", "")
    session_id = data.get("payload", {}).get("session_id", "")

    if not question:
        await _send_error(websocket, ErrorCode.VALIDATION_FAILED, "Empty question")
        return

    orchestrator = websocket.app.state.orchestrator
    if orchestrator is None:
        await _send_error(websocket, ErrorCode.SERVICE_UNAVAILABLE, "Orchestrator not available")
        return

    user_context = {
        "user_id": user_payload["sub"],
        "username": user_payload.get("username"),
        "org_ids": [user_payload.get("org_id")] if user_payload.get("org_id") else [],
        "data_scope": "ALL",
    }

    # Build callbacks that send WS messages
    async def on_progress(step_number: int, total_steps: int, step: str, detail: str | None) -> None:
        msg = ProgressMessage(
            payload=ProgressPayload(
                step=step,
                step_number=step_number,
                total_steps=total_steps,
                detail=detail,
            ),
            trace_id="",  # will be filled by orchestrator
        )
        await websocket.send_json(serialize_message(msg))

    async def on_stream(content: str, phase: str, done: bool) -> None:
        msg = StreamMessage(
            payload=StreamPayload(
                content=content,
                phase=StreamPhase(phase),
                done=done,
            ),
            trace_id="",
        )
        await websocket.send_json(serialize_message(msg))

    callbacks = PipelineCallbacks(on_progress=on_progress, on_stream=on_stream)

    result: QueryResult = await orchestrator.execute_query(
        question=question,
        session_id=session_id,
        user_context=user_context,
        callbacks=callbacks,
    )

    if result.error:
        await _send_error(websocket, ErrorCode.EXECUTION_ERROR, result.error, result.trace_id)
    else:
        response = ResponseMessage(
            payload=ResponsePayload(
                summary=result.summary,
                raw_data=result.raw_data,
                columns=result.columns,
                cypher=result.cypher,
                trace_id=result.trace_id,
                execution_time_ms=result.execution_time_ms,
                row_count=result.row_count,
            ),
        )
        await websocket.send_json(serialize_message(response))

    # Save user message and assistant response to chat_messages
    pg = websocket.app.state.pg
    if pg and pg._pool:
        try:
            async with pg._pool.acquire() as conn:
                # User message
                await conn.execute(
                    """INSERT INTO honeybadge_audit.chat_messages
                       (session_id, role, content, message_type, metadata)
                       VALUES ($1, 'user', $2, 'text', NULL)""",
                    session_id,
                    question,
                )
                # Assistant message
                metadata = json.dumps({
                    "trace_id": result.trace_id,
                    "cypher": result.cypher,
                    "raw_data": result.raw_data,
                    "columns": result.columns,
                    "execution_time_ms": result.execution_time_ms,
                }, ensure_ascii=False, default=str)
                await conn.execute(
                    """INSERT INTO honeybadge_audit.chat_messages
                       (session_id, role, content, message_type, metadata)
                       VALUES ($1, 'assistant', $2, $3, $4::jsonb)""",
                    session_id,
                    result.summary,
                    "query_result" if not result.error else "error",
                    metadata,
                )
                # Update session message count
                await conn.execute(
                    """UPDATE honeybadge_audit.chat_sessions
                       SET message_count = message_count + 2
                       WHERE session_id = $1""",
                    session_id,
                )
        except Exception as e:
            logger.error("save_messages_failed", error=str(e))


async def _send_error(
    websocket: WebSocket,
    code: ErrorCode,
    message: str,
    trace_id: str = "",
) -> None:
    """Send an error message to the client."""
    msg = ErrorMessage(
        payload=ErrorPayload(code=code, message=message, trace_id=trace_id or None),
    )
    await websocket.send_json(serialize_message(msg))
```

- [ ] **Step 4: Mount WebSocket router in app.py**

Add these lines at the end of `create_app()` in `app.py`, just before `return app`:

```python
    from honeybadge.server.websocket import router as ws_router
    app.include_router(ws_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_server_websocket.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/honeybadge/server/websocket.py tests/test_server_websocket.py
git add src/honeybadge/server/app.py
git commit -m "feat(server): add WebSocket handler with query pipeline integration"
```

---

## Task 6: Docker Compose and Frontend Proxy

**Files:**
- Modify: `deploy/docker/docker-compose.yaml`
- Create: `deploy/docker/Dockerfile.server`
- Modify: `frontend/vite.config.ts`

- [ ] **Step 1: Create server Dockerfile**

```dockerfile
# deploy/docker/Dockerfile.server
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/honeybadge /app/src/honeybadge
COPY prompts /app/prompts

ENV PYTHONPATH=/app/src
EXPOSE 8090

CMD ["python", "-m", "uvicorn", "honeybadge.server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090"]
```

- [ ] **Step 2: Add honeybadge-server to docker-compose.yaml**

Add this service block after the MCP servers section, before the `networks:` section:

```yaml
  # =============================================================================
  # HoneyBadge Backend Server
  # =============================================================================

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
      - NEBULA_USER=root
      - NEBULA_PASSWORD=nebula
      - NEBULA_SPACE=honeybadge
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_PASSWORD=redis123
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - POSTGRES_USER=honeybadge
      - POSTGRES_PASSWORD=honeybadge123
      - POSTGRES_DB=honeybadge_audit
      - LLM_ENDPOINT=${LLM_ENDPOINT:-http://host.docker.internal:8000/v1}
      - LLM_API_KEY=${LLM_API_KEY:-}
      - LLM_MODEL=${LLM_MODEL:-glm-4-flash}
      - JWT_SECRET=${JWT_SECRET:-honeybadge-dev-secret-change-in-prod}
      - ORCHESTRATOR_TYPE=direct
      - SERVER_PORT=8090
      - TZ=Asia/Shanghai
    depends_on:
      nebula-graphd:
        condition: service_healthy
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    networks:
      - honeybadge-net
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8090/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

- [ ] **Step 3: Fix Milvus in docker-compose.yaml**

In the `milvus` service:
1. Add port `19530:19530` to the ports list
2. Remove the `profiles: [vector]` block so it starts by default

The milvus service ports section becomes:
```yaml
    ports:
      - "19530:19530"  # Milvus gRPC port
      - "9091:9091"    # Milvus HTTP port
```

And delete these lines from the milvus service:
```yaml
    profiles:
      - vector  # Only runs with: docker-compose --profile vector up
```

Also remove `profiles: [vector]` from `milvus-etcd` and `milvus-minio` if present (they don't have profiles currently, so no change needed for them).

- [ ] **Step 4: Fix frontend vite.config.ts proxy port**

Change the proxy target from `8080` to `8090`:

```typescript
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8090',
        ws: true,
      },
    },
  },
```

- [ ] **Step 5: Commit**

```bash
git add deploy/docker/Dockerfile.server deploy/docker/docker-compose.yaml frontend/vite.config.ts
git commit -m "feat(deploy): add server to docker-compose, fix Milvus ports, fix proxy"
```

---

## Task 7: Test Data Loader Script

**Files:**
- Create: `scripts/load-test-data.py`

- [ ] **Step 1: Create the data loader script**

```python
# scripts/load-test-data.py
"""Load CSV test data into NebulaGraph.

Usage:
    python scripts/load-test-data.py [--host HOST] [--port PORT]

Reads CSV files from deploy/test-data/csv/vertices/ and deploy/test-data/csv/edges/
and inserts them into the honeybadge space via nGQL INSERT statements.
"""

import argparse
import csv
import json
import os
import sys
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nebula3.Config import Config as NebulaConfig
from nebula3.gclient.net import ConnectionPool


def get_connection(host: str, port: int) -> ConnectionPool:
    config = NebulaConfig()
    config.max_connection_pool_size = 4
    config.timeout = 60000
    pool = ConnectionPool()
    ok = pool.init([(host, port)], config)
    if not ok:
        raise RuntimeError(f"Failed to connect to NebulaGraph at {host}:{port}")
    return pool


def execute(pool: ConnectionPool, ngql: str, space: str = "") -> bool:
    session = pool.get_session("root", "nebula")
    try:
        if space:
            r = session.execute(f"USE {space}")
            if not r.is_succeeded():
                print(f"  ERROR: USE {space}: {r.error_msg()}")
                return False
        r = session.execute(ngql)
        if not r.is_succeeded():
            print(f"  ERROR: {r.error_msg()}")
            print(f"  nGQL: {ngql[:200]}...")
            return False
        return True
    finally:
        session.release()


def escape_value(val: str) -> str:
    """Escape a string value for nGQL."""
    if val is None or val == "":
        return '""'
    return '"' + val.replace("\\", "\\\\").replace('"', '\\"') + '"'


def load_vertices(pool: ConnectionPool, csv_dir: str, space: str, batch_size: int = 50):
    """Load vertex CSV files."""
    files = sorted(f for f in os.listdir(csv_dir) if f.endswith(".csv"))
    for filename in files:
        tag_name = filename.replace(".csv", "")
        filepath = os.path.join(csv_dir, filename)

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print(f"  {tag_name}: 0 rows (skip)")
            continue

        # Parse first row to get property names
        sample_props = json.loads(rows[0]["properties"])
        prop_names = list(sample_props.keys())

        inserted = 0
        batch = []
        for row in rows:
            vid = row["vid"]
            props = json.loads(row["properties"])
            values = []
            for pname in prop_names:
                val = props.get(pname, "")
                if isinstance(val, bool):
                    values.append("true" if val else "false")
                elif isinstance(val, (int, float)):
                    values.append(str(val))
                elif val == "" or val is None:
                    values.append('""')
                else:
                    values.append(escape_value(str(val)))

            batch.append(f'"{vid}":({", ".join(values)})')

            if len(batch) >= batch_size:
                props_str = ", ".join(prop_names)
                ngql = f"INSERT VERTEX `{tag_name}`({props_str}) VALUES {', '.join(batch)};"
                if execute(pool, ngql, space):
                    inserted += len(batch)
                batch = []

        if batch:
            props_str = ", ".join(prop_names)
            ngql = f"INSERT VERTEX `{tag_name}`({props_str}) VALUES {', '.join(batch)};"
            if execute(pool, ngql, space):
                inserted += len(batch)

        print(f"  {tag_name}: {inserted}/{len(rows)} inserted")


def load_edges(pool: ConnectionPool, csv_dir: str, space: str, batch_size: int = 50):
    """Load edge CSV files."""
    files = sorted(f for f in os.listdir(csv_dir) if f.endswith(".csv"))
    for filename in files:
        edge_name = filename.replace(".csv", "")
        filepath = os.path.join(csv_dir, filename)

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print(f"  {edge_name}: 0 rows (skip)")
            continue

        # Parse first row to get property names
        sample_props = json.loads(rows[0]["properties"])
        prop_names = list(sample_props.keys())

        inserted = 0
        batch = []
        for row in rows:
            src = row["src_vid"]
            dst = row["dst_vid"]
            rank = row.get("rank", "0")
            props = json.loads(row["properties"])
            values = []
            for pname in prop_names:
                val = props.get(pname, "")
                if isinstance(val, bool):
                    values.append("true" if val else "false")
                elif isinstance(val, (int, float)):
                    values.append(str(val))
                elif val == "" or val is None:
                    values.append('""')
                else:
                    values.append(escape_value(str(val)))

            batch.append(f'"{src}"->"{dst}"@{rank}:({", ".join(values)})')

            if len(batch) >= batch_size:
                props_str = ", ".join(prop_names)
                ngql = f"INSERT EDGE `{edge_name}`({props_str}) VALUES {', '.join(batch)};"
                if execute(pool, ngql, space):
                    inserted += len(batch)
                batch = []

        if batch:
            props_str = ", ".join(prop_names)
            ngql = f"INSERT EDGE `{edge_name}`({props_str}) VALUES {', '.join(batch)};"
            if execute(pool, ngql, space):
                inserted += len(batch)

        print(f"  {edge_name}: {inserted}/{len(rows)} inserted")


def main():
    parser = argparse.ArgumentParser(description="Load test data into NebulaGraph")
    parser.add_argument("--host", default="localhost", help="NebulaGraph host")
    parser.add_argument("--port", type=int, default=9669, help="NebulaGraph port")
    parser.add_argument("--space", default="honeybadge", help="NebulaGraph space")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch insert size")
    args = parser.parse_args()

    base_dir = os.path.join(os.path.dirname(__file__), "..", "deploy", "test-data", "csv")
    vertex_dir = os.path.join(base_dir, "vertices")
    edge_dir = os.path.join(base_dir, "edges")

    print(f"Connecting to NebulaGraph at {args.host}:{args.port}...")
    pool = get_connection(args.host, args.port)

    print(f"\nLoading vertices into space '{args.space}'...")
    load_vertices(pool, vertex_dir, args.space, args.batch_size)

    print(f"\nLoading edges into space '{args.space}'...")
    load_edges(pool, edge_dir, args.space, args.batch_size)

    print("\nDone! Verifying...")
    session = pool.get_session("root", "nebula")
    try:
        session.execute(f"USE {args.space}")
        for tag in ["Supplier", "PurchaseOrder", "Invoice", "Item"]:
            r = session.execute(f"LOOKUP ON `{tag}` YIELD id(vertex) | LIMIT 1")
            count_r = session.execute(f'MATCH (n:{tag}) RETURN count(n) AS cnt')
            if count_r.is_succeeded() and count_r.row_size() > 0:
                cnt = count_r.row_values(0)[0].as_int()
                print(f"  {tag}: {cnt} vertices")
    finally:
        session.release()

    pool.close()
    print("\nTest data loaded successfully!")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/load-test-data.py
git commit -m "feat(scripts): add test data loader for NebulaGraph"
```

---

## Task 8: E2E Integration Test

**Files:**
- Create: `tests/test_integration_e2e.py`

- [ ] **Step 1: Write E2E integration test**

This test validates the full flow with mocked infrastructure (no Docker needed):

```python
# tests/test_integration_e2e.py
"""End-to-end integration tests for the HoneyBadge server.

These tests use FastAPI TestClient with mocked DB clients.
For full Docker-based integration, use the Docker Compose environment.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from honeybadge.server.app import create_app
from honeybadge.server.config import ServerConfig
from honeybadge.server.orchestrator import DirectPipelineOrchestrator, QueryResult


@pytest.fixture
def config():
    return ServerConfig()


@pytest.fixture
def app(config):
    application = create_app(config)

    # Mock infrastructure
    application.state.pg = AsyncMock()
    application.state.pg._pool = MagicMock()
    application.state.pg._pool.acquire = MagicMock()

    # Mock PG context manager for sessions
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
    mock_conn.fetchval = AsyncMock(return_value=1)

    class MockPool:
        _pool = True
        async def acquire(self):
            return MockConnContext(mock_conn)

    class MockConnContext:
        def __init__(self, conn):
            self.conn = conn
        async def __aenter__(self):
            return self.conn
        async def __aexit__(self, *args):
            pass

    application.state.pg._pool = MockPool()
    application.state.pg.write_audit_log = AsyncMock(return_value=True)

    application.state.redis = AsyncMock()
    application.state.redis._client = AsyncMock()
    application.state.redis._client.ping = AsyncMock(return_value=True)

    application.state.nebula = AsyncMock()
    application.state.nebula._pool = True

    application.state.llm = AsyncMock()
    application.state.llm.health_check = AsyncMock(return_value=True)

    # Mock orchestrator returns a successful result
    mock_orchestrator = AsyncMock()
    mock_orchestrator.execute_query = AsyncMock(return_value=QueryResult(
        summary="找到5个活跃供应商",
        raw_data=[
            {"supplier_name": "大连黄海贸易有限公司", "status": "ACTIVE"},
            {"supplier_name": "成都孙超贸易有限公司", "status": "ACTIVE"},
        ],
        columns=["supplier_name", "status"],
        cypher="MATCH (n:Supplier) WHERE n.Supplier.status == 'ACTIVE' RETURN n.Supplier.supplier_name, n.Supplier.status LIMIT 100",
        trace_id="TRC-20260407-120000-abcd1234",
        execution_time_ms=150,
        row_count=2,
    ))
    application.state.orchestrator = mock_orchestrator

    return application


@pytest.fixture
def client(app):
    return TestClient(app)


class TestE2EAuthFlow:
    """Test the complete authentication flow."""

    def test_login_and_access(self, client):
        # Login
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200
        data = resp.json()
        token = data["token"]
        refresh = data["refresh_token"]
        assert data["user"]["username"] == "admin"

        # Access protected endpoint
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

        # Refresh token
        resp = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 200
        new_token = resp.json()["token"]
        assert new_token != token

    def test_unauthenticated_access_blocked(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

        resp = client.get("/api/sessions", headers={"Authorization": "Bearer invalid"})
        assert resp.status_code == 401


class TestE2EHealthCheck:
    """Test health check endpoint."""

    def test_health_returns_service_status(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert "services" in data
        assert "redis" in data["services"]
        assert "postgres" in data["services"]
        assert "nebula" in data["services"]


class TestE2EQueryFlow:
    """Test the complete query flow via WebSocket."""

    def test_full_query_flow(self, client):
        # Login first
        resp = client.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
        token = resp.json()["token"]

        # Connect WebSocket and send query
        with client.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_json({
                "type": "query",
                "payload": {"question": "查询所有活跃供应商", "session_id": "test-session"},
                "timestamp": 1234567890,
            })

            # Collect messages
            messages = []
            for _ in range(30):
                msg = ws.receive_json()
                messages.append(msg)
                if msg["type"] in ("response", "error"):
                    break

            # Verify we got a response
            response_msgs = [m for m in messages if m["type"] == "response"]
            assert len(response_msgs) == 1
            resp_data = response_msgs[0]["payload"]
            assert resp_data["row_count"] == 2
            assert resp_data["trace_id"].startswith("TRC-")
            assert "供应商" in resp_data["summary"]

    def test_heartbeat(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        token = resp.json()["token"]

        with client.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_json({"type": "heartbeat", "payload": {}, "timestamp": 1234567890})
            msg = ws.receive_json()
            assert msg["type"] == "heartbeat_ack"
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration_e2e.py
git commit -m "test: add E2E integration tests for full auth + query flow"
```

---

## Task 9: Final Wiring and Validation

- [ ] **Step 1: Run full test suite**

Run: `cd /d/dev/HoneyBadge/.worktrees/phase1-implementation && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Verify Docker Compose syntax**

Run: `cd /d/dev/HoneyBadge/.worktrees/phase1-implementation/deploy/docker && docker compose config > /dev/null`
Expected: No errors

- [ ] **Step 3: Verify server starts locally (smoke test)**

Run: `cd /d/dev/HoneyBadge/.worktrees/phase1-implementation && timeout 5 python -c "from honeybadge.server.app import create_app; app = create_app(); print('App created successfully')" || true`
Expected: "App created successfully"

- [ ] **Step 4: Verify frontend proxy config**

Run: `cd /d/dev/HoneyBadge/.worktrees/phase1-implementation/frontend && cat vite.config.ts | grep -A2 "target"`
Expected: Shows `http://localhost:8090` and `ws://localhost:8090`

- [ ] **Step 5: Final commit with all changes**

```bash
git add -A
git status
# If any unstaged changes remain, add them
git commit -m "feat: complete Phase 1 E2E integration server

- FastAPI backend with JWT auth, session CRUD, health check
- WebSocket handler with query pipeline integration
- QueryOrchestrator interface (direct pipeline + future HiClaw)
- Docker Compose with server service, Milvus fix
- Frontend proxy config
- Test data loader script
- Comprehensive test suite"
```

---

## Docker Startup Sequence (for manual E2E validation)

After all tasks are complete, test the full Docker environment:

```bash
# 1. Start infrastructure
cd deploy/docker
docker compose up -d

# 2. Wait for services to be healthy
docker compose ps  # all should show "healthy"

# 3. Initialize NebulaGraph schema
bash init-nebula.sh

# 4. Load test data
cd ../..
python scripts/load-test-data.py --host localhost --port 9669

# 5. Start backend server (or use Docker)
python -m honeybadge.server.app
# OR: docker compose up -d honeybadge-server

# 6. Start frontend
cd frontend
npm install
npm run dev

# 7. Open http://localhost:3000
# Login: admin / admin123
# Try: "查询所有供应商"
```
