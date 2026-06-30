"""NebulaGraph database client for HoneyBadge."""

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import structlog
from nebula3.Config import Config as NebulaConfig
from nebula3.gclient.net import ConnectionPool

from honeybadge.core.exceptions import NebulaGraphError

logger = structlog.get_logger()


@dataclass
class NebulaQueryResult:
    """Result of a NebulaGraph query."""

    columns: list[str]
    rows: list[dict[str, Any]]
    execution_time_ms: int
    success: bool
    error_message: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)


class NebulaGraphClient:
    """
    Async-compatible client for NebulaGraph operations.

    Wraps nebula3-python (sync) with async wrappers using run_in_executor.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9669,
        user: str = "root",
        password: str = "nebula",
        max_pool_size: int = 10,
        timeout: int = 30000,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.max_pool_size = max_pool_size
        self.timeout = timeout
        self._pool: ConnectionPool | None = None

    async def connect(self) -> None:
        """Establish connection pool to NebulaGraph with retry logic."""
        import asyncio

        loop = asyncio.get_running_loop()
        max_retries = 5
        base_delay = 2  # seconds

        def _connect():
            config = NebulaConfig()
            config.max_connection_pool_size = self.max_pool_size
            config.timeout = self.timeout
            pool = ConnectionPool()
            ok = pool.init([(self.host, self.port)], config)
            if not ok:
                raise NebulaGraphError(
                    f"Failed to init connection pool to {self.host}:{self.port}"
                )
            return pool

        last_error = None
        for attempt in range(max_retries):
            try:
                self._pool = await loop.run_in_executor(None, _connect)
                logger.info(
                    "nebula_connected",
                    host=self.host,
                    port=self.port,
                    attempt=attempt + 1,
                )
                return
            except NebulaGraphError:
                raise
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "nebula_connect_retry",
                        host=self.host,
                        port=self.port,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(e),
                    )
                    time.sleep(delay)
                else:
                    raise NebulaGraphError(
                        f"Failed to connect to NebulaGraph after {max_retries} attempts: {e}"
                    )

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            self._pool.close()
            self._pool = None
            logger.info("nebula_disconnected")

    @asynccontextmanager
    async def session(self, space: str) -> AsyncGenerator["NebulaSession", None]:
        """Create a session context for the given space."""
        sess = NebulaSession(self, space)
        try:
            await sess.open()
            yield sess
        finally:
            await sess.close()

    async def execute(
        self,
        ngql: str,
        space: str | None = None,
    ) -> NebulaQueryResult:
        """Execute nGQL statement."""
        import asyncio

        if not self._pool:
            await self.connect()

        loop = asyncio.get_running_loop()
        start_time = time.time()

        def _exec():
            session = self._pool.get_session(self.user, self.password)
            try:
                if space:
                    r = session.execute(f"USE {space}")
                    if not r.is_succeeded():
                        return NebulaQueryResult(
                            columns=[],
                            rows=[],
                            execution_time_ms=0,
                            success=False,
                            error_message=f"USE {space} failed: {r.error_msg()}",
                        )

                result = session.execute(ngql)
                execution_time_ms = int((time.time() - start_time) * 1000)

                if not result.is_succeeded():
                    return NebulaQueryResult(
                        columns=[],
                        rows=[],
                        execution_time_ms=execution_time_ms,
                        success=False,
                        error_message=result.error_msg(),
                    )

                columns = result.keys() if result.keys() else []
                rows = []

                if result.row_size() > 0:
                    for i in range(result.row_size()):
                        row = result.row_values(i)
                        row_dict = {}
                        for j, col in enumerate(columns):
                            row_dict[col] = _convert_value(row[j])
                        rows.append(row_dict)

                return NebulaQueryResult(
                    columns=columns,
                    rows=rows,
                    execution_time_ms=execution_time_ms,
                    success=True,
                )
            finally:
                session.release()

        try:
            return await loop.run_in_executor(None, _exec)
        except NebulaGraphError:
            raise
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            raise NebulaGraphError(f"Query execution failed: {e}", query=ngql)

    async def execute_file(
        self, filepath: str, space: str | None = None
    ) -> list[NebulaQueryResult]:
        """Execute nGQL statements from a file."""
        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        statements = [
            s.strip()
            for s in content.split(";")
            if s.strip() and not s.strip().startswith("--")
        ]

        results = []
        for stmt in statements:
            result = await self.execute(stmt, space)
            results.append(result)

        return results


class NebulaSession:
    """Session context for NebulaGraph operations."""

    def __init__(self, client: NebulaGraphClient, space: str):
        self._client = client
        self._space = space
        self._session = None

    async def open(self) -> None:
        """Open session."""
        import asyncio

        if not self._client._pool:
            raise NebulaGraphError("Client not connected")

        loop = asyncio.get_running_loop()

        def _open():
            session = self._client._pool.get_session(
                self._client.user, self._client.password
            )
            result = session.execute(f"USE {self._space}")
            if not result.is_succeeded():
                session.release()
                raise NebulaGraphError(
                    f"Failed to USE space {self._space}: {result.error_msg()}"
                )
            return session

        self._session = await loop.run_in_executor(None, _open)

    async def close(self) -> None:
        """Close session."""
        if self._session:
            self._session.release()
            self._session = None

    async def execute(self, ngql: str) -> NebulaQueryResult:
        """Execute nGQL in this session."""
        import asyncio

        if not self._session:
            raise NebulaGraphError("Session not open")

        loop = asyncio.get_running_loop()
        start_time = time.time()

        def _exec():
            result = self._session.execute(ngql)
            execution_time_ms = int((time.time() - start_time) * 1000)

            if not result.is_succeeded():
                return NebulaQueryResult(
                    columns=[],
                    rows=[],
                    execution_time_ms=execution_time_ms,
                    success=False,
                    error_message=result.error_msg(),
                )

            columns = result.keys() if result.keys() else []
            rows = []
            if result.row_size() > 0:
                for i in range(result.row_size()):
                    row = result.row_values(i)
                    row_dict = {}
                    for j, col in enumerate(columns):
                        row_dict[col] = _convert_value(row[j])
                    rows.append(row_dict)

            return NebulaQueryResult(
                columns=columns,
                rows=rows,
                execution_time_ms=execution_time_ms,
                success=True,
            )

        return await loop.run_in_executor(None, _exec)


def _convert_value(value: Any) -> Any:
    """Convert NebulaGraph value to Python type."""
    if value.is_empty():
        return None
    if value.is_null():
        return None
    if value.is_bool():
        return value.as_bool()
    if value.is_int():
        return value.as_int()
    if value.is_double():
        return value.as_double()
    if value.is_string():
        return value.as_string()
    if value.is_date():
        return str(value.as_date())
    if value.is_time():
        return str(value.as_time())
    if value.is_datetime():
        return str(value.as_datetime())
    if value.is_list():
        return [_convert_value(v) for v in value.as_list()]
    if value.is_set():
        return [_convert_value(v) for v in value.as_set()]
    if value.is_map():
        return {k: _convert_value(v) for k, v in value.as_map().items()}
    if value.is_vertex():
        vertex = value.as_node()
        return {
            "vid": vertex.get_id().as_string()
            if vertex.get_id().is_string()
            else str(vertex.get_id()),
            "tags": vertex.tags(),
        }
    if value.is_edge():
        edge = value.as_relationship()
        return {
            "src": str(edge.start_vertex_id()),
            "dst": str(edge.end_vertex_id()),
            "type": edge.edge_name(),
            "ranking": edge.ranking(),
        }
    if value.is_path():
        return str(value.as_path())
    # Fallback
    return str(value)
