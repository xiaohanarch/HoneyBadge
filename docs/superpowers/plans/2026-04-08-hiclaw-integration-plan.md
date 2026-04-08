# HiClaw Integration Implementation Plan (Phase 1.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update HoneyBadge config defaults to connect to HiClaw Tuwunel (localhost:6167), update config tests, and write integration tests for the HiClaw Matrix DM routing.

**Architecture:** honeybadge-server acts as a Matrix client connecting to HiClaw's Tuwunel (port 6167) rather than HoneyBadge's own Conduit (port 8008). Each user session creates a DM room with HiClaw Manager. The Matrix DM carries `gateway_query` messages from honeybadge to Manager, and `result`/`error` messages back.

**Tech Stack:** matrix-nio (Python Matrix SDK), Python asyncio, pytest, HiClaw Tuwunel (Matrix server, port 6167)

---

## File Structure

- **Modify**: `src/honeybadge/server/config.py` — Update `matrix_homeserver_url` and `matrix_user_id` defaults to HiClaw values
- **Modify**: `tests/test_server_config.py` — Update tests for new defaults
- **Create**: `tests/test_matrix_hiclaw_integration.py` — Integration tests for Matrix→HiClaw routing with auto-registration
- **Create**: `docs/superpowers/plans/2026-04-08-hiclaw-deployment-runbook.md` — HiClaw standalone deployment guide

---

## Task 1: Update Matrix Config Defaults for HiClaw Tuwunel

**Files:**
- Modify: `src/honeybadge/server/config.py:84-86`

- [ ] **Step 1: Update the Matrix config field defaults**

Edit `src/honeybadge/server/config.py` lines 84-86:

```python
    # -------------------------------------------------------------------------
    # Matrix client (honeybadge-gateway bot user, connects to HiClaw Tuwunel :6167)
    # -------------------------------------------------------------------------
    matrix_homeserver_url: str = field(default="http://localhost:6167")
    matrix_user_id: str = field(default="@honeybadge-gateway:matrix-local.hiclaw.io")
    matrix_user_password: str = field(default="")
```

- [ ] **Step 2: Run config tests to verify fixture still works**

Run: `pytest tests/test_server_config.py -v`
Expected: PASS (ServerConfig() still works)

- [ ] **Step 3: Commit**

```bash
git add src/honeybadge/server/config.py
git commit -m "feat(config): update Matrix defaults to HiClaw Tuwunel (localhost:6167)"
```

---

## Task 2: Update Config Tests for New HiClaw Defaults

**Files:**
- Modify: `tests/test_server_config.py:79-84`

- [ ] **Step 1: Update test_default_matrix_fields to reflect HiClaw Tuwunel**

Edit `tests/test_server_config.py` lines 79-84:

```python
    def test_default_matrix_fields(self):
        """Should have Matrix client defaults pointing to HiClaw Tuwunel."""
        config = ServerConfig()
        assert config.matrix_homeserver_url == "http://localhost:6167"
        assert config.matrix_user_id == "@honeybadge-gateway:matrix-local.hiclaw.io"
        assert config.matrix_user_password == ""
```

- [ ] **Step 2: Update test_config_from_env to include Matrix env vars**

Edit `tests/test_server_config.py` lines 125-126, adding after the existing env set:

```python
        monkeypatch.setenv("MATRIX_HOMESERVER_URL", "http://hiclaw.example.com:6167")
        monkeypatch.setenv("MATRIX_USER_ID", "@honeybadge-gateway:hiclaw.example.com")
        monkeypatch.setenv("MATRIX_USER_PASSWORD", "secret")
```

And add assertions after line 155:

```python
        assert config.matrix_homeserver_url == "http://hiclaw.example.com:6167"
        assert config.matrix_user_id == "@honeybadge-gateway:hiclaw.example.com"
        assert config.matrix_user_password == "secret"
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/test_server_config.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_server_config.py
git commit -m "test(config): update Matrix defaults to HiClaw Tuwunel in tests"
```

---

## Task 3: Write HiClaw Integration Tests (Matrix DM Routing + Auto-Registration)

**Files:**
- Create: `tests/test_matrix_hiclaw_integration.py`
- Modify: `tests/test_matrix_client.py` (add auto-registration test)

- [ ] **Step 1: Write test for auto-registration flow**

Create `tests/test_matrix_hiclaw_integration.py`:

