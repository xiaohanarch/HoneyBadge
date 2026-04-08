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
    import sys
    from honeybadge.gateway.schema_cache import SchemaCache
    from honeybadge.protocols.validator import SchemaTag, SchemaEdge

    # bootstrap_schema does `from nio import RoomCreateResponse` at runtime,
    # so we inject a minimal mock for nio that includes RoomCreateResponse.
    class MockRoomCreateResponse:
        def __init__(self, room_id: str):
            self.room_id = room_id

    mock_nio = MagicMock()
    mock_nio.RoomCreateResponse = MockRoomCreateResponse
    sys.modules["nio"] = mock_nio

    try:
        client = MatrixClient(
            homeserver_url="http://localhost:8008",
            user_id="@honeybadge-gateway:matrix.local",
            password="secret",
            room_manager=MagicMock(),
        )

        # Directly set _client to a mock to bypass actual connection
        mock_client = MagicMock()
        client._client = mock_client
        mock_client.room_create = AsyncMock(
            return_value=MockRoomCreateResponse("!test-room:matrix.local")
        )
        mock_client.room_send = AsyncMock(return_value=None)

        # Mock the schema response from Worker
        async def mock_send_and_wait_for_response(trace_id: str, timeout: float = 30.0):
            return MatrixMessage(
                msgtype="schema_response",
                trace_id="__bootstrap__",
                tags=[SchemaTag(name="Supplier", properties=[])],
                edges=[SchemaEdge(name="PLACED_WITH", properties=[])],
            )

        client._send_and_wait_for_response = mock_send_and_wait_for_response
        schema_cache = SchemaCache()
        await client.bootstrap_schema(schema_cache)

        assert schema_cache.is_ready()
        assert "SUPPLIER" in schema_cache.get_tags()
    finally:
        sys.modules.pop("nio", None)


@pytest.mark.asyncio
async def test_matrix_client_auto_registers_when_user_not_exists():
    """When login returns RegisterResponse (not LoginResponse), matrix-nio auto-registers the user.

    Tuwunel (HiClaw Matrix) has allow_registration=true by default.
    """
    import sys
    from unittest.mock import MagicMock, AsyncMock

    # Create mock nio module
    mock_nio = MagicMock()

    # MockLoginResponse is the base class; MockRegisterResponse is a subclass
    # so isinstance check for LoginResponse returns False for RegisterResponse
    class MockLoginResponse:
        pass

    class MockRegisterResponse(MockLoginResponse):
        def __init__(self):
            self.user_id = "@honeybadge-gateway:matrix-local.hiclaw.io"
            self.access_token = "auto-registered-token"
            self.device_id = "auto-device"

    # Create a mock AsyncClient class that returns a mock instance with login configured
    class MockAsyncClient:
        def __init__(self, homeserver_url, user_id=None):
            self.homeserver_url = homeserver_url
            self.user_id = user_id
            self.login = AsyncMock(return_value=MockRegisterResponse())

    mock_nio.RegisterResponse = MockRegisterResponse
    mock_nio.LoginResponse = MockLoginResponse
    mock_nio.AsyncClient = MockAsyncClient
    mock_nio.RoomMessage = MagicMock

    # Install mock nio module
    sys.modules['nio'] = mock_nio

    try:
        client = MatrixClient(
            homeserver_url="http://localhost:6167",
            user_id="@honeybadge-gateway:matrix-local.hiclaw.io",
            password="",
            room_manager=MagicMock(),
        )

        await client.connect()

        # Should have called login (and nio auto-registers with empty password)
        client._client.login.assert_called_once_with("")
    finally:
        # Clean up - remove mock nio module
        if 'nio' in sys.modules:
            del sys.modules['nio']
