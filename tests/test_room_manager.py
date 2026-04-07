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


def test_room_manager_get_session_id():
    """Test getting session_id from room_id (reverse lookup)."""
    rm = RoomManager()
    rm.register("session_123", "!abc123:matrix.local")

    assert rm.get_session_id("!abc123:matrix.local") == "session_123"
