# HoneyBadge Local Development Infrastructure

## Quick Start

```bash
# All commands run from the project root. The compose file requires
# deploy/docker/.env — copy it from deploy/docker/.env.example first
# (see "Configuration file" below).
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env up -d

# Check status / view logs
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env ps
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env logs -f nebula-graphd

# Stop services
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env down

# Stop and remove volumes (CLEAN slate)
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env down -v

# First-time only (idempotent): Nebula schema + worker bootstrap
bash deploy/docker/init-nebula.sh
bash deploy/hiclaw/init-workers.sh
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env restart hiclaw-graph-worker hiclaw-analytics-worker
```

## Services

| Service | Port (host) | Description |
|---------|------|-------------|
| nebula-graphd | 9669 | NebulaGraph Graph Service |
| nebula-metad | 9559 | NebulaGraph Metadata Service |
| nebula-storaged | 9779 | NebulaGraph Storage Service |
| redis | 6379 | Redis for session/cache |
| postgres | 5432 | PostgreSQL for audit log |
| frontend | 3000 | Vue 3 chat UI (browser talks to Matrix directly) |
| honeybadge-server | 8090 | FastAPI — audit REST + session API |
| honeybadge-auth | 8091 | FastAPI — login + per-user Matrix account provisioning |
| honeybadge-nebula-mcp | — | NebulaGraph MCP (SSE :8000 internal) |

There is no standalone Matrix service: the Tuwunel homeserver runs inside
the AgentTeams embedded bundle (host port `:7167`) — see the topology
section below.

## Optional Services

```bash
# With tools (includes nebula-console)
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env --profile tools up -d

# With Milvus (Vector DB for semantic cache)
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env --profile vector up -d

# With observability stack (Prometheus/Grafana/Loki/Promtail/Alertmanager)
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env --profile observability up -d
```

## Connecting to Services

### NebulaGraph

```bash
# Using docker exec
docker exec -it honeybadge-nebula-console

# Or connect from host using NebulaGraph Studio (web UI)
# http://localhost:7001
```

### PostgreSQL

```bash
# Host connection
psql -h localhost -p 5432 -U honeybadge -d honeybadge_audit
# Password: honeybadge123
```

### Redis

```bash
# Host connection
redis-cli -h localhost -p 6379 -a redis123
```

## Environment Variables for Application

Copy these to your `.env` file:

```bash
# NebulaGraph
NEBULA_GRAPHD_HOST=localhost
NEBULA_GRAPHD_PORT=9669
NEBULA_USER=root
NEBULA_PASSWORD=nebula
NEBULA_SPACE=honeybadge

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_URL=redis://:redis123@localhost:6379/0

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=honeybadge
POSTGRES_PASSWORD=honeybadge123
POSTGRES_DB=honeybadge_audit

# Matrix — no bot token / homeserver URL anymore (Approach B). honeybadge-auth
# provisions per-user accounts (@hb-<user>) at login and the browser talks to
# Tuwunel directly at http://localhost:7167.

# LLM — configured in deploy/docker/.env, not per-app env vars.
# See deploy/docker/.env.example (LLM_ENDPOINT / LLM_API_KEY /
# MANAGER_LLM_MODEL / LLM_MODEL / MCP_LLM_ENDPOINT).
```

---

## AgentTeams v1.2.2 dev topology

The agent stack was split in v1.1.0 from a single all-in-one container into
two services. At v1.2.2 the images moved to the upstream AgentTeams registry
(compose service names keep the historical `hiclaw-*` prefixes):

| Service | Image | Role |
|---|---|---|
| `hiclaw-embedded` | `agentteams-embedded:v1.2.2` | Tuwunel (Matrix, host `:7167` / internal `:6167`) + MinIO (`:9000`, console `:19001`) + Higress (`:18080`, console `:18001`) + Element Web (`:18888`) |
| `hiclaw-manager` | slim `agentteams-manager:v1.2.2` | OpenClaw agent only. Reads SOUL/AGENTS/skills out of MinIO, talks to Matrix and the AI gateway over the compose network. |

The two worker services (`hiclaw-graph-worker`, `hiclaw-analytics-worker`) are
unchanged — they register themselves through Matrix during `manager-init-internal.sh`
Step 2.

### Configuration file

Local dev configuration lives in **`deploy/docker/.env`** (gitignored). The
tracked template is **`deploy/docker/.env.example`** — copy it once when
setting up a fresh checkout:

```bash
cp deploy/docker/.env.example deploy/docker/.env
# Edit deploy/docker/.env and fill in real LLM key etc.
```

Never commit `deploy/docker/.env`. The repo's pre-commit hook does not block
it (the file was historically tracked), so it's on you to keep secrets out.

### Dev gateway modes (`AGENTTEAMS_DEV_GATEWAY`)

The worker → LLM path is controlled by a single env var in `.env`:

| Mode | What happens | When to use |
|---|---|---|
| `nginx-bypass` (default) | A `hiclaw-aigw-bypass` nginx sidecar owns the `aigw-local.agentteams.io` DNS alias and forwards `/v1/*` to `LLM_UPSTREAM_HOST` with `LLM_API_KEY` injected. Steps 2c/2d (Higress route + consumer) are **skipped**. | WSL2 hosts (Higress binary segfaults under the WSL2 kernel) and any time you want to debug end-to-end without Higress in the way. |
| `higress` | The embedded Higress instance owns the alias. Step 2c creates the LLM route, Step 2d binds the manager consumer. | Linux dev hosts and the k3s/ECS production target. |

Switching modes only requires updating `.env` and recreating the affected
containers:

```bash
# Switch to nginx-bypass (WSL2 friendly)
sed -i 's/^AGENTTEAMS_DEV_GATEWAY=.*/AGENTTEAMS_DEV_GATEWAY=nginx-bypass/' deploy/docker/.env
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env up -d --force-recreate hiclaw-aigw-bypass hiclaw-manager
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env restart hiclaw-graph-worker hiclaw-analytics-worker
```

### Why the bypass exists

WSL2 kernel 6.6.x crashes the bundled `higress` + `pilot-discovery` Go
binaries on startup (segfault inside `runtime.morestack_noctxt`), regardless
of `seccomp`, `privileged`, or `cap_add` settings. Production k3s on
Linux 5.x+ is unaffected. The bypass is **only** a dev-loop workaround —
production paths always use real Higress, and the k3s gate
(`run-e2e-ecs.sh`) validates that path before any release.

The bypass mirrors the slice of Higress contract that workers actually
exercise:

- Listens on `:8080` inside the compose network.
- Owns the `aigw-local.agentteams.io` Docker network alias workers expect.
- Strips the worker-supplied gateway key and injects `LLM_API_KEY`
  (what real Higress does via consumer / credential mapping).
- Forwards `/v1/*` to `https://${LLM_UPSTREAM_HOST}` with SNI, streaming
  buffering disabled, and 600s read/send timeouts.

Anything outside `/v1/*` is rejected with a 404 to match Higress' AI
gateway path policy.
