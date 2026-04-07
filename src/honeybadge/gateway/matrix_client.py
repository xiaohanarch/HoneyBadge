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
        """
        if self._client is None:
            logger.warning("matrix_client_mock_mode", note="Cannot send real Matrix message")
            return

        room_id = self.room_manager.get_room_id(session_id)
        if not room_id:
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

    async def _send_and_wait_for_response(self, trace_id: str, timeout: float = 30.0) -> MatrixMessage:
        """
        Wait for a response with the given trace_id.
        Internal helper used by bootstrap_schema.
        """
        future: asyncio.Future[MatrixMessage] = self._pending_responses.get(trace_id)
        if not future:
            raise RuntimeError(f"No pending future for trace_id: {trace_id}")
        return await asyncio.wait_for(future, timeout=timeout)

    async def bootstrap_schema(self, schema_cache: SchemaCache) -> None:
        """
        Request schema from Worker via Matrix at startup.
        """
        if self._client is None:
            logger.warning("matrix_bootstrap_mock_mode")
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
            response = await self._send_and_wait_for_response("__bootstrap__", timeout=30.0)

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
