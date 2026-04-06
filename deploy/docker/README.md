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
