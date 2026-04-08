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
