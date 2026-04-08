# Matrix Gateway Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 HoneyBadge 从"编排服务"重构为"轻量 Matrix 网关"，查询逻辑下沉到 HiClaw Worker。

**Architecture:** honeybadge-server 作为 Matrix 客户端（@honeybadge-gateway），通过 Matrix DM 与 HiClaw Manager 通信。启动时通过 Matrix 请求 Worker 获取 schema 缓存（供 Manager/Worker 使用）。用户 query 在网关层只做输入过滤（空问题/写操作检测），实际 L1-L3 验证在 Worker 侧执行。Worker 执行结果通过 Matrix 透传给用户。

**Tech Stack:** Python 3.10+, matrix-nio (Matrix SDK), FastAPI, asyncpg

---

## File Structure

### New Files
- `src/honeybadge/gateway/__init__.py` — gateway 模块导出
- `src/honeybadge/gateway/matrix_client.py` — Matrix 客户端封装（基于 matrix-nio）
- `src/honeybadge/gateway/schema_cache.py` — L2 schema 缓存管理
- `src/honeybadge/gateway/room_manager.py` — session_id → Matrix room_id 映射
- `tests/test_matrix_client.py` — MatrixClient 单元测试
- `tests/test_schema_cache.py` — SchemaCache 单元测试
- `tests/test_room_manager.py` — RoomManager 单元测试

### Modified Files
- `src/honeybadge/server/app.py:27-82` — lifespan 中初始化 MatrixClient 和 SchemaCache，启动时向 Manager 请求 schema
- `src/honeybadge/server/websocket.py:31-148` — 重构 `_handle_query`，L1-L3 验证后通过 MatrixClient 发送，监听 Matrix 事件回传
- `src/honeybadge/db/postgres.py:85-121` — `init_schema()` 中添加 `chat_sessions` 和 `chat_messages` 表
- `src/honeybadge/protocols/validator.py` — `NgqlValidator` 保留，`load_schema()` 需被调用（由 schema_cache 触发）
- `src/honeybadge/server/config.py` — 添加 Matrix 相关配置项（matrix_homeserver_url, matrix_user_id, matrix_user_password）

---

## Task 1: Add Matrix Configuration

**Files:**
- Modify: `src/honeybadge/server/config.py`

- [ ] **Step 1: Read current config.py**

Run: `cat src/honeybadge/server/config.py`

- [ ] **Step 2: Add Matrix config fields**

```python
# In ServerConfig dataclass, add these fields:
matrix_homeserver_url: str = field(default="http://localhost:8008")
matrix_user_id: str = field(default="@honeybadge-gateway:matrix.local")
matrix_user_password: str = field(default="")
```

- [ ] **Step 3: Write the change**

Run: Edit `src/honeybadge/server/config.py` — add the three Matrix fields above to the `ServerConfig` dataclass.

- [ ] **Step 4: Add test for Matrix config**

```python
# tests/test_server_config.py - add to TestDefaultConfig class
def test_default_matrix_fields(self):
    config = ServerConfig()
    assert config.matrix_homeserver_url == "http://localhost:8008"
    assert config.matrix_user_id == "@honeybadge-gateway:matrix.local"
    assert config.matrix_user_password == ""
```

- [ ] **Step 5: Run tests**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_server_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/honeybadge/server/config.py tests/test_server_config.py
git commit -m "feat(config): add Matrix homeserver configuration fields"
```

---

## Task 2: Create SchemaCache Module

**Files:**
- Create: `src/honeybadge/gateway/schema_cache.py`
- Create: `src/honeybadge/gateway/__init__.py`
- Test: `tests/test_schema_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema_cache.py
import pytest
from honeybadge.gateway.schema_cache import SchemaCache, SchemaTag, SchemaEdge, SchemaProperty


def test_schema_cache_starts_empty():
    cache = SchemaCache()
    assert cache.get_tags() == {}
    assert cache.get_edges() == {}