```python
"""Integration tests for HoneyBadge → HiClaw Matrix DM routing.

These tests verify:
1. MatrixClient auto-registers with HiClaw Tuwunel when user does not exist
2. DM room creation with HiClaw Manager (@hiclaw-manager:*)
3. gateway_query message format sent to Manager
4. Result/error message routing back to correct session via trace_id
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from honeybadge.gateway.matrix_client import MatrixClient, MatrixMessage
from honeybadge.gateway.room_manager import RoomManager
from honeybadge.gateway.schema_cache import SchemaCache


@pytest.mark.asyncio
async def test_matrix_client_creates_dm_with_hiclaw_manager():
    """When send_query is called without an existing room, MatrixClient creates a DM with Manager."""
    room_manager = RoomManager()
    client = MatrixClient(
        homeserver_url="http://localhost:6167",
        user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
        password="",
        room_manager=room_manager,
    )

    mock_client = MagicMock()
    client._client = mock_client
    mock_client.room_create = AsyncMock(return_value="!manager-dm:matrix-local.hiclaw.io")
    mock_client.room_send = AsyncMock(return_value=None)

    # Track the invite argument passed to room_create
    created_room_ids = []
    async def capture_room_create(invite, **kwargs):
        created_room_ids.append(invite)
        return "!manager-dm:matrix-local.hiclaw.io"
    mock_client.room_create = AsyncMock(side_effect=capture_room_create)

    await client.send_query(
        question="供应商V001的订单有哪些？",
        trace_id="HB-20260408-001",
        user_id="admin",
        org_id="org001",
        roles=["admin"],
        session_id="session-abc",
    )

    # Verify room was created inviting the Manager
    assert len(created_room_ids) == 1
    manager_id = created_room_ids[0]
    assert "@hiclaw-manager:" in manager_id
    # The domain should match the homeserver URL split
    assert manager_id.startswith("@hiclaw-manager:matrix-local.hiclaw.io")

    # Verify room was registered
    assert room_manager.get_room_id("session-abc") == "!manager-dm:matrix-local.hiclaw.io"


@pytest.mark.asyncio
async def test_gateway_query_message_format():
    """gateway_query message should include all required fields from the spec."""
    room_manager = RoomManager()
    client = MatrixClient(
        homeserver_url="http://localhost:6167",
        user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
        password="",
        room_manager=room_manager,
    )

    mock_client = MagicMock()
    client._client = mock_client

    async def mock_room_create(invite, **kwargs):
        return "!dm-room:matrix-local.hiclaw.io"
    mock_client.room_create = AsyncMock(side_effect=mock_room_create)

    sent_messages = []
    async def capture_room_send(room_id, event_type, content):
        sent_messages.append(content)
    mock_client.room_send = AsyncMock(side_effect=capture_room_send)

    await client.send_query(
        question="查询供应商列表",
        trace_id="HB-20260408-002",
        user_id="admin",
        org_id="org001",
        roles=["admin", "analyst"],
        session_id="session-xyz",
    )

    assert len(sent_messages) == 1
    msg = sent_messages[0]

    assert msg["type"] == "gateway_query"
    assert msg["trace_id"] == "HB-20260408-002"
    assert msg["question"] == "查询供应商列表"
    assert msg["user_id"] == "admin"
    assert msg["org_id"] == "org001"
    assert msg["roles"] == ["admin", "analyst"]
    assert "data" not in msg  # gateway_query does not include data field


@pytest.mark.asyncio
async def test_result_message_routes_to_correct_session():
    """A result message with trace_id HB-xxx should be routed to the session that sent that query."""
    room_manager = RoomManager()
    client = MatrixClient(
        homeserver_url="http://localhost:6167",
        user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
        password="",
        room_manager=room_manager,
    )

    # Register session → room mapping
    room_manager.register("session-A", "!room-A:matrix-local.hiclaw.io", "HB-A")
    room_manager.register("session-B", "!room-B:matrix-local.hiclaw.io", "HB-B")

    # Simulate result message for session B
    result_msg = MatrixMessage(
        msgtype="result",
        trace_id="HB-B",
        data={"rows": [{"id": "PO001"}], "columns": ["id"]},
        summary="查询到1条",
    )

    routed_session = None
    async def mock_on_result(msg: MatrixMessage):
        nonlocal routed_session
        routed_session = room_manager.get_session_id_by_trace(msg.trace_id)

    client.on_result = mock_on_result

    # Trigger routing
    await client._on_matrix_event("!room-B:matrix-local.hiclaw.io", MagicMock(
        source={"content": result_msg.to_dict()}
    ))

    assert routed_session == "session-B"


@pytest.mark.asyncio
async def test_error_message_routes_to_on_error_callback():
    """An error message should be dispatched to on_error callback."""
    room_manager = RoomManager()
    client = MatrixClient(
        homeserver_url="http://localhost:6167",
        user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
        password="",
        room_manager=room_manager,
    )

    received_error = None
    async def mock_on_error(msg: MatrixMessage):
        nonlocal received_error
        received_error = msg

    client.on_error = mock_on_error

    error_msg = MatrixMessage(
        msgtype="error",
        trace_id="HB-ERR-001",
        error_code="L2_SCHEMA_VALIDATION_FAILED",
        error_message="Tag 'Person' does not exist",
        recoverable=False,
    )

    await client._on_matrix_event("!room:matrix-local.hiclaw.io", MagicMock(
        source={"content": error_msg.to_dict()}
    ))

    assert received_error is not None
    assert received_error.error_code == "L2_SCHEMA_VALIDATION_FAILED"
    assert received_error.recoverable is False
```

