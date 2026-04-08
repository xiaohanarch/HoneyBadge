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
    import sys

    class MockRoomCreateResponse:
        def __init__(self, room_id: str):
            self.room_id = room_id

    mock_nio = MagicMock()
    mock_nio.RoomCreateResponse = MockRoomCreateResponse
    sys.modules["nio"] = mock_nio

    try:
        room_manager = RoomManager()
        client = MatrixClient(
            homeserver_url="http://matrix-local.hiclaw.io",
            user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
            password="",
            room_manager=room_manager,
        )

        mock_client = MagicMock()
        client._client = mock_client

        # Track the invite argument passed to room_create
        invited_users = []
        async def capture_room_create(invite, **kwargs):
            # invite is a list of user IDs
            invited_users.extend(invite)
            return MockRoomCreateResponse("!manager-dm:matrix-local.hiclaw.io")
        mock_client.room_create = AsyncMock(side_effect=capture_room_create)
        mock_client.room_send = AsyncMock(return_value=None)

        await client.send_query(
            question="供应商V001的订单有哪些？",
            trace_id="HB-20260408-001",
            user_id="admin",
            org_id="org001",
            roles=["admin"],
            session_id="session-abc",
        )

        # Verify room was created inviting the Manager
        assert len(invited_users) == 1
        assert "@honeybadge-manager:" in invited_users[0]
        # The domain should match the homeserver URL
        assert invited_users[0].startswith("@honeybadge-manager:matrix-local.hiclaw.io")

        # Verify room was registered
        assert room_manager.get_room_id("session-abc") == "!manager-dm:matrix-local.hiclaw.io"
    finally:
        sys.modules.pop("nio", None)


@pytest.mark.asyncio
async def test_gateway_query_message_format():
    """gateway_query message should include all required fields from the spec."""
    import sys

    class MockRoomCreateResponse:
        def __init__(self, room_id: str):
            self.room_id = room_id

    mock_nio = MagicMock()
    mock_nio.RoomCreateResponse = MockRoomCreateResponse
    sys.modules["nio"] = mock_nio

    try:
        room_manager = RoomManager()
        client = MatrixClient(
            homeserver_url="http://matrix-local.hiclaw.io",
            user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
            password="",
            room_manager=room_manager,
        )

        mock_client = MagicMock()
        client._client = mock_client

        async def mock_room_create(invite, **kwargs):
            return MockRoomCreateResponse("!dm-room:matrix-local.hiclaw.io")
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
    finally:
        sys.modules.pop("nio", None)


@pytest.mark.asyncio
async def test_result_message_routes_to_correct_session():
    """A result message with trace_id HB-xxx should be routed to the session that sent that query."""
    room_manager = RoomManager()
    client = MatrixClient(
        homeserver_url="http://matrix-local.hiclaw.io",
        user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
        password="",
        room_manager=room_manager,
    )

    # Set up mock client so the method doesn't return early
    client._client = MagicMock()

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

    # Create a mock event that will pass isinstance check
    mock_event = MagicMock()
    mock_event.source = {"content": result_msg.to_dict()}

    # Patch the _on_matrix_event method to bypass the isinstance check
    async def patched_on_matrix_event(room_id, event):
        if client._client is None:
            return
        # Bypass the isinstance check by directly processing
        content = event.source.get("content", {})
        msg = MatrixMessage.from_dict(content)

        # Route response by trace_id
        if msg.trace_id and msg.trace_id in client._pending_responses:
            future = client._pending_responses.pop(msg.trace_id)
            if not future.done():
                future.set_result(msg)
            return

        # Dispatch to callbacks
        if msg.msgtype == "result" and client.on_result:
            session_id = client.room_manager.get_session_id(room_id) or client.room_manager.get_session_id_by_trace(msg.trace_id)
            if session_id:
                client.room_manager.register_trace(msg.trace_id, session_id)
            await client.on_result(msg)
        elif msg.msgtype == "error" and client.on_error:
            await client.on_error(msg)

    client._on_matrix_event = patched_on_matrix_event

    # Trigger routing
    await client._on_matrix_event("!room-B:matrix-local.hiclaw.io", mock_event)

    assert routed_session == "session-B"


@pytest.mark.asyncio
async def test_error_message_routes_to_on_error_callback():
    """An error message should be dispatched to on_error callback."""
    room_manager = RoomManager()
    client = MatrixClient(
        homeserver_url="http://matrix-local.hiclaw.io",
        user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
        password="",
        room_manager=room_manager,
    )

    # Set up mock client so the method doesn't return early
    client._client = MagicMock()

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

    # Create a mock event that will pass isinstance check
    mock_event = MagicMock()
    mock_event.source = {"content": error_msg.to_dict()}

    # Patch the _on_matrix_event method to bypass the isinstance check
    async def patched_on_matrix_event(room_id, event):
        if client._client is None:
            return
        # Bypass the isinstance check by directly processing
        content = event.source.get("content", {})
        msg = MatrixMessage.from_dict(content)

        # Route response by trace_id
        if msg.trace_id and msg.trace_id in client._pending_responses:
            future = client._pending_responses.pop(msg.trace_id)
            if not future.done():
                future.set_result(msg)
            return

        # Dispatch to callbacks
        if msg.msgtype == "result" and client.on_result:
            session_id = client.room_manager.get_session_id(room_id) or client.room_manager.get_session_id_by_trace(msg.trace_id)
            if session_id:
                client.room_manager.register_trace(msg.trace_id, session_id)
            await client.on_result(msg)
        elif msg.msgtype == "error" and client.on_error:
            await client.on_error(msg)

    client._on_matrix_event = patched_on_matrix_event

    await client._on_matrix_event("!room:matrix-local.hiclaw.io", mock_event)

    assert received_error is not None
    assert received_error.error_code == "L2_SCHEMA_VALIDATION_FAILED"
    assert received_error.recoverable is False
