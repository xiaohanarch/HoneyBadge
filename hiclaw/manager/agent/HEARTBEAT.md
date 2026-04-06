# Periodic Health Check

Run these checks on each heartbeat cycle:

1. **Worker Health**: Check if active Workers have responded in the last 2 minutes. If not, mark as unhealthy.
2. **MCP Server Connectivity**: Verify honeybadge-nebula-mcp, honeybadge-audit-mcp, and honeybadge-cache-mcp are reachable via mcporter.
3. **Stale Sessions**: If a Matrix room has had no activity for 30 minutes, archive the session context.
4. **Report**: If any issues found, notify admin via primary channel.
