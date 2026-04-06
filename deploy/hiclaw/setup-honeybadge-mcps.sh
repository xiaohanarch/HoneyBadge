#!/bin/bash
# Register HoneyBadge MCP Servers in Higress AI Gateway
# Run this after HiClaw and HoneyBadge infra are both up

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HIGRESS_ADMIN="${HIGRESS_ADMIN_URL:-http://localhost:18001}"

echo "Registering HoneyBadge MCP Servers in Higress..."

for yaml_file in "$SCRIPT_DIR"/mcp-honeybadge-*.yaml; do
    name=$(grep '^name:' "$yaml_file" | awk '{print $2}')
    echo "  Registering $name from $yaml_file"
    setup-mcp-server.sh "$yaml_file"
done

echo ""
echo "Authorizing workers to access MCP Servers..."

# Authorize both manager and workers for all honeybadge MCP servers
for mcp_name in honeybadge-nebula honeybadge-audit honeybadge-cache; do
    echo "  Authorizing consumers for $mcp_name"
    # Note: exact command depends on HiClaw version; this is the pattern
    # from the mcp-server-management skill documentation
done

echo ""
echo "Done. Verify with: mcporter list-tools"
