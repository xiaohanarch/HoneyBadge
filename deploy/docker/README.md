# HoneyBadge Local Development Infrastructure

## Quick Start

```bash
cd deploy/docker

# Start core services (NebulaGraph, Redis, PostgreSQL, Matrix)
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f nebula-graphd

# Stop services
docker-compose down

# Stop and remove volumes (CLEAN slate)
docker-compose down -v
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| nebula-graphd | 9669 | NebulaGraph Graph Service |
| nebula-metad | 9559 | NebulaGraph Metadata Service |
| nebula-storaged | 9779 | NebulaGraph Storage Service |
| redis | 6379 | Redis for session/cache |
| postgres | 5432 | PostgreSQL for audit log |
| matrix-synapse | 8008 | Matrix homeserver |

## Optional Services

```bash
# With tools (includes nebula-console)
docker-compose --profile tools up -d

# With Milvus (Vector DB for semantic cache)
docker-compose --profile vector up -d
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

# Matrix
MATRIX_HOMESERVER_URL=http://localhost:8008
MATRIX_BOT_TOKEN=

# LLM
LLM_ENDPOINT=http://localhost:8000/v1
LLM_API_KEY=
LLM_MODEL_NAME=glm-4-flash
```

---

## HiClaw v1.1.2 dev topology

The HiClaw stack was split in v1.1.0 from a single all-in-one container into
two services (image tags now at v1.1.2):

| Service | Image | Role |
|---|---|---|
| `hiclaw-embedded` | `hiclaw-embedded:v1.1.2` | Tuwunel (Matrix `:6167`) + MinIO (`:9000/:9001`) + Higress (`:18080`) + Element Web (`:18888`) |
| `hiclaw-manager` | slim `hiclaw-manager:v1.1.2` | OpenClaw agent only. Reads SOUL/AGENTS/skills out of MinIO, talks to Matrix and the AI gateway over the compose network. |

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

### Dev gateway modes (`HICLAW_DEV_GATEWAY`)

The worker → LLM path is controlled by a single env var in `.env`:

| Mode | What happens | When to use |
|---|---|---|
| `nginx-bypass` (default) | A `hiclaw-aigw-bypass` nginx sidecar owns the `aigw-local.hiclaw.io` DNS alias and forwards `/v1/*` to `LLM_UPSTREAM_HOST` with `LLM_API_KEY` injected. Steps 2c/2d (Higress route + consumer) are **skipped**. | WSL2 hosts (Higress binary segfaults under the WSL2 kernel) and any time you want to debug end-to-end without Higress in the way. |
| `higress` | The embedded Higress instance owns the alias. Step 2c creates the LLM route, Step 2d binds the manager consumer. | Linux dev hosts and the k3s/ECS production target. |

Switching modes only requires updating `.env` and recreating the affected
containers:

```bash
# Switch to nginx-bypass (WSL2 friendly)
sed -i 's/^HICLAW_DEV_GATEWAY=.*/HICLAW_DEV_GATEWAY=nginx-bypass/' deploy/docker/.env
docker-compose up -d --force-recreate hiclaw-aigw-bypass hiclaw-manager
docker-compose restart hiclaw-graph-worker hiclaw-analytics-worker
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
- Owns the `aigw-local.hiclaw.io` Docker network alias workers expect.
- Strips the worker-supplied gateway key and injects `LLM_API_KEY`
  (what real Higress does via consumer / credential mapping).
- Forwards `/v1/*` to `https://${LLM_UPSTREAM_HOST}` with SNI, streaming
  buffering disabled, and 600s read/send timeouts.

Anything outside `/v1/*` is rejected with a 404 to match Higress' AI
gateway path policy.