- [ ] **Step 2: Run the new integration tests**

Run: `pytest tests/test_matrix_hiclaw_integration.py -v`
Expected: PASS

- [ ] **Step 3: Add auto-registration test to test_matrix_client.py**

Edit `tests/test_matrix_client.py` — add this test at the end:

```python
@pytest.mark.asyncio
async def test_matrix_client_auto_registers_when_user_not_exists():
    """When login returns RegisterResponse (not LoginResponse), matrix-nio auto-registers the user.

    Tuwunel (HiClaw Matrix) has allow_registration=true by default.
    """
    from nio import RegisterResponse

    client = MatrixClient(
        homeserver_url="http://localhost:6167",
        user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
        password="",
        room_manager=MagicMock(),
    )

    mock_client = MagicMock()
    client._client = mock_client

    # Simulate auto-registration: login returns RegisterResponse instead of LoginResponse
    mock_client.login = AsyncMock(return_value=RegisterResponse(
        user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
        access_token="auto-registered-token",
        device_id="auto-device",
    ))

    await client.connect()

    # Should have called login (and nio auto-registers with empty password)
    mock_client.login.assert_called_once_with("")
```

- [ ] **Step 4: Run all matrix tests**

Run: `pytest tests/test_matrix_client.py tests/test_matrix_hiclaw_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_matrix_hiclaw_integration.py tests/test_matrix_client.py
git commit -m "test: add HiClaw integration tests for Matrix DM routing and auto-registration"
```

---

## Task 4: Write HiClaw Standalone Deployment Runbook

**Files:**
- Create: `docs/superpowers/plans/2026-04-08-hiclaw-deployment-runbook.md`

- [ ] **Step 1: Write the HiClaw standalone deployment runbook**

Create `docs/superpowers/plans/2026-04-08-hiclaw-deployment-runbook.md`:

```markdown
# HiClaw Standalone Deployment Runbook

**Date**: 2026-04-08
**Type**: Operations Guide
**Phase**: Phase 1.2

## Overview

HiClaw is deployed standalone (independent of HoneyBadge docker-compose) on port 18088.
honeybadge-server connects to HiClaw's Tuwunel (Matrix server) at port 6167.

## Prerequisites

- Linux host (Ubuntu 20.04+ or similar)
- Docker and Docker Compose installed
- Network connectivity between HiClaw host and HoneyBadge host
- HoneyBadge nebula-graphd, nebula-mcp, audit-mcp, cache-mcp must be accessible from HiClaw network

## Step 1: Install HiClaw

```bash
# Official HiClaw installation
curl | bash

# Or clone and setup
git clone https://github.com/alibaba/hiClaw.git
cd hiClaw
./setup.sh
```

## Step 2: Configure HiClaw Network

Ensure HiClaw can reach HoneyBadge's MCP servers. In `docker-compose.yml` or environment config:

```yaml
# HiClaw environment
HICLAW_MCP_NEBULA_URL: http://<honeybadge-host>:8000   # nebula-mcp
HICLAW_MCP_AUDIT_URL: http://<honeybadge-host>:8000   # audit-mcp
HICLAW_MCP_CACHE_URL: http://<honeybadge-host>:8000  # cache-mcp
```

Alternatively, add HoneyBadge's network to HiClaw's docker network:

```bash
# In HiClaw docker-compose.yml
networks:
  default:
    external:
      name: honeybadge_default
```

## Step 3: Configure HiClaw Higress MCP

In HiClaw's Higress config (`higress/config.yaml`), add HoneyBadge MCP servers:

```yaml
mcpServers:
  honeybadge-nebula-mcp:
    url: http://honeybadge-nebula-mcp:8000
  honeybadge-audit-mcp:
    url: http://honeybadge-audit-mcp:8000
  honeybadge-cache-mcp:
    url: http://honeybadge-cache-mcp:8000
```

## Step 4: Configure Manager SOUL.md (One-Time)

In HiClaw Manager's `SOUL.md`, add honeybadge-gateway as a trusted external gateway:

```markdown
# Security Rules

