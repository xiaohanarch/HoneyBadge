# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Project HoneyBadge** — Enterprise Knowledge Graph Intelligent Assistant built on ERP systems (Oracle EBS / custom ERP). Enables natural language Q&A over procurement/supply chain data, fraud detection, and three-way matching anomaly detection.

The canonical architecture document is `README.md` (v3.2, written in Chinese). All implementation decisions should align with it.

## Current Status

- **Phase 0 (MVP)**: Complete — single-node Neo4j, OpenClaw agent, cloud LLM API
- **Phase 1 (Active)**: Infrastructure upgrade — NebulaGraph, HiClaw, Higress gateway, observability stack

## Architecture

### Request flow
```
Frontend (Vue 3 + matrix-js-sdk)
  → honeybadge-auth (FastAPI :8091, login + per-user Matrix account provisioning)
  → Tuwunel Matrix homeserver (browser-direct DM to @manager)
  → HiClaw Manager (supervisord container — Tuwunel + MinIO + Higress + Element)
  → Worker pool (graph-worker, analytics-worker)
  → MCP Servers (SSE :8000) → NebulaGraph / PostgreSQL / Redis
honeybadge-server (FastAPI :8090) handles audit REST + sessions only
  (NOT in the chat hot path post-Approach B; see PR #7 in MEMORY.md for context)
```

### Repo layout (where to look)
- `src/honeybadge/` — Python backend package (installed via `pyproject.toml`)
  - `server/` — FastAPI app (`app.py`), audit, sessions, auth (local users in `auth.py`)
  - `auth_service/` — separate FastAPI service that provisions Matrix accounts, handles Google OAuth
  - `llm/` — LLM provider abstraction (`provider.py`) + adapters (claude, minimax)
  - `protocols/` — message schemas + Cypher/nGQL validator (anti-hallucination L1/L2)
  - `ontology/` — domain ontology loader; injects per-domain context into LLM prompts
  - `permission_service/` — permission enforcement (anti-hallucination L3)
  - `core/` — `trace.py`, `exceptions.py`, `constants.py` (shared)
  - `db/`, `etl/`, `gateway/`, `metrics/` — supporting modules
- `mcp-servers/` — three FastMCP SSE servers: `honeybadge-nebula-mcp`, `honeybadge-audit-mcp`, `honeybadge-cache-mcp`. All run on port 8000 inside their containers.
- `frontend/` — Vue 3 + Vite + Element Plus + matrix-js-sdk
- `deploy/docker/` — local dev compose (`docker-compose.yaml`), Nebula schema (`nebula-schema.ngql`, `nebula-edges.ngql`), `init-nebula.sh`, `init-postgres.sql`
- `deploy/hiclaw/` — `Dockerfile.manager`, `Dockerfile.worker`, `init-workers.sh` (bootstraps `openclaw.json + SOUL.md + AGENTS.md` into MinIO — must run after first `docker compose up`)
- `deploy/k8s/` — kustomize manifests for k3s/ECS production deployment
- `prompts/ontology/` — 12 LLM-optimized ontology files routed by `> **Keywords**:` header
- `tests/` — unit tests at top level, `tests/e2e/` for end-to-end (markers in `pytest.ini`)
- `openspec/` — change specifications
- `scripts/ralph/` — Ralph (autonomous loop) artifacts; not part of the runtime

### Anti-Hallucination Framework (5 layers)
1. **L1** Cypher syntax validation (parser-based, reject & regenerate) — `src/honeybadge/protocols/validator.py`
2. **L2** Schema compliance against NebulaGraph schema
3. **L3** Permission injection at Cypher AST level (never string concat) — `permission_service/`
4. **L4** Raw result passthrough — LLM cannot modify data values, only wrap/format
5. **L5** Full-chain audit log (question → Cypher → result → summary) in PostgreSQL via `audit-mcp`

LLM only generates nGQL and formats output; it never directly answers questions. Every query carries a `trace_id`.

### Business domain
ERP-focused. Two main processes plus master data:
- **Procure-to-Pay (PTP)**: PO → Receipt → Invoice → Payment
- **Order-to-Cash (OTC)**: Sales Order → Shipment → Billing → Collection
- Master data: Item master, Supplier master, BOM

## Common Commands