def test_schema_cache_load_schema():
    cache = SchemaCache()
    tags = [
        SchemaTag(name="Supplier", properties=[SchemaProperty(name="id", type="string"), SchemaProperty(name="name", type="string")]),
        SchemaTag(name="PurchaseOrder", properties=[SchemaProperty(name="id", type="string"), SchemaProperty(name="amount", type="double")]),
    ]
    edges = [
        SchemaEdge(name="PLACED_WITH", properties=[SchemaProperty(name="date", type="string")]),
    ]
    cache.load_schema(tags, edges)

    assert "SUPPLIER" in cache.get_tags()
    assert "PURCHASEORDER" in cache.get_tags()
    assert "PLACED_WITH" in cache.get_edges()
    assert cache.get_tags()["SUPPLIER"].properties[0].name == "id"


def test_schema_cache_is_ready():
    cache = SchemaCache()
    assert not cache.is_ready()

    cache.load_schema([], [])
    assert cache.is_ready()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_schema_cache.py -v`
Expected: FAIL — import error or test failures

- [ ] **Step 3: Create `src/honeybadge/gateway/__init__.py`**

```python
"""HoneyBadge Matrix Gateway modules."""
from honeybadge.gateway.schema_cache import SchemaCache
from honeybadge.gateway.room_manager import RoomManager
from honeybadge.gateway.matrix_client import MatrixClient

__all__ = ["SchemaCache", "RoomManager", "MatrixClient"]
```

- [ ] **Step 4: Write `src/honeybadge/gateway/schema_cache.py`**

```python
"""L2 schema cache for Anti-Hallucination Framework (L2 Schema Validation)."""
from dataclasses import dataclass, field
from typing import Any

from honeybadge.protocols.validator import SchemaTag, SchemaEdge


@dataclass
class SchemaCache:
    """
    Caches NebulaGraph schema for L2 validation.

    Schema is obtained via Matrix message to HiClaw Worker at startup.
    """

    _tags: dict[str, SchemaTag] = field(default_factory=dict)
    _edges: dict[str, SchemaEdge] = field(default_factory=dict)
    _ready: bool = False

    def load_schema(self, tags: list[SchemaTag], edges: list[SchemaEdge]) -> None:
        """Load schema from tags and edges list."""
        self._tags = {tag.name.upper(): tag for tag in tags}
        self._edges = {edge.name.upper(): edge for edge in edges}
        self._ready = True

    def get_tags(self) -> dict[str, SchemaTag]:
        """Get all schema tags."""
        return self._tags

    def get_edges(self) -> dict[str, SchemaEdge]:
        """Get all schema edges."""
        return self._edges

    def is_ready(self) -> bool:
        """Check if schema has been loaded."""
        return self._ready

    def get_schema_as_tags_edges(self) -> tuple[list[SchemaTag], list[SchemaEdge]]:
        """Return schema as lists (for NgqlValidator.load_schema)."""
        return list(self._tags.values()), list(self._edges.values())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_schema_cache.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/honeybadge/gateway/__init__.py src/honeybadge/gateway/schema_cache.py tests/test_schema_cache.py
git commit -m "feat(gateway): add SchemaCache for L2 validation"
```

---

## Task 3: Create RoomManager Module

**Files:**
- Create: `src/honeybadge/gateway/room_manager.py`
- Test: `tests/test_room_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_room_manager.py
import pytest
from honeybadge.gateway.room_manager import RoomManager


def test_room_manager_starts_empty():
    rm = RoomManager()
    assert rm.get_room_id("session_123") is None
    assert list(rm.list_sessions()) == []


def test_room_manager_register_and_get():
    rm = RoomManager()
    rm.register("session_123", "!abc123:matrix.local")

    assert rm.get_room_id("session_123") == "!abc123:matrix.local"
    assert "session_123" in rm.list_sessions()


def test_room_manager_unregister():
    rm = RoomManager()
    rm.register("session_123", "!abc123:matrix.local")
    rm.unregister("session_123")

    assert rm.get_room_id("session_123") is None


def test_room_manager_trace_to_session():
    rm = RoomManager()
    rm.register("session_123", "!abc123:matrix.local", trace_id="HB-001")

    assert rm.get_session_id_by_trace("HB-001") == "session_123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_room_manager.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write `src/honeybadge/gateway/room_manager.py`**

