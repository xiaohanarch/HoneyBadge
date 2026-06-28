"""Typed MCP client — wraps mcporter subprocess for analytics-worker skills."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueryResult:
    """Result of a validate_and_execute MCP call."""
    trace_id: str
    ngql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: int
    success: bool


class MCPClient:
    """Typed wrapper over mcporter subprocess calls."""

    def __init__(self, server: str = "honeybadge-nebula"):
        self._server = server

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool via mcporter and return parsed JSON response."""
        cmd = [
            "mcporter", "call", f"{self._server}.{tool}",
            "--args", json.dumps(args, ensure_ascii=False),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"mcporter {self._server}.{tool} failed: {result.stderr[:200]}"
            )
        return json.loads(result.stdout)

    def generate_query(self, question: str) -> dict[str, Any]:
        """Generate nGQL from a natural language question."""
        return self.call("generate_query", {"question": question})

    def validate_and_execute(
        self, ngql: str, user_id: str | None = None
    ) -> QueryResult:
        """Validate and execute nGQL, returning a typed QueryResult."""
        args: dict[str, Any] = {"ngql": ngql}
        if user_id:
            args["user_context"] = {"user_id": user_id}
        raw = self.call("validate_and_execute", args)
        rows = raw.get("rows", [])
        return QueryResult(
            trace_id=raw.get("trace_id", ""),
            ngql=raw.get("ngql", ngql),
            columns=raw.get("columns", []),
            rows=rows,
            row_count=raw.get("row_count", len(rows)),
            execution_time_ms=raw.get("execution_time_ms", 0),
            success=raw.get("success", True),
        )

    def write_audit_log(self, **kwargs: Any) -> dict[str, Any]:
        """Write an audit log entry via audit-mcp."""
        old_server = self._server
        self._server = "honeybadge-audit"
        try:
            return self.call("write_audit_log", kwargs)
        finally:
            self._server = old_server
