"""HoneyBadge MCP Server Launcher.

In production, MCP Servers run as Docker containers registered in Higress.
This entry point is for local development and testing.
"""
import argparse
import sys

from honeybadge.core.constants import VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=f"HoneyBadge v{VERSION}")
    parser.add_argument("--version", action="version", version=f"v{VERSION}")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("nebula-mcp", help="Run NebulaGraph MCP Server")
    subparsers.add_parser("audit-mcp", help="Run Audit MCP Server")
    subparsers.add_parser("cache-mcp", help="Run Cache MCP Server")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "nebula-mcp":
        sys.path.insert(0, "mcp-servers/honeybadge-nebula-mcp")
        from server import mcp
        mcp.run(transport="sse")
    elif args.command == "audit-mcp":
        sys.path.insert(0, "mcp-servers/honeybadge-audit-mcp")
        from server import mcp
        mcp.run(transport="sse")
    elif args.command == "cache-mcp":
        sys.path.insert(0, "mcp-servers/honeybadge-cache-mcp")
        from server import mcp
        mcp.run(transport="sse")


if __name__ == "__main__":
    main()