```python
"""Session to Matrix room mapping manager."""
from dataclasses import dataclass, field


@dataclass
class RoomManager:
    """
    Manages session_id → Matrix room_id mappings.

    Each user session has one Matrix DM room with the HiClaw Manager.
    """

    _session_to_room: dict[str, str] = field(default_factory=dict)
    _room_to_session: dict[str, str] = field(default_factory=dict)
    _trace_to_session: dict[str, str] = field(default_factory=dict)

    def register(self, session_id: str, room_id: str, trace_id: str | None = None) -> None:
        """Register a session to Matrix room mapping."""
        self._session_to_room[session_id] = room_id
        self._room_to_session[room_id] = session_id
        if trace_id:
            self._trace_to_session[trace_id] = session_id

    def unregister(self, session_id: str) -> None:
        """Unregister a session."""
        room_id = self._session_to_room.pop(session_id, None)
        if room_id:
            self._room_to_session.pop(room_id, None)

    def get_room_id(self, session_id: str) -> str | None:
        """Get Matrix room_id for a session."""
        return self._session_to_room.get(session_id)

    def get_session_id(self, room_id: str) -> str | None:
        """Get session_id for a Matrix room."""
        return self._room_to_session.get(room_id)

    def get_session_id_by_trace(self, trace_id: str) -> str | None:
        """Get session_id by trace_id."""
        return self._trace_to_session.get(trace_id)

    def register_trace(self, trace_id: str, session_id: str) -> None:
        """Register a trace_id to session mapping."""
        self._trace_to_session[trace_id] = session_id

    def list_sessions(self) -> list[str]:
        """List all active session IDs."""
        return list(self._session_to_room.keys())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_room_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/honeybadge/gateway/room_manager.py tests/test_room_manager.py
git commit -m "feat(gateway): add RoomManager for session-room mapping"
```

---

## Task 4: Create MatrixClient Module

**Files:**
- Create: `src/honeybadge/gateway/matrix_client.py`
- Test: `tests/test_matrix_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_matrix_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from honeybadge.gateway.matrix_client import MatrixClient, MatrixMessage


def test_matrix_message_serialization():
    msg = MatrixMessage(
        msgtype="gateway_query",
        question="供应商V001的订单有哪些？",
        trace_id="HB-001",
        user_id="admin",
        org_id="org001",
    )
    data = msg.to_dict()

    assert data["type"] == "gateway_query"
    assert data["question"] == "供应商V001的订单有哪些？"
    assert data["trace_id"] == "HB-001"
    assert data["user_id"] == "admin"


def test_matrix_message_parse_response():
    raw = {
        "type": "result",
        "trace_id": "HB-001",
        "data": {"rows": [{"id": "PO001"}]},
        "summary": "查询到1条采购订单",
    }
    msg = MatrixMessage.from_dict(raw)

    assert msg.msgtype == "result"
    assert msg.trace_id == "HB-001"
    assert msg.data == {"rows": [{"id": "PO001"}]}


def test_matrix_message_parse_error():
    raw = {
        "type": "error",
        "trace_id": "HB-001",
        "error_code": "L2_SCHEMA",
        "error_message": "Tag not found",
        "recoverable": False,
    }
    msg = MatrixMessage.from_dict(raw)

    assert msg.msgtype == "error"
    assert msg.error_code == "L2_SCHEMA"
    assert msg.recoverable is False


@pytest.mark.asyncio
async def test_matrix_client_bootstrap_fetches_schema():
    with patch("honeybadge.gateway.matrix_client.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_client.sync.return_value = None

        from honeybadge.gateway.schema_cache import SchemaCache
        from honeybadge.protocols.validator import SchemaTag, SchemaEdge

        client = MatrixClient(
            homeserver_url="http://localhost:8008",
            user_id="@honeybadge-gateway:matrix.local",
            password="secret",
        )

        # Mock the schema response from Worker
        async def mock_send_and_wait_for_schema(*args, **kwargs):
            return MatrixMessage(
                msgtype="schema_response",
                trace_id="__bootstrap__",
                tags=[SchemaTag(name="Supplier", properties=[])],
                edges=[SchemaEdge(name="PLACED_WITH", properties=[])],
            )

        client._send_and_wait_for_response = AsyncMock(side_effect=mock_send_and_wait_for_schema)
        schema_cache = SchemaCache()
        await client.bootstrap_schema(schema_cache)

        assert schema_cache.is_ready()
        assert "SUPPLIER" in schema_cache.get_tags()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_matrix_client.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write `src/honeybadge/gateway/matrix_client.py`**

```python
"""Matrix client for HoneyBadge gateway - communicates with HiClaw Manager via Matrix DM."""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

