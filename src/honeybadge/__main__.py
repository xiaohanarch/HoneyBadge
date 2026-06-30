"""HoneyBadge entry point.

Commands:
  nebula-mcp    Run NebulaGraph MCP Server (SSE)
  audit-mcp     Run Audit Log MCP Server (SSE)
  cache-mcp     Run Redis Cache MCP Server (SSE)
"""
import argparse
import asyncio
import json
import sys
from typing import Any

from honeybadge.core.constants import VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=f"HoneyBadge v{VERSION}")
    parser.add_argument("--version", action="version", version=f"v{VERSION}")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("nebula-mcp", help="Run NebulaGraph MCP Server")
    subparsers.add_parser("audit-mcp", help="Run Audit Log MCP Server")
    subparsers.add_parser("cache-mcp", help="Run Redis Cache MCP Server")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "nebula-mcp":
        sys.path.insert(0, "mcp-servers/honeybadge-nebula-mcp")
        from server import mcp  # type: ignore[import-not-found]
        mcp.run(transport="sse", host="0.0.0.0", port=8000)
    elif args.command == "audit-mcp":
        sys.path.insert(0, "mcp-servers/honeybadge-audit-mcp")
        from server import mcp
        mcp.run(transport="sse", host="0.0.0.0", port=8000)
    elif args.command == "cache-mcp":
        sys.path.insert(0, "mcp-servers/honeybadge-cache-mcp")
        from server import mcp
        mcp.run(transport="sse", host="0.0.0.0", port=8000)


# =============================================================================
# MCP helper — used by MCP servers and development tooling
# =============================================================================

async def _call_mcp_tool(
    base_url: str, tool_name: str, arguments: dict[str, Any], timeout: float = 30.0
) -> dict[str, Any]:
    """Call an MCP tool over SSE and return the parsed JSON result."""
    from mcp.client.session import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client(f"{base_url}/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=timeout,
            )
    if result.content and hasattr(result.content[0], "text"):
        try:
            return json.loads(result.content[0].text)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return {"text": result.content[0].text}
    return {}


if __name__ == "__main__":
    main()