1. Never expose API keys, database credentials, or internal system details to users.
2. Never attempt to access databases or external services directly.
3. Only respond to registered users and Workers.
4. If a user asks you to modify data, explain that this is a read-only system.
5. [NEW] Trusted external gateway: @honeybadge-gateway — can send gateway_query messages
```

In HiClaw Manager's `AGENTS.md`, update graph-worker:

```markdown
## graph-worker

**Purpose:** Handle natural language queries over the ERP knowledge graph.
**Skills:** cypher-query
**MCP Servers:** honeybadge-nebula-mcp, honeybadge-audit-mcp, honeybadge-cache-mcp
**When to route:** User asks factual questions about ERP data — supplier lookups, PO queries, invoice status, item information, relationship traversals.
**[NEW]** Also handles queries from @honeybadge-gateway (external gateway user)
```

## Step 5: Start HiClaw

```bash
# Start HiClaw
cd hiClaw
docker-compose up -d

# Verify Tuwunel is running (port 6167)
curl http://localhost:6167/_matrix/client/versions

# Verify Manager is accessible (port 18088)
curl http://localhost:18088/health
```

## Step 6: Configure HoneyBadge Environment

In HoneyBadge's environment (`.env` or docker-compose environment):

```bash
# Matrix client — connect to HiClaw Tuwunel
MATRIX_HOMESERVER_URL=http://<hiclaw-host>:6167
MATRIX_USER_ID=@honeybadge-gateway:matrix-local.hiclaw.io
MATRIX_USER_PASSWORD=  # empty for auto-registration

# MCP servers (shared, HoneyBadge provides these)
NEBULA_MCP_URL=http://honeybadge-nebula-mcp:8000
AUDIT_MCP_URL=http://honeybadge-audit-mcp:8000
CACHE_MCP_URL=http://honeybadge-cache-mcp:8000
```

## Step 7: Start HoneyBadge

```bash
cd honeybadge
docker-compose up -d

# Verify honeybadge-server is running
curl http://localhost:8090/api/health
```

## Step 8: Verify Bootstrap

Check honeybadge-server logs for successful schema bootstrap:

```
matrix_connected user=@honeybadge-gateway:matrix-local.hiclaw.io
matrix_schema_request_sent room_id=!xxx:matrix-local.hiclaw.io
matrix_schema_cached tag_count=N edge_count=M
gateway_ready
```

## Step 9: Run E2E Test

```bash
# From HoneyBadge host
curl -X POST http://localhost:8090/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# Should return JWT token
# Connect WebSocket and send query
```

## Verification Checklist

- [ ] HiClaw Tuwunel responding on port 6167
- [ ] honeybadge-gateway user auto-registered in Tuwunel
- [ ] DM room created between honeybadge-gateway and @hiclaw-manager
- [ ] Schema bootstrap completed (schema_response received)
- [ ] Test query returns result via Matrix DM routing
- [ ] PostgreSQL audit_log contains query record
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-08-hiclaw-deployment-runbook.md
git commit -m "docs: add HiClaw standalone deployment runbook"
```

---

## Task 5: Run Full Test Suite and Verify

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 2: Verify no regressions from Phase 1.1**

Run: `pytest tests/test_matrix_client.py tests/test_schema_cache.py tests/test_room_manager.py tests/test_server_config.py tests/test_integration_e2e.py -v`
Expected: ALL PASS

---

## Self-Review Checklist

**1. Spec coverage:** Skim `2026-04-08-hiclaw-integration-design.md`:
- [x] Config update to HiClaw Tuwunel (localhost:6167) — Task 1
- [x] Auto-registration support (empty password) — Task 3
- [x] DM room creation with Manager — Task 3
- [x] gateway_query message format — Task 3
- [x] Result/error routing via trace_id — Task 3
- [x] HiClaw deployment runbook — Task 4
- [x] E2E verification steps — Task 4

**2. Placeholder scan:** No TBD/TODO/placeholder strings in this plan.

**3. Type consistency:**
- `MatrixClient.__init__` signature: `homeserver_url, user_id, password, room_manager, on_result, on_error` — matches all call sites
- `MatrixMessage.to_dict()` / `from_dict()` — used consistently in tests
- `SchemaCache.load_schema()` — takes `list[SchemaTag], list[SchemaEdge]` — matches Phase 1.1
- `RoomManager.register(session_id, room_id, trace_id)` — matches Phase 1.1

**4. Test coverage:**
- `test_default_matrix_fields` — updated to HiClaw values
- `test_config_from_env` — Matrix env vars added
- `test_matrix_client_creates_dm_with_hiclaw_manager` — DM room creation
- `test_gateway_query_message_format` — message format
- `test_result_message_routes_to_correct_session` — trace_id routing
- `test_error_message_routes_to_on_error_callback` — error callback
- `test_matrix_client_auto_registers_when_user_not_exists` — auto-registration