from honeybadge.gateway.room_manager import RoomManager
from honeybadge.gateway.schema_cache import SchemaCache

logger = structlog.get_logger()


# Matrix event callback type
MatrixEventCallback = Callable[["MatrixMessage"], Awaitable[None]]


@dataclass
class MatrixMessage:
    """Message sent/received via Matrix."""

    msgtype: str  # "gateway_query", "result", "error", "schema_response", "get_schema"
    question: str = ""
    trace_id: str = ""
    user_id: str = ""
    org_id: str = ""
    roles: list[str] = field(default_factory=list)
    data: dict[str, Any] | None = None
    summary: str = ""
    error_code: str = ""
    error_message: str = ""
    recoverable: bool = True
    # Schema response fields
    tags: list[Any] = field(default_factory=list)
    edges: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for Matrix event content."""
        base = {"type": self.msgtype, "trace_id": self.trace_id}
        if self.question:
            base["question"] = self.question
        if self.user_id:
            base["user_id"] = self.user_id
        if self.org_id:
            base["org_id"] = self.org_id
        if self.roles:
            base["roles"] = self.roles
        if self.data:
            base["data"] = self.data
        if self.summary:
            base["summary"] = self.summary
        if self.error_code:
            base["error_code"] = self.error_code
        if self.error_message:
            base["error_message"] = self.error_message
        base["recoverable"] = self.recoverable
        if self.tags:
            base["tags"] = self.tags
        if self.edges:
            base["edges"] = self.edges
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatrixMessage":
        """Parse from Matrix event content dict."""
        return cls(
            msgtype=data.get("type", "unknown"),
            question=data.get("question", ""),
            trace_id=data.get("trace_id", ""),
            user_id=data.get("user_id", ""),
            org_id=data.get("org_id", ""),
            roles=data.get("roles", []),
            data=data.get("data"),
            summary=data.get("summary", ""),
            error_code=data.get("error_code", ""),
            error_message=data.get("error_message", ""),
            recoverable=data.get("recoverable", True),
            tags=data.get("tags", []),
            edges=data.get("edges", []),
        )


class MatrixClient:
    """
    Matrix client for HoneyBadge gateway.

    Sends queries to HiClaw Manager via Matrix DM and listens for responses.
    """

    def __init__(
        self,
        homeserver_url: str,
        user_id: str,
        password: str,
        room_manager: RoomManager,
        on_result: MatrixEventCallback | None = None,
        on_error: MatrixEventCallback | None = None,
    ):
        self.homeserver_url = homeserver_url
        self.user_id = user_id
        self.password = password
        self.room_manager = room_manager
        self.on_result = on_result
        self.on_error = on_error
        self._client = None  # matrix-nio Client instance
        self._running = False
        self._pending_responses: dict[str, asyncio.Future[MatrixMessage]] = {}
        self._listening_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Connect to Matrix homeserver and log in."""
        try:
            from nio import Client, LoginResponse
        except ImportError:
            logger.warning("matrix_nio_not_installed", note="Using mock client for development")
            self._client = None
            return

        self._client = Client(self.homeserver_url)
        resp = await self._client.login(self.password)
        if not isinstance(resp, LoginResponse):
            raise RuntimeError(f"Matrix login failed: {resp}")
        logger.info("matrix_connected", user=self.user_id)

    async def disconnect(self) -> None:
        """Disconnect from Matrix."""
        self._running = False
        if self._listening_task:
            self._listening_task.cancel()
            self._listening_task = None
        if self._client:
            await self._client.close()
            self._client = None
        logger.info("matrix_disconnected")

    async def send_query(
        self,
        question: str,
        trace_id: str,
        user_id: str,
        org_id: str,
        roles: list[str],
        session_id: str,
    ) -> None:
        """
        Send a user query to the HiClaw Manager via Matrix DM.

        Creates a DM room with Manager if not already established.
        """
        if self._client is None:
            logger.warning("matrix_client_mock_mode", note="Cannot send real Matrix message")
            return

        room_id = self.room_manager.get_room_id(session_id)
        if not room_id:
            # Create DM with Manager (derive manager user_id from homeserver)
            manager_user = "@hiclaw-manager:" + self.homeserver_url.split("//")[1]
            room_id = await self._client.room_create(
                invite=manager_user,
                is_direct=True,
            )
            self.room_manager.register(session_id, room_id, trace_id)
            logger.info("matrix_room_created", session_id=session_id, room_id=room_id)

        msg = MatrixMessage(
            msgtype="gateway_query",
            question=question,
            trace_id=trace_id,
            user_id=user_id,
            org_id=org_id,
            roles=roles,
        )
        await self._client.room_send(room_id, "m.room.message", msg.to_dict())
        logger.info("matrix_query_sent", trace_id=trace_id, room_id=room_id)

    async def bootstrap_schema(self, schema_cache: SchemaCache) -> None:
        """
        Request schema from Worker via Matrix at startup.

        Sends a get_schema message and waits for Worker response.
        """
        if self._client is None:
            logger.warning("matrix_bootstrap_mock_mode")
            # In mock/dev mode, load empty schema to allow startup
            schema_cache.load_schema([], [])
            return

        future: asyncio.Future[MatrixMessage] = asyncio.Future()
        self._pending_responses["__bootstrap__"] = future

        try:
            manager_user = "@hiclaw-manager:" + self.homeserver_url.split("//")[1]
            room_id = await self._client.room_create(invite=manager_user, is_direct=True)

            bootstrap_msg = MatrixMessage(msgtype="get_schema", trace_id="__bootstrap__")
            await self._client.room_send(room_id, "m.room.message", bootstrap_msg.to_dict())

            logger.info("matrix_schema_request_sent", room_id=room_id)
            response = await asyncio.wait_for(future, timeout=30.0)

            # Parse tags and edges into SchemaTag/SchemaEdge
            from honeybadge.protocols.validator import SchemaTag, SchemaEdge
            tags = [SchemaTag(name=t.name, properties=[]) for t in response.tags]
            edges = [SchemaEdge(name=e.name, properties=[]) for e in response.edges]
            schema_cache.load_schema(tags, edges)
            logger.info("matrix_schema_cached", tag_count=len(tags), edge_count=len(edges))

        except asyncio.TimeoutError:
            logger.error("matrix_schema_bootstrap_timeout")
            schema_cache.load_schema([], [])
        finally:
            self._pending_responses.pop("__bootstrap__", None)

    async def _on_matrix_event(self, room_id: str, event: Any) -> None:
        """Handle incoming Matrix events."""
        if self._client is None:
            return

        from nio import RoomMessage

        if isinstance(event, RoomMessage):
            content = event.source.get("content", {})
            msg = MatrixMessage.from_dict(content)

            # Route response by trace_id
            if msg.trace_id and msg.trace_id in self._pending_responses:
                future = self._pending_responses.pop(msg.trace_id)
                if not future.done():
                    future.set_result(msg)
                return

            # Dispatch to callbacks
            if msg.msgtype == "result" and self.on_result:
                session_id = self.room_manager.get_session_id(room_id) or self.room_manager.get_session_id_by_trace(msg.trace_id)
                if session_id:
                    self.room_manager.register_trace(msg.trace_id, session_id)
                await self.on_result(msg)
            elif msg.msgtype == "error" and self.on_error:
                await self.on_error(msg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_matrix_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/honeybadge/gateway/matrix_client.py tests/test_matrix_client.py
git commit -m "feat(gateway): add MatrixClient for HiClaw Manager communication"
```

---

## Task 5: Fix PostgreSQL Schema — Add chat_sessions and chat_messages Tables

**Files:**
- Modify: `src/honeybadge/db/postgres.py:85-121`

- [ ] **Step 1: Read current init_schema**

Run: `cat src/honeybadge/db/postgres.py | grep -n "init_schema" -A 40`

- [ ] **Step 2: Write the fix**

Replace `init_schema()` body to include `chat_sessions` and `chat_messages` tables:

```python
async def init_schema(self) -> None:
    """Initialize audit log and chat session schema."""
    if not self._pool:
        raise PostgreSQLError("Not connected to PostgreSQL")

    async with self._pool.acquire() as conn:
        # audit_logs table (existing)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                trace_id        VARCHAR(64) NOT NULL UNIQUE,
                question        TEXT NOT NULL,
                cypher          TEXT NOT NULL,
                raw_result      JSONB NOT NULL,
                summary         TEXT,
                user_id         VARCHAR(64) NOT NULL,
                session_id      VARCHAR(64) NOT NULL,
                execution_time_ms INT NOT NULL,
                row_count       INT NOT NULL,
                error_message   TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_trace_id ON audit_logs(trace_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_logs(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_session_id ON audit_logs(session_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at DESC)")

        # chat_sessions table (new)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id      VARCHAR(64) PRIMARY KEY,
                user_id         VARCHAR(64) NOT NULL,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                message_count   INT NOT NULL DEFAULT 0,
                last_trace_id   VARCHAR(64)
            )
        """)

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_session_user_id ON chat_sessions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_session_created_at ON chat_sessions(created_at DESC)")

        # chat_messages table (new)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id      VARCHAR(64) NOT NULL REFERENCES chat_sessions(session_id),
                role            VARCHAR(16) NOT NULL,  -- 'user' or 'assistant'
                content         TEXT NOT NULL,
                message_type    VARCHAR(32) NOT NULL,  -- 'text', 'query_result', 'error'
                metadata        JSONB,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON chat_messages(session_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON chat_messages(created_at)")

    logger.info("postgres_schema_initialized")
```

- [ ] **Step 3: Run existing tests**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/ -v -k "not e2e" --tb=short 2>&1 | tail -30`
Expected: PASS (existing tests still work)

- [ ] **Step 4: Commit**

```bash
git add src/honeybadge/db/postgres.py
git commit -m "fix(postgres): add chat_sessions and chat_messages tables"
```

---

## Task 6: Integrate MatrixClient and SchemaCache into app.py Lifespan

**Files:**
- Modify: `src/honeybadge/server/app.py:27-82`

- [ ] **Step 1: Write integration in lifespan**

In the `lifespan()` function of `create_app()`, after existing service init, add:

```python
# After validator init, add Matrix client + schema cache
from honeybadge.gateway import MatrixClient, SchemaCache, RoomManager

schema_cache = SchemaCache()
room_manager = RoomManager()

# Create Matrix client with callbacks
async def on_matrix_result(msg):
    # Route result to the appropriate WebSocket via session_id
    session_id = room_manager.get_session_id_by_trace(msg.trace_id)
    if session_id:
        # Dispatch to WebSocket handler — stored in app.state.active_ws_sessions
        ws = app.state.active_ws_sessions.get(session_id)
        if ws:
            from honeybadge.protocols.messages import ResponseMessage, ResponsePayload, serialize_message
            response = ResponseMessage(
                payload=ResponsePayload(
                    summary=msg.summary,
                    raw_data=msg.data.get("rows", []) if msg.data else [],
                    columns=msg.data.get("columns", []) if msg.data else [],
                    cypher="",
                    trace_id=msg.trace_id,
                    execution_time_ms=0,
                    row_count=0,
                ),
            )
            await ws.send_json(serialize_message(response))

async def on_matrix_error(msg):
    session_id = room_manager.get_session_id_by_trace(msg.trace_id)
    if session_id:
        ws = app.state.active_ws_sessions.get(session_id)
        if ws:
            from honeybadge.protocols.messages import ErrorMessage, ErrorPayload, ErrorCode, serialize_message
            error = ErrorMessage(
                payload=ErrorPayload(
                    code=ErrorCode.EXECUTION_ERROR,
                    message=msg.error_message,
                    trace_id=msg.trace_id,
                ),
            )
            await ws.send_json(serialize_message(error))

matrix_client = MatrixClient(
    homeserver_url=config.matrix_homeserver_url,
    user_id=config.matrix_user_id,
    password=config.matrix_user_password,
    room_manager=room_manager,
    on_result=on_matrix_result,
    on_error=on_matrix_error,
)

app.state.matrix_client = matrix_client
app.state.schema_cache = schema_cache
app.state.room_manager = room_manager
app.state.active_ws_sessions = {}  # session_id → WebSocket

# Bootstrap schema from Worker via Matrix
await matrix_client.connect()
await matrix_client.bootstrap_schema(schema_cache)

# Note: L1-L3 validation happens in Worker, not in gateway.
# schema_cache is available in app.state for any module that needs it.

logger.info("gateway_ready", schema_tags=len(schema_cache.get_tags()), schema_edges=len(schema_cache.get_edges()))
```

Also update the shutdown section:
```python
if hasattr(app.state, "matrix_client") and app.state.matrix_client:
    await app.state.matrix_client.disconnect()
```

- [ ] **Step 2: Update startup error handling**

In the `except` block of lifespan, add:
```python
for attr in ("nebula", "pg", "redis", "llm", "orchestrator", "validator", "matrix_client", "schema_cache", "room_manager"):
```

- [ ] **Step 3: Run tests**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_server_config.py tests/test_schema_cache.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/honeybadge/server/app.py
git commit -m "feat(app): integrate MatrixClient and SchemaCache into lifespan"
```

---

## Task 7: Refactor WebSocket Handler — Matrix Gateway Mode

**Files:**
- Modify: `src/honeybadge/server/websocket.py:31-148`

- [ ] **Step 1: Write the refactored `_handle_query`**

Replace the entire `_handle_query` function with:

```python
async def _handle_query(websocket: WebSocket, data: dict, user_payload: dict) -> None:
    question = data.get("payload", {}).get("question", "")
    session_id = data.get("payload", {}).get("session_id", "")

    if not question:
        await _send_error(websocket, ErrorCode.VALIDATION_FAILED, "Empty question")
        return

    matrix_client = websocket.app.state.matrix_client
    schema_cache = websocket.app.state.schema_cache
    room_manager = websocket.app.state.room_manager

    if matrix_client is None:
        await _send_error(websocket, ErrorCode.SERVICE_UNAVAILABLE, "Matrix client not initialized")
        return

    # Register WebSocket session for response routing
    websocket.app.state.active_ws_sessions[session_id] = websocket
    room_manager.register_trace("", session_id)  # temporary mapping until trace_id assigned

    trace_id = generate_trace_id()
    user_context = {
        "user_id": user_payload["sub"],
        "username": user_payload.get("username"),
        "org_ids": [user_payload.get("org_id")] if user_payload.get("org_id") else [],
        "data_scope": "ALL",
    }

    # ---- Gateway-Layer Input Filtering (Lightweight) ----
    # Full L1-L3 validation happens in Worker after nGQL generation.
    # Gateway only does basic safety checks on the raw question.

    # Check: empty question
    if not question.strip():
        await _send_error(websocket, ErrorCode.VALIDATION_FAILED, "Empty question", trace_id)
        return

    # Check: write operations attempted at gateway level
    write_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"]
    question_upper = question.upper()
    for kw in write_keywords:
        if kw in question_upper:
            await _send_error(websocket, ErrorCode.PERMISSION_DENIED, f"Write operations not allowed: {kw}", trace_id)
            return

    # Register session with room_manager
    room_id = room_manager.get_room_id(session_id)
    if room_id:
        room_manager.register_trace(trace_id, session_id)

    # Forward to Matrix → Manager → Worker (L1-L3 validation happens in Worker)
    await matrix_client.send_query(
        question=question,
        trace_id=trace_id,
        user_id=user_payload["sub"],
        org_id=user_payload.get("org_id", ""),
        roles=user_payload.get("roles", []),
        session_id=session_id,
    )

    # Send progress: query forwarded to Manager
    progress_msg = ProgressMessage(
        payload=ProgressPayload(step="Query forwarded to Manager", step_number=1, total_steps=3, detail=f"trace_id={trace_id}"),
        trace_id=trace_id,
    )
    await websocket.send_json(serialize_message(progress_msg))

    # Note: Actual response comes back via Matrix event → on_matrix_result callback
    # which dispatches to the WebSocket registered in active_ws_sessions

    # Save user message to PostgreSQL (optimistic)
    pg = websocket.app.state.pg
    if pg and hasattr(pg, '_pool') and pg._pool:
        try:
            async with pg._pool.acquire() as conn:
                # Ensure session exists
                await conn.execute(
                    """INSERT INTO chat_sessions (session_id, user_id, message_count, last_trace_id) VALUES ($1, $2, 1, $3) ON CONFLICT (session_id) DO UPDATE SET message_count = chat_sessions.message_count + 1, updated_at = NOW(), last_trace_id = $3""",
                    session_id, user_payload["sub"], trace_id,
                )
                await conn.execute(
                    """INSERT INTO chat_messages (session_id, role, content, message_type, metadata) VALUES ($1, 'user', $2, 'text', NULL)""",
                    session_id, question,
                )
        except Exception as e:
            logger.error("save_user_message_failed", error=str(e))
```

Also add import at top:
```python
from honeybadge.core.trace import generate_trace_id
```

Also add a new import for ProgressMessage in the existing imports section.

- [ ] **Step 2: Run tests**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_server_websocket.py -v`
Expected: PASS (existing tests should still pass with mock app.state)

- [ ] **Step 3: Commit**

```bash
git add src/honeybadge/server/websocket.py
git commit -m "feat(websocket): refactor to Matrix gateway mode - L1-L3 validation then forward to Matrix"
```

---

## Task 8: Verify SchemaCache and MatrixClient Unit Tests

**Files:**
- Run: `tests/test_schema_cache.py`, `tests/test_room_manager.py`, `tests/test_matrix_client.py`

- [ ] **Step 1: Run all gateway module tests**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/test_schema_cache.py tests/test_room_manager.py tests/test_matrix_client.py -v`
Expected: ALL PASS

- [ ] **Step 2: Commit**

```bash
git add tests/
git commit -m "test(gateway): add tests for SchemaCache, RoomManager, MatrixClient"
```

---

## Task 9: End-to-End Verification

**Files:**
- No new files

- [ ] **Step 1: Run full test suite**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python scripts/pytest.exe tests/ -v --tb=short 2>&1 | tail -40`
Expected: ALL PASS (137+ tests)

- [ ] **Step 2: Check imports work**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python -c "from honeybadge.gateway import MatrixClient, SchemaCache, RoomManager; print('imports OK')"`
Expected: imports OK

- [ ] **Step 3: Check app creates without crashing (import check)**

Run: `cd "D:/dev/HoneyBadge/.worktrees/phase1-implementation" && python -c "from honeybadge.server.app import create_app; print('app factory OK')"`
Expected: app factory OK

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: full test suite pass after Matrix gateway refactor"
```

---

## Self-Review Checklist

- [ ] Spec coverage: All sections in design spec have corresponding tasks?
  - Matrix Gateway (Task 3 MatrixClient, 4 RoomManager, 6 app.py, 7 websocket) ✅
  - Schema Cache bootstrap (Task 3, 6) ✅
  - PostgreSQL chat tables (Task 5) ✅
  - Lightweight input filtering (Task 7) ✅
  - HiClaw integration points (Task 4, 6) ✅

- [ ] Placeholder scan: No "TBD", "TODO", "implement later" in task steps ✅
- [ ] Type consistency: `SchemaTag`, `SchemaEdge`, `MatrixMessage` used consistently ✅
- [ ] Test coverage: Each new module has tests ✅
- [ ] Task boundaries: Each task is self-contained and can be committed independently ✅

---

## Execution Option

**Plan complete and saved to `docs/superpowers/plans/2026-04-07-matrix-gateway-refactor-plan.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