### Python backend
```bash
# Install (editable + dev extras)
pip install -e ".[dev]"

# Lint / type-check
ruff check src tests
mypy src

# Unit tests (pyproject testpaths=tests, runs all tests/*.py)
pytest

# Run a single test file / single test
pytest tests/test_validator.py
pytest tests/test_validator.py::test_specific_case -v

# E2E tests (pytest.ini overrides testpaths to tests/e2e/)
pytest -c pytest.ini                  # all e2e
pytest -c pytest.ini -m auth          # by marker (auth, chat, session, isolation, permission, antihal, mcp, infra, observability)
pytest -c pytest.ini tests/e2e/test_02_chat.py --timeout=180

# Run MCP servers locally
honeybadge nebula-mcp     # or: python -m honeybadge nebula-mcp
honeybadge audit-mcp
honeybadge cache-mcp

# Run API server
honeybadge-server
```

### Frontend
```bash
cd frontend
npm install
npm run dev          # vite dev server :3000
npm run build        # vue-tsc + vite build
npm run type-check   # vue-tsc --noEmit
```

### Local stack (Docker Compose)
```bash
# Full local setup with health checks + worker bootstrap + restart
./scripts/run-e2e-tests.sh --setup-only

# Manual equivalent
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env up -d
bash deploy/docker/init-nebula.sh        # Nebula schema (idempotent; StatementEmpty errors are benign)
bash deploy/hiclaw/init-workers.sh       # MUST run after first compose up — bootstraps worker configs + Manager DM allowlist + LLM route
docker compose -f deploy/docker/docker-compose.yaml restart hiclaw-graph-worker hiclaw-analytics-worker

# Service URLs (local)
# Frontend :3000 | API :8090 | Auth :8091 | Tuwunel :7167 (host, internal 6167)
# Higress GW :18080 | Higress Console :18001 (admin/admin1234) | MinIO Console :19001
# Element Web :18888 | Prometheus :9090 | Grafana :3030
```

### E2E filter shortcuts
```bash
./scripts/run-e2e-tests.sh --filter auth           # one group
./scripts/run-e2e-tests.sh --filter chat           # auth|chat|session|isolation|permission|antihal|mcp|infra|observability
./scripts/run-e2e-tests.sh --teardown-only
./run-e2e-ecs.sh                                   # K8s/ECS variant (port-forward + Traefik)
```

### Default credentials (dev only)
admin/admin123, analyst/analyst123, auditor/auditor123 (defined in `src/honeybadge/server/auth.py`).

## Git Workflow (MANDATORY)

**NEVER push directly to `master` or `main`.** All changes must go through a feature branch + Pull Request, no exceptions — even single-commit fixes, CI tweaks, or "trivial" changes.

1. `git checkout -b ralph/<feature-name>`
2. Commit to the feature branch
3. `git push -u origin ralph/<feature-name>`
4. `gh pr create` targeting `master`

### CRLF pre-commit hook (install once per clone)
```bash
git config core.hooksPath .githooks
# or:
bash deploy/hiclaw/install-git-hooks.sh
```
The hook (`.githooks/pre-commit`) blocks CRLF in `*.sh|bash|ngql|cypher|py|yaml|json|env|conf|cfg|dockerfile`, `Dockerfile`, `Makefile`. CRLF in shell scripts silently breaks HiClaw / ConfigMaps in production.

## nGQL / NebulaGraph notes (v3)
- Comments use `#`, not `--` (SQL syntax fails)
- Edge DDL: `CREATE EDGE IF NOT EXISTS` (not `CREATE EDGE TYPE`)
- After `CREATE INDEX`: `REBUILD TAG INDEX; REBUILD EDGE INDEX;`
- All schema DDL is `IF NOT EXISTS`, so `init-nebula.sh` is safe to re-run

## LLM / Higress Gateway gotchas
- Workers reach the gateway via Docker network alias `aigw-local.hiclaw.io:8080` (NOT `hiclaw-manager:8080`, which Envoy blackholes)
- Worker `openclaw.json` `baseUrl` MUST end in `/v1` (OpenAI SDK appends `/chat/completions` directly)
- Use `HICLAW_LLM_PROVIDER=openai-compat` (idempotent). The built-in `qwen` provider hardcodes `dashscope.aliyuncs.com` and overwrites manual YAML on every restart.
- `HICLAW_AI_GATEWAY_DOMAIN` (v1.1.0+ name; old v1.0.8 name `HICLAW_AI_GATEWAY_SERVER` removed) must be set, or `manager-openclaw.json.tmpl` generates `baseUrl: http://:8080/v1` (empty host). K8s manifests also need `HICLAW_AI_GATEWAY_URL` (full URL incl. scheme+port) for CRD validation.
- HiClaw v1.1.2 disabled `observe-recovery` — container recreation **no longer resets** Manager's DM allowlist to `[@admin]`. `init-workers.sh` still patches it on boot as a safety measure, but it is no longer required after every recreation.

## Language

`README.md` and many design docs are written in Chinese (project serves Chinese enterprise users). Code comments and tech docs may be in either language.
