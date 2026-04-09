"""Tests for MatrixClient.submit_and_wait() and x-honeybadge _on_matrix_event routing."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from honeybadge.gateway.matrix_client import MatrixClient, MatrixMessage
from honeybadge.gateway.room_manager import RoomManager


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_client() -> MatrixClient:
    """Create a MatrixClient with a mock nio client and RoomMessage class pre-attached."""
    client = MatrixClient(
        homeserver_url="http://localhost:8008",
        user_id="@gateway:matrix.local",
        password="secret",
        room_manager=RoomManager(),
    )
    mock_nio = MagicMock()

    class MockRoomCreateResponse:
        def __init__(self, room_id: str):
            self.room_id = room_id

    class MockRoomMessage:
        def __init__(self, sender: str, content: dict):
            self.sender = sender
            self.source = {"content": content}

    mock_nio.RoomCreateResponse = MockRoomCreateResponse
    mock_nio.RoomMessage = MockRoomMessage
    sys.modules["nio"] = mock_nio

    nio_client = MagicMock()
    nio_client.room_create = AsyncMock(
        return_value=MockRoomCreateResponse("!room1:matrix.local")
    )
    nio_client.room_send = AsyncMock()
    client._client = nio_client
    return client


def _make_result_event(trace_id: str, room_id: str = "!room1:matrix.local"):
    """Build a mock Matrix event with a CONTRACT-002 result payload."""
    mock_nio = sys.modules.get("nio", MagicMock())
    MockRoomMessage = mock_nio.RoomMessage

    content = {
        "msgtype": "m.text",
        "body": f"[HoneyBadge] result trace={trace_id}",
        "x-honeybadge": {
            "version": "1",
            "type": "result",
            "trace_id": trace_id,
            "summary": "发现1笔异常交易",
            "ngql": "MATCH (po:PurchaseOrder) RETURN po",
            "rows": [{"po_number": "PO001"}],
            "columns": ["po_number"],
            "row_count": 1,
            "execution_time_ms": 300,
        },
    }
    room = MagicMock()
    room.room_id = room_id
    event = MockRoomMessage("@manager:matrix.local", content)
    return room, event


def _make_error_event(trace_id: str, room_id: str = "!room1:matrix.local"):
    """Build a mock Matrix event with a CONTRACT-003 error payload."""
    mock_nio = sys.modules.get("nio", MagicMock())
    MockRoomMessage = mock_nio.RoomMessage

    content = {
        "msgtype": "m.text",
        "body": f"[HoneyBadge] error trace={trace_id}",
        "x-honeybadge": {
            "version": "1",
            "type": "error",
            "trace_id": trace_id,
            "error_code": "VALIDATION_ERROR",
            "error_message": "L1 语法校验失败",
            "recoverable": False,
        },
    }
    room = MagicMock()
    room.room_id = room_id
    event = MockRoomMessage("@manager:matrix.local", content)
    return room, event


def _make_plain_text_event(
    body: str,
    sender: str = "@manager:matrix.local",
    room_id: str = "!room1:matrix.local",
):
    """Build a mock Matrix event with plain text (CONTRACT-004, no x-honeybadge)."""
    mock_nio = sys.modules.get("nio", MagicMock())
    MockRoomMessage = mock_nio.RoomMessage

    content = {"msgtype": "m.text", "body": body}
    room = MagicMock()
    room.room_id = room_id
    event = MockRoomMessage(sender, content)
    return room, event


@pytest.fixture(autouse=True)
def cleanup_nio():
    yield
    sys.modules.pop("nio", None)


# ---------------------------------------------------------------------------
# submit_and_wait tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_and_wait_returns_result_message():
    """submit_and_wait() returns a MatrixMessage when result arrives."""
    client = _make_client()
    trace_id = "TRC-20260408-120000-test0001"

    async def inject():
        await asyncio.sleep(0.02)
        room, event = _make_result_event(trace_id)
        await client._on_matrix_event(room, event)

    asyncio.create_task(inject())

    msg = await client.submit_and_wait(
        question="查找异常交易",
        trace_id=trace_id,
        user_context={"user_id": "u1", "org_id": "org1", "roles": []},
        session_id="sess-001",
        on_room_text=AsyncMock(),
        timeout=2.0,
    )

    assert msg.msgtype == "result"
    assert msg.trace_id == trace_id
    assert msg.summary == "发现1笔异常交易"
    assert msg.row_count == 1


@pytest.mark.asyncio
async def test_submit_and_wait_returns_error_message():
    """submit_and_wait() returns a MatrixMessage when error arrives."""
    client = _make_client()
    trace_id = "TRC-20260408-120000-test0002"

    async def inject():
        await asyncio.sleep(0.02)
        room, event = _make_error_event(trace_id)
        await client._on_matrix_event(room, event)

    asyncio.create_task(inject())

    msg = await client.submit_and_wait(
        question="查找异常交易",
        trace_id=trace_id,
        user_context={"user_id": "u1", "org_id": "org1", "roles": []},
        session_id="sess-002",
        on_room_text=AsyncMock(),
        timeout=2.0,
    )

    assert msg.msgtype == "error"
    assert msg.error_code == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_submit_and_wait_timeout_raises():
    """submit_and_wait() raises asyncio.TimeoutError when no response arrives."""
    client = _make_client()
    trace_id = "TRC-20260408-120000-test0003"

    with pytest.raises(asyncio.TimeoutError):
        await client.submit_and_wait(
            question="查找异常交易",
            trace_id=trace_id,
            user_context={"user_id": "u1", "org_id": "org1", "roles": []},
            session_id="sess-003",
            on_room_text=AsyncMock(),
            timeout=0.05,
        )


@pytest.mark.asyncio
async def test_submit_and_wait_cleans_up_queue_on_success():
    """_pending_queues is empty after submit_and_wait returns successfully."""
    client = _make_client()
    trace_id = "TRC-20260408-120000-test0004"

    async def inject():
        await asyncio.sleep(0.02)
        room, event = _make_result_event(trace_id)
        await client._on_matrix_event(room, event)

    asyncio.create_task(inject())
    await client.submit_and_wait(
        question="q",
        trace_id=trace_id,
        user_context={"user_id": "u1", "org_id": "o1", "roles": []},
        session_id="sess-004",
        on_room_text=AsyncMock(),
        timeout=2.0,
    )

    assert trace_id not in client._pending_queues


@pytest.mark.asyncio
async def test_submit_and_wait_cleans_up_queue_on_timeout():
    """_pending_queues is empty after timeout."""
    client = _make_client()
    trace_id = "TRC-20260408-120000-test0005"

    with pytest.raises(asyncio.TimeoutError):
        await client.submit_and_wait(
            question="q",
            trace_id=trace_id,
            user_context={"user_id": "u1", "org_id": "o1", "roles": []},
            session_id="sess-005",
            on_room_text=AsyncMock(),
            timeout=0.05,
        )

    assert trace_id not in client._pending_queues


# ---------------------------------------------------------------------------
# _on_matrix_event routing tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_matrix_event_plain_text_calls_room_text_callback():
    """Plain text HiClaw messages (CONTRACT-004) trigger the on_room_text callback."""
    client = _make_client()
    room_id = "!room1:matrix.local"
    on_text = AsyncMock()
    client._room_text_callbacks[room_id] = on_text

    room, event = _make_plain_text_event("正在路由到 graph-worker...", room_id=room_id)
    await client._on_matrix_event(room, event)

    on_text.assert_awaited_once_with("正在路由到 graph-worker...")


@pytest.mark.asyncio
async def test_on_matrix_event_own_plain_text_ignored():
    """Plain text sent by the gateway itself does NOT trigger on_room_text."""
    client = _make_client()
    room_id = "!room1:matrix.local"
    on_text = AsyncMock()
    client._room_text_callbacks[room_id] = on_text

    # sender == client.user_id
    room, event = _make_plain_text_event(
        "my own message",
        sender="@gateway:matrix.local",
        room_id=room_id,
    )
    await client._on_matrix_event(room, event)

    on_text.assert_not_called()
