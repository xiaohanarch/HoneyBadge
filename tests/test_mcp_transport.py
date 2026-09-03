"""MCP transport consistency tests.

Source-side: all three MCP servers call mcp.run(transport="streamable-http").

Runtime reality (verified 2026-09-01): the installed FastMCP 4.0.0 serves the
classic SSE transport — GET /sse returns 200 and messages POST back to
/messages/?session_id=... — while /mcp returns 404. The worker-side mcporter
configs MUST therefore point at /sse; pointing at /mcp 404s every tool call.
Empirically confirmed by the full chat E2E group (12/12) with /sse configs.
"""

import pathlib

SERVERS = [
    "mcp-servers/honeybadge-nebula-mcp/server.py",
    "mcp-servers/honeybadge-audit-mcp/server.py",
    "mcp-servers/honeybadge-cache-mcp/server.py",
]

MCPORTER_SCRIPT = "deploy/hiclaw/init-workers.sh"


def test_all_servers_use_streamable_http():
    for rel_path in SERVERS:
        content = pathlib.Path(rel_path).read_text(encoding="utf-8")
        assert 'transport="streamable-http"' in content, (
            f"{rel_path} missing transport=\"streamable-http\""
        )


def test_mcporter_init_script_uses_sse_path():
    content = pathlib.Path(MCPORTER_SCRIPT).read_text(encoding="utf-8")
    assert "honeybadge-nebula-mcp:8000/sse" in content
    assert "honeybadge-audit-mcp:8000/sse" in content
    assert "honeybadge-cache-mcp:8000/sse" in content
    assert "honeybadge-nebula-mcp:8000/mcp" not in content
    assert "honeybadge-audit-mcp:8000/mcp" not in content
    assert "honeybadge-cache-mcp:8000/mcp" not in content
