# Workspace Layout

- Local workspace: ~/
- Shared files: /root/hiclaw-fs/shared/
- Worker files: /root/hiclaw-fs/agents/<worker-name>/

Use `${HICLAW_STORAGE_PREFIX}` for MinIO paths. Use full Matrix IDs like `@graph-worker:matrix-local.hiclaw.io`.

# Available Workers

## graph-worker

**Purpose:** Handle natural language queries over the ERP knowledge graph.
**Skills:** cypher-query
**MCP Servers:** honeybadge-nebula-mcp, honeybadge-audit-mcp, honeybadge-cache-mcp
**When to route:** User asks factual questions about ERP data — supplier lookups, PO queries, invoice status, item information, relationship traversals.

## analytics-worker

**Purpose:** Complex multi-step analysis, anomaly detection, and fraud pattern identification.
**Skills:** multi-step-analysis, anomaly-detection
**MCP Servers:** honeybadge-nebula-mcp, honeybadge-audit-mcp, honeybadge-cache-mcp
**When to route:** User asks for analysis, trend comparison, anomaly detection, three-way matching checks, or statistical summaries.

# State Management

Register every Worker task in `state.json` — no exceptions.
