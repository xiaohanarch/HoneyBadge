# Start All Service — HoneyBadge Phase 1 (Approach B)

## Overview

One-stop guide to bring up the full HoneyBadge Phase 1 stack locally (Approach B: browser speaks Matrix directly, per-user Matrix accounts).

## Quick Reference

| Scenario | Command (run from project root) |
|----------|---------|
| First-time startup | Steps 1-4 below |
| Regular restart | `docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env up -d` |
| Check status | `docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env ps` |
| Check health | `curl -s http://localhost:8090/api/health` |
| Stop all | `docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env down` |
| Wipe data | `docker compose … down -v` then re-run Steps 3-4 |

## First-Time Startup (Steps 1-4)

**Step 1 — Start all containers** (from project root `D:\dev\HoneyBadge`):
```bash
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env up -d
```
Wait ~60s for HiClaw Manager to fully start (supervisord launches Matrix + MinIO + Higress internally).

**Step 2 — Init NebulaGraph schema** (ONE TIME — safe to re-run):
```bash
bash deploy/docker/init-nebula.sh
```
Applies tags + edges. Takes ~30s. `StatementEmpty` errors for comment lines — benign.

**Step 3 — Init HiClaw workers** (ONE TIME — safe to re-run):
```bash
bash deploy/hiclaw/init-workers.sh
```
Uploads Worker configs (SOUL.md, skills) to MinIO. Registers MCP servers in Higress.
Note: per-user Matrix accounts are now provisioned at login time by honeybadge-auth — the gateway account is no longer created here.

**Step 4 — Restart workers** (after Step 3):
```bash
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env restart hiclaw-graph-worker hiclaw-analytics-worker
```

## Health Verification

All key services should show `(healthy)` or `Up`:
```
honeybadge-auth          Up (healthy)   :8091   ← NEW: auth + Matrix provisioning
honeybadge-server        Up (healthy)   :8090   (audit REST API only)
honeybadge-nebula-mcp    Up (healthy)   :8000
honeybadge-hiclaw-manager Up (healthy)  :6167/:18080/:18001/:18888/:19001
nebula-graphd            Up (healthy)   :9669
nebula-metad             Up (healthy)   :9559
nebula-storaged          Up (healthy)   :9779
postgres                 Up (healthy)   :5432
redis                    Up (healthy)   :6379
```

Health checks:
```bash
curl http://localhost:8090/api/health          # server: redis/postgres/nebula
curl http://localhost:8091/health              # auth: {"status":"ok","service":"honeybadge-auth"}
curl http://localhost:6167/_matrix/client/versions  # Tuwunel Matrix server
```
- `llm: degraded` = **normal** (MiniMax doesn't expose `/v1/models`; LLM calls work fine)

## Login Flow (Approach B)

**Frontend** http://localhost:3000 — credentials: admin/admin123 · analyst/analyst123 · auditor/auditor123

Login now calls `honeybadge-auth:8091/login` which:
1. Provisions `@hb-{username}:matrix-local.hiclaw.io` in Tuwunel (or logs in if already exists)
2. Returns `matrix_access_token + roles_jwt` to browser
3. Browser connects to Tuwunel via matrix-js-sdk and DMs `@manager:matrix-local.hiclaw.io`

| UI | URL | Credentials |
|----|-----|-------------|
| Frontend (chat) | http://localhost:3000 | admin/admin123 etc. |
| Element Web (agent monitor) | http://localhost:18888 | any Matrix user |
| MinIO Console | http://localhost:19001 | admin/admin1234 |
| Higress Console | http://localhost:18001 | admin/admin1234 |

## Test Auth Service Manually

```bash
# Should return matrix_access_token + roles_jwt
curl -s -X POST http://localhost:8091/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python -m json.tool
```

## Observability Stack (Optional)

Start the full observability stack with Prometheus + Grafana + Loki + Alertmanager:

```bash
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env \
  --profile observability up -d
```

| Service | URL | Description |
|---------|-----|-------------|
| Prometheus | http://localhost:9090 | Metrics collection & querying |
| Grafana | http://localhost:3030 | admin/admin123 |
| Loki | http://localhost:3100 | Log aggregation (Promtail auto-collects from all honeybadge-* containers) |
| Alertmanager | http://localhost:9093 | Alert routing |

All honeybadge-* services are labeled with `com.honeybadge.service` — Promtail auto-discovers them via Docker socket.

Prometheus scrapes:
- HiClaw Manager (metrics at :8080/metrics)
- HiClaw Workers (graph + analytics)
- NebulaGraph (graphd:19669, storaged:19779)
- Loki, Grafana, Alertmanager themselves

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `honeybadge-auth` not starting | hiclaw-manager not healthy yet | Wait 60s after compose up, then `docker compose restart honeybadge-auth` |
| `honeybadge-server` unhealthy | NebulaGraph wasn't ready at startup | `docker compose restart honeybadge-server` |
| Login fails with 503 | Tuwunel not reachable from auth container | Check `docker logs honeybadge-auth`; verify hiclaw-manager healthy |
| `matrix_access_token` missing | honeybadge-auth returned error | Check `docker logs honeybadge-auth`; re-run `init-workers.sh` |
| Workers not connecting | MinIO config missing | Re-run init-workers.sh → restart workers |
| `honeybadge-nebula-mcp` restarting | Stale image | `docker compose build honeybadge-nebula-mcp && docker compose up -d --force-recreate honeybadge-nebula-mcp` |
| NebulaGraph has only 10 tags | init-nebula.sh not run | Re-run `bash deploy/docker/init-nebula.sh` |
| Browser Matrix DM timeout | Manager SOUL.md not routed to graph-worker | Check `docker logs honeybadge-graph-worker`; restart workers after init |

## Notes

- Milvus (vector DB) is off by default. Start with: `docker compose … --profile vector up -d`
- NebulaGraph console: `docker compose … --profile tools up -d nebula-console`
- Tuwunel (:6167) is now exposed on host — browser matrix-js-sdk connects there directly
- `honeybadge-server` is now audit REST API only — no Matrix, no WebSocket proxy
