"""TDD test: all three MCP servers must use streamable-http transport.

FastMCP >= 2.3.0 required on server side.
mcporter on worker side must point to /mcp (not /sse).
"""
import pathlib


SERVERS = [
    "mcp-servers/honeybadge-nebula-mcp/server.py",
    "mcp-servers/honeybadge-audit-mcp/server.py",
    "mcp-servers/honeybadge-cache-mcp/server.py",
]

MCPORTER_SCRIPT = "deploy/hiclaw/init-workers.sh"


def test_no_server_uses_sse_transport():
    for rel_path in SERVERS:
        content = pathlib.Path(rel_path).read_text(encoding="utf-8")
        assert 'transport="sse"' not in content, (
            f"{rel_path} still has transport=\"sse\" — change to streamable-http"
        )


def test_all_servers_use_streamable_http():
    for rel_path in SERVERS:
        content = pathlib.Path(rel_path).read_text(encoding="utf-8")
        assert 'transport="streamable-http"' in content, (
            f"{rel_path} missing transport=\"streamable-http\""
        )


def test_mcporter_init_script_uses_mcp_path():
    content = pathlib.Path(MCPORTER_SCRIPT).read_text(encoding="utf-8")
    assert "honeybadge-nebula-mcp:8000/mcp" in content
    assert "honeybadge-audit-mcp:8000/mcp" in content
    assert "honeybadge-cache-mcp:8000/mcp" in content
    assert "honeybadge-nebula-mcp:8000/sse" not in content
    assert "honeybadge-audit-mcp:8000/sse" not in content
    assert "honeybadge-cache-mcp:8000/sse" not in content
