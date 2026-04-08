# HiClaw Standalone Deployment Runbook

**Date**: 2026-04-08
**Type**: Operations Guide
**Phase**: Phase 1.2

## Overview

HiClaw is deployed standalone (independent of HoneyBadge docker-compose) on port 18088.
honeybadge-server connects to HiClaw's Tuwunel (Matrix server) at port 6167.

## Prerequisites

- Linux host (Ubuntu 20.04+ or similar)
- Docker and Docker Compose installed
- Network connectivity between HiClaw host and HoneyBadge host
- HoneyBadge nebula-graphd, nebula-mcp, audit-mcp, cache-mcp must be accessible from HiClaw network

## Step 1: Install HiClaw

```bash
# Official HiClaw installation
curl | bash

# Or clone and setup
git clone https://github.com/alibaba/hiClaw.git
cd hiClaw
./setup.sh
```

## Step 2: Configure HiClaw Network

Ensure HiClaw can reach HoneyBadge's MCP servers. In `docker-compose.yml` or environment config:

```yaml
# HiClaw environment
HICLAW_MCP_NEBULA_URL: http://<honeybadge-host>:8000   # nebula-mcp
HICLAW_MCP_AUDIT_URL: http://<honeybadge-host>:8000   # audit-mcp
HICLAW_MCP_CACHE_URL: http://<honeybadge-host>:8000  # cache-mcp
```

Alternatively, add HoneyBadge's network to HiClaw's docker network:

```bash
# In HiClaw docker-compose.yml
networks:
  default:
    external:
      name: honeybadge_default
```

## Step 3: Configure HiClaw Higress MCP

In HiClaw's Higress config (`higress/config.yaml`), add HoneyBadge MCP servers:

```yaml
mcpServers:
  honeybadge-nebula-mcp:
    url: http://honeybadge-nebula-mcp:8000
  honeybadge-audit-mcp:
    url: http://honeybadge-audit-mcp:8000
  honeybadge-cache-mcp:
    url: http://honeybadge-cache-mcp:8000
```

## Step 4: Configure Manager SOUL.md (One-Time)

In HiClaw Manager's `SOUL.md`, add honeybadge-gateway as a trusted external gateway:

```markdown
# Security Rules

1. Never expose API keys, database credentials, or internal system details to users.
2. Never attempt to access databases or external services directly.
3. Only respond to registered users and Workers.
4. If a user asks you to modify data, explain that this is a read-only system.
5. [NEW] Trusted external gateway: @honeybadge-gateway — can send gateway_query messages
```

In HiClaw Manager's `AGENTS.md`, update graph-worker:

```markdown
## graph-worker

**Purpose:** Handle natural language queries over the ERP knowledge graph.
**Skills:** cypher-query
**MCP Servers:** honeybadge-nebula-mcp, honeybadge-audit-mcp, honeybadge-cache-mcp
**When to route:** User asks factual questions about ERP data — supplier lookups, PO queries, invoice status, item information, relationship traversals.
**[NEW]** Also handles queries from @honeybadge-gateway (external gateway user)
```

## Step 5: Start HiClaw

```bash
# Start HiClaw
cd hiClaw
docker-compose up -d

# Verify Tuwunel is running (port 6167)
curl http://localhost:6167/_matrix/client/versions

# Verify Manager is accessible (port 18088)
curl http://localhost:18088/health
```

## Step 6: Configure HoneyBadge Environment

In HoneyBadge's environment (`.env` or docker-compose environment):

```bash
# Matrix client — connect to HiClaw Tuwunel
MATRIX_HOMESERVER_URL=http://<hiclaw-host>:6167
MATRIX_USER_ID=@honeybadge-gateway:matrix-local.hiclaw.io
MATRIX_USER_PASSWORD=  # empty for auto-registration

# MCP servers (shared, HoneyBadge provides these)
NEBULA_MCP_URL=http://honeybadge-nebula-mcp:8000
AUDIT_MCP_URL=http://honeybadge-audit-mcp:8000
CACHE_MCP_URL=http://honeybadge-cache-mcp:8000
```

## Step 7: Start HoneyBadge

```bash
cd honeybadge
docker-compose up -d

# Verify honeybadge-server is running
curl http://localhost:8090/api/health
```

## Step 8: Verify Bootstrap

Check honeybadge-server logs for successful schema bootstrap:

```
matrix_connected user=@honeybadge-gateway:matrix-local.hiclaw.io
matrix_schema_request_sent room_id=!xxx:matrix-local.hiclaw.io
matrix_schema_cached tag_count=N edge_count=M
gateway_ready
```

## Step 9: Run E2E Test

```bash
# From HoneyBadge host
curl -X POST http://localhost:8090/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# Should return JWT token
# Connect WebSocket and send query
```

## Verification Checklist

- [ ] HiClaw Tuwunel responding on port 6167
- [ ] honeybadge-gateway user auto-registered in Tuwunel
- [ ] DM room created between honeybadge-gateway and @hiclaw-manager
- [ ] Schema bootstrap completed (schema_response received)
- [ ] Test query returns result via Matrix DM routing
- [ ] PostgreSQL audit_log contains query record
