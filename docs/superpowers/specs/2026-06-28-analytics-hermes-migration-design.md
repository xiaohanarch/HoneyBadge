# Analytics-Worker Hermes Migration Design

**Date**: 2026-06-28
**Status**: Draft (awaiting review)
**Branch**: `ralph/analytics-hermes-migration`
**Author**: Ralph (via superpowers brainstorming skill)

---

## 1. Context & Critical Findings

### 1.1 What triggered this design

README §12.9 (Worker Runtime Selection) recommended `analytics-worker` as the
pilot component for migrating from OpenClaw to Hermes runtime, based on four
reasons: non-hot-path, self-learning fit, Python same-language, long-task match.
This document specifies *how* to execute that migration.

### 1.2 Findings from container investigation (v1.1.2 image)

| Finding | Impact on design |
|---------|------------------|
| OpenClaw version is `2026.4.14` (date-based), NOT `v1.1.2` | Confirmed; HiClaw v1.1.2 is the distribution, OpenClaw is the runtime |
| Hermes `AGENTS.md` confirms skills use **SKILL.md format** (same as openclaw) | Skills are portable — no rewrite needed |
| **Hermes runtime is NOT installed in the worker image** | Must build a custom image or install at runtime |
| Worker image is Ubuntu 24.04 + Python 3.12.3, **no pip** | Custom Dockerfile needed (can't `pip install` at runtime) |
| `hermes-worker-agent/` in the manager image only contains `AGENTS.md` + `skills/` (templates, not runtime) | Hermes-agent is a separate pip package |
| `worker-entrypoint.sh` is deeply openclaw-specific (openclaw.json, OPENCLAW_*, `exec openclaw gateway run`) | Need a parallel `hermes-worker-entrypoint.sh` |
| Manager-side scripts (route-and-execute.sh, forward-to-user.sh) and MCP/L3 layers are runtime-agnostic | Confirmed: blast radius limited to worker container |

### 1.3 Blast radius (confirmed minimal)

**Unaffected (no changes required):**
- `hiclaw/manager/` — all scripts, SOUL.md, skills
- `mcp-servers/` — all three MCP servers
- `src/honeybadge/permission_service/` — L3 AST injection
- `src/honeybadge/protocols/validator.py` — L1/L2 validation
- `deploy/docker/docker-compose.yaml` — graph-worker service
- Frontend, auth-service, honeybadge-server

**Affected (changes required):**
- `deploy/hiclaw/Dockerfile.hermes-worker` — **new** (extends worker image, installs hermes-agent)
- `deploy/hiclaw/hermes-worker-entrypoint.sh` — **new** (parallel to worker-entrypoint.sh)
- `deploy/hiclaw/hermes-config-bridge.sh` — **new** (openclaw.json → config.yaml + .env)
- `deploy/hiclaw/worker-init-wrapper.sh` — **modified** (detect runtime, branch init logic)
- `deploy/docker/docker-compose.yaml` — **modified** (analytics-worker: image + entrypoint)
- `hiclaw/workers/analytics-worker/agent/SOUL.md` — **minor** (identity wording)
- `hiclaw/workers/analytics-worker/agent/AGENTS.md` — **new** (hermes-specific behavioral rules)

---

## 2. Design Decisions

### 2.1 Custom image vs runtime install

**Decision**: Build a custom Docker image (`Dockerfile.hermes-worker`).

**Rationale**:
- Worker image has no pip — runtime install requires bootstrapping pip first
- Runtime install adds 30-60s startup latency and a network dependency
- Custom image is reproducible, cacheable, and follows the existing `Dockerfile.worker` pattern
- Production k8s deployments already require a baked image (no MinIO config dependency)

**Rejected alternative**: Install pip + hermes-agent in `worker-init-wrapper.sh` at startup.
Slower, fragile (network failures break startup), and violates "build artifacts once" principle.

### 2.2 Parallel entrypoint vs modify existing

**Decision**: Write a separate `hermes-worker-entrypoint.sh`, do NOT modify `worker-entrypoint.sh`.

**Rationale**:
- `worker-entrypoint.sh` is 200+ lines of openclaw-specific logic (OPENCLAW_*, matrix re-login, gateway health)
- Modifying it risks breaking graph-worker (which stays on openclaw)
- A parallel script is cleaner, easier to test, and trivially removable (rollback = delete file + revert compose)

### 2.3 Config bridge: generate vs hand-edit

**Decision**: Write `hermes-config-bridge.sh` that translates `openclaw.json` → `~/.hermes/config.yaml` + `.env`.

**Rationale**:
- Hermes AGENTS.md documents the bridge behavior: openclaw.json is the single source of truth
- Bridge owns: `MATRIX_*`, `OPENAI_*`, `model:`, `matrix:`, `platforms.matrix:` YAML blocks
- Non-bridge-owned keys preserved (additions survive re-runs)
- Bridge must run at startup AND after every config push from coordinator

### 2.4 Skills porting strategy

**Decision**: Copy SKILL.md files as-is, validate behavior, only modify if hermes rejects them.

**Rationale**:
- Hermes AGENTS.md: "Each skill directory contains a `SKILL.md` explaining how to use it" — same format
- Both skills (`anomaly-detection`, `multi-step-analysis`) are pure markdown with mcporter CLI examples
- mcporter is runtime-agnostic (CLI tool installed in both runtimes)
- If validation fails, fallback to adapting phrasing (not full rewrite)

---

## 3. Architecture

### 3.1 Before (current state)

```
docker-compose.yaml
  hiclaw-analytics-worker:
    image: hiclaw-worker:v1.1.2
    entrypoint: worker-init-wrapper.sh
      → exec /opt/hiclaw/scripts/worker-entrypoint.sh
        → exec openclaw gateway run --verbose --force
```

### 3.2 After (target state)

```
docker-compose.yaml
  hiclaw-analytics-worker:
    image: honeybadge/hiclaw-hermes-worker:v1.1.2-1   # custom build
    entrypoint: worker-init-wrapper.sh                  # same wrapper, detects runtime
      → exec /opt/honeybadge/init/hermes-worker-entrypoint.sh
        → hermes-config-bridge.sh (openclaw.json → ~/.hermes/config.yaml + .env)
        → exec hermes-agent --config ~/.hermes/config.yaml
```

### 3.3 Component diagram

```
┌─────────────────────────────────────────────────────────────┐
│ hiclaw-analytics-worker container                            │
│                                                              │
│  worker-init-wrapper.sh (modified)                           │
│    ├─ if HICLAW_WORKER_RUNTIME=hermes:                       │
│    │    copy SOUL.md → ~/.hermes/SOUL.md                     │
│    │    copy skills → ~/.hermes/skills/                      │
│    │    register mcporter servers                            │
│    │    wake Matrix sessions (hermes CLI)                    │
│    │    exec hermes-worker-entrypoint.sh                     │
│    │                                                          │
│    └─ else (default openclaw):                               │
│         [existing logic unchanged]                           │
│         exec worker-entrypoint.sh                            │
│                                                              │
│  hermes-worker-entrypoint.sh (new)                           │
│    ├─ mc alias set hiclaw (MinIO)                            │
│    ├─ mc mirror agents/analytics-worker/ → ~/.hermes/        │
│    ├─ hermes-config-bridge.sh                                │
│    │    openclaw.json → config.yaml + .env                   │
│    ├─ start file sync loop (5min pull, change-triggered push)│
│    └─ exec hermes-agent --config ~/.hermes/config.yaml       │
│                                                              │
│  hermes-config-bridge.sh (new)                               │
│    ├─ read openclaw.json                                     │
│    ├─ generate config.yaml (model, matrix, platforms)        │
│    ├─ generate .env (MATRIX_*, OPENAI_*)                     │
│    └─ preserve non-bridge-owned keys                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. File Specifications

### 4.1 `deploy/hiclaw/Dockerfile.hermes-worker` (new)

```dockerfile
# HoneyBadge Hermes Worker — extends hiclaw-worker v1.1.2 with hermes-agent
FROM higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/hiclaw-worker:v1.1.2

# Bootstrap pip, then install hermes-agent
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip \
    && pip3 install --no-cache-dir --break-system-packages hermes-agent \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy hermes-specific entrypoint and bridge
COPY hermes-worker-entrypoint.sh /opt/honeybadge/init/
COPY hermes-config-bridge.sh     /opt/honeybadge/init/
RUN chmod +x /opt/honeybadge/init/hermes-worker-entrypoint.sh \
             /opt/honeybadge/init/hermes-config-bridge.sh

EXPOSE 8080
```

**Open question**: Is `hermes-agent` published on PyPI? If not, must obtain the
package from HiClaw's distribution or build from source. Needs verification
before implementation. If unavailable, this design is blocked.

### 4.2 `deploy/hiclaw/hermes-worker-entrypoint.sh` (new)

Responsibilities (mirrors `worker-entrypoint.sh` structure, adapted for hermes):

1. **Set timezone** (same as openclaw version)
2. **Configure mc alias** for MinIO (same)
3. **Pull worker config** from MinIO to `~/.hermes/` (path change: `/root/hiclaw-fs/agents/<name>/` → `~/.hermes/`)
4. **Run config bridge**: `hermes-config-bridge.sh` translates `openclaw.json` → `config.yaml` + `.env`
5. **Start file sync loop** (adapted: push `~/.hermes/` changes, pull `shared/` every 5min)
6. **Configure mcporter** (same: register MCP servers)
7. **Matrix re-login** (adapted: update `~/.hermes/.env` with fresh token instead of `openclaw.json`)
8. **Launch hermes-agent**: `exec hermes-agent --config ~/.hermes/config.yaml`

**Key differences from openclaw version**:
- No `OPENCLAW_*` env vars
- No `openclaw gateway health` check (hermes has its own health endpoint, if any)
- No `observe-recovery` cleanup (hermes-specific)
- Config file is `config.yaml` not `openclaw.json` (but openclaw.json is still the source of truth, bridged)

### 4.3 `deploy/hiclaw/hermes-config-bridge.sh` (new)

```bash
#!/bin/bash
# Translates openclaw.json → ~/.hermes/config.yaml + .env
# Rewritten every bridge run (startup + config push). Non-bridge-owned keys preserved.
set -euo pipefail

OPENCLAW_JSON="${1:-${HOME}/hiclaw-fs/agents/${HICLAW_WORKER_NAME}/openclaw.json}"
HERMES_DIR="${HOME}/.hermes"
CONFIG_YAML="${HERMES_DIR}/config.yaml"
ENV_FILE="${HERMES_DIR}/.env"

mkdir -p "$HERMES_DIR"

# Extract from openclaw.json using jq
MATRIX_HOMESERVER=$(jq -r '.channels.matrix.homeserver // empty' "$OPENCLAW_JSON")
MATRIX_USER=$(jq -r '.channels.matrix.userId // .channels.matrix.user // empty' "$OPENCLAW_JSON")
MATRIX_TOKEN=$(jq -r '.channels.matrix.accessToken // empty' "$OPENCLAW_JSON")
MODEL_PROVIDER=$(jq -r '.model.provider // empty' "$OPENCLAW_JSON")
MODEL_NAME=$(jq -r '.model.model // .model.name // empty' "$OPENCLAW_JSON")
OPENAI_BASE_URL=$(jq -r '.model.baseUrl // empty' "$OPENCLAW_JSON")
OPENAI_API_KEY=$(jq -r '.model.apiKey // .model.openaiApiKey // empty' "$OPENCLAW_JSON")

# Generate config.yaml (bridge-owned blocks)
# NOTE: preserve any non-bridge-owned YAML by appending, not overwriting
cat > "$CONFIG_YAML" << YAML
# Generated by hermes-config-bridge.sh — do not edit bridge-owned sections.
# Bridge-owned: model, matrix, platforms.matrix
model:
  provider: ${MODEL_PROVIDER}
  name: ${MODEL_NAME}

matrix:
  homeserver: ${MATRIX_HOMESERVER}
  user_id: ${MATRIX_USER}
  access_token: ${MATRIX_TOKEN}

platforms:
  matrix:
    homeserver: ${MATRIX_HOMESERVER}
    user_id: ${MATRIX_USER}
    access_token: ${MATRIX_TOKEN}
YAML

# Append any user-added YAML outside bridge-owned blocks (preserved across re-runs)
# TODO: implement preservation logic (similar to merge-openclaw-config.sh)

# Generate .env (bridge-owned: MATRIX_*, OPENAI_*)
# Preserve non-bridge-owned vars
TMP_ENV=$(mktemp)
{
  echo "# Bridge-owned (rewritten every run)"
  echo "MATRIX_HOMESERVER=${MATRIX_HOMESERVER}"
  echo "MATRIX_USER_ID=${MATRIX_USER}"
  echo "MATRIX_ACCESS_TOKEN=${MATRIX_TOKEN}"
  echo "OPENAI_BASE_URL=${OPENAI_BASE_URL}"
  echo "OPENAI_API_KEY=${OPENAI_API_KEY}"
  # Append preserved non-bridge-owned vars from existing .env
  if [ -f "$ENV_FILE" ]; then
    grep -vE '^(MATRIX_|OPENAI_)' "$ENV_FILE" 2>/dev/null || true
  fi
} > "$TMP_ENV"
mv "$TMP_ENV" "$ENV_FILE"

echo "[hermes-bridge] config.yaml and .env generated for ${HICLAW_WORKER_NAME}"
```

**Open question**: The exact `config.yaml` schema hermes-agent expects (model/matrix/platforms blocks) needs verification against hermes-agent docs. The AGENTS.md describes ownership boundaries but not the full schema.

### 4.4 `deploy/hiclaw/worker-init-wrapper.sh` (modified)

Add runtime detection at the top, branch the init logic:

```bash
# After WORKER_NAME assignment, add:
WORKER_RUNTIME="${HICLAW_WORKER_RUNTIME:-openclaw}"

if [ "$WORKER_RUNTIME" = "hermes" ]; then
    WORKER_ENTRYPOINT="/opt/honeybadge/init/hermes-worker-entrypoint.sh"
    AGENT_HOME="/root/.hermes"
    SESSIONS_FILE="${AGENT_HOME}/sessions/sessions.json"
else
    WORKER_ENTRYPOINT="/opt/hiclaw/scripts/worker-entrypoint.sh"
    AGENT_HOME="/root"
    SESSIONS_FILE="/root/.openclaw/agents/main/sessions/sessions.json"
fi

# Background init block: use $AGENT_HOME instead of hardcoded /root
# - SOUL.md copy target: $AGENT_HOME/SOUL.md
# - skills copy target: $AGENT_HOME/skills/
# - Matrix session wake-up: use hermes CLI if hermes, openclaw CLI if openclaw
```

**Key principle**: Single wrapper, runtime-aware branching. The graph-worker
keeps `HICLAW_WORKER_RUNTIME` unset (defaults to openclaw) — zero impact.

### 4.5 `deploy/docker/docker-compose.yaml` (modified)

```yaml
hiclaw-analytics-worker:
  image: honeybadge/hiclaw-hermes-worker:v1.1.2-1   # CHANGED from hiclaw-worker:v1.1.2
  container_name: honeybadge-analytics-worker
  hostname: hiclaw-analytics-worker
  restart: unless-stopped
  entrypoint: ["/bin/bash", "/opt/honeybadge/init/worker-init-wrapper.sh"]
  environment:
    - HICLAW_WORKER_NAME=analytics-worker
    - HICLAW_WORKER_RUNTIME=hermes              # NEW — triggers hermes code path
    - HICLAW_FS_ENDPOINT=http://hiclaw-embedded:9000
    - HICLAW_FS_ACCESS_KEY=${HICLAW_ADMIN_USER:-admin}
    - HICLAW_FS_SECRET_KEY=${HICLAW_ADMIN_PASSWORD:-admin1234}
    - TZ=Asia/Shanghai
  volumes:
    - ../hiclaw/worker-init-wrapper.sh:/opt/honeybadge/init/worker-init-wrapper.sh:ro
    # hermes-worker-entrypoint.sh and hermes-config-bridge.sh are baked into the image
  networks:
    - honeybadge-net
  depends_on:
    hiclaw-embedded:
      condition: service_healthy
    hiclaw-manager:
      condition: service_started
  labels:
    com.honeybadge.service: "hiclaw-analytics-worker"
    com.honeybadge.runtime: "hermes"            # NEW label for observability
    com.honeybadge.version: "${IMAGE_TAG:-latest}"
```

### 4.6 `hiclaw/workers/analytics-worker/agent/SOUL.md` (minor edit)

Two changes:
1. Identity line: "Analytics Worker" → "Analytics Worker (Hermes runtime)"
2. Add a note in the "How to Call MCP Tools" section: hermes uses the same
   `mcporter` CLI; no syntax change needed.

The `result.json` Python heredoc (Step 3b) is **kept as-is** — hermes is
Python-native, so `python3 - << 'JSONEOF'` works identically.

### 4.7 `hiclaw/workers/analytics-worker/agent/AGENTS.md` (new)

Mirror the structure of `/opt/hiclaw/agent/hermes-worker-agent/AGENTS.md`
(from the manager container) but customized for analytics-worker's role:
- Workspace layout: `~/.hermes/`
- Config bridge behavior
- @mention protocol (same as openclaw)
- NO_REPLY rules (same)
- Task execution workflow (same 5 steps as SOUL.md)

---

## 5. Verification Plan

### 5.1 Build verification
- [ ] `docker build -f deploy/hiclaw/Dockerfile.hermes-worker -t honeybadge/hiclaw-hermes-worker:v1.1.2-1 .` succeeds
- [ ] `docker run --rm honeybadge/hiclaw-hermes-worker:v1.1.2-1 hermes-agent --version` returns a version
- [ ] Image size < 1.5GB (openclaw worker is ~1.2GB)

### 5.2 Unit verification (bridge script)
- [ ] `hermes-config-bridge.sh` produces valid YAML given a sample openclaw.json
- [ ] `hermes-config-bridge.sh` preserves non-bridge-owned `.env` vars across re-runs
- [ ] `hermes-config-bridge.sh` fails loudly if openclaw.json is missing required keys

### 5.3 Integration verification (local docker-compose)
- [ ] `docker compose up hiclaw-analytics-worker` starts without crash
- [ ] Container logs show "[hermes-bridge] config.yaml and .env generated"
- [ ] `docker exec honeybadge-analytics-worker hermes-agent --health` (or equivalent) returns OK
- [ ] Matrix login: worker joins its DM room with @manager
- [ ] File sync: `~/.hermes/SOUL.md` matches MinIO version after 5min

### 5.4 Functional verification (E2E)
- [ ] **TC-CHAT-01**: User asks analytics question → @manager routes to analytics-worker → hermes executes → result.json written → frontend renders
- [ ] **TC-ANTIHAL-01**: L1/L2/L3/L4/L5 all pass (these are MCP-layer, runtime-agnostic)
- [ ] **TC-ISOLATION-01**: analytics-worker (hermes) and graph-worker (openclaw) run side-by-side without interference
- [ ] **TC-ANOMALY-01**: anomaly-detection skill triggers correctly (SKILL.md portability validation)
- [ ] **TC-MULTISTEP-01**: multi-step-analysis skill completes 8-round query (hermes session persistence)

### 5.5 Regression verification
- [ ] All existing E2E tests in `tests/e2e/` pass (except analytics-specific ones, which are replaced by TC-ANOMALY-01/TC-MULTISTEP-01)
- [ ] graph-worker behavior unchanged (smoke test: TC-CHAT-02 graph query still works)

### 5.6 Observability verification
- [ ] Grafana shows analytics-worker panel with `runtime=hermes` label
- [ ] Audit log in PostgreSQL captures trace_id for hermes-executed queries (L5)
- [ ] Prometheus scrapes hermes-agent metrics (if exposed)

---

## 6. Rollback Plan

### 6.1 Rollback trigger
- Any CRITICAL issue in functional verification (5.4)
- analytics-worker fails to start after 3 retries
- E2E regression rate > 20%

### 6.2 Rollback procedure (time: ~5 minutes)

```bash
# 1. Revert docker-compose.yaml analytics-worker section to openclaw
git checkout HEAD~1 -- deploy/docker/docker-compose.yaml

# 2. Restart only analytics-worker (graph-worker unaffected)
docker compose -f deploy/docker/docker-compose.yaml up -d hiclaw-analytics-worker

# 3. Verify rollback
docker exec honeybadge-analytics-worker openclaw --version
# Should print: OpenClaw 2026.4.14
```

### 6.3 Rollback safety guarantees
- `worker-init-wrapper.sh` changes are backward-compatible (defaults to openclaw)
- No database schema changes → no data migration to reverse
- No MinIO object format changes → config files readable by both runtimes
- Matrix account `@analytics-worker` is reused (no account churn)
- SOUL.md changes are cosmetic (identity label) → openclaw ignores the hermes label

---

## 7. Open Questions & Risks

### 7.1 Blocking questions (must resolve before implementation)

| # | Question | How to resolve |
|---|----------|----------------|
| Q1 | Is `hermes-agent` published on PyPI? | `pip install hermes-agent --dry-run` from a machine with pip; or check HiClaw official docs |
| Q2 | What is the exact `config.yaml` schema hermes-agent expects? | Read hermes-agent docs or source; verify against AGENTS.md ownership table |
| Q3 | Does hermes-agent have a health check endpoint? | `hermes-agent --help` or docs; needed for readiness reporter |
| Q4 | How does hermes-agent handle Matrix E2EE? | AGENTS.md mentions "custom Matrix adapter" — verify crypto storage path and re-login flow |
| Q5 | Does hermes-agent support the `exec` tool for mcporter CLI? | SKILL.md assumes `exec` tool exists; verify in hermes-agent docs |

### 7.2 Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| hermes-agent not on PyPI | Medium | **Blocker** | Check HiClaw distribution; may need to extract from a hermes-enabled image |
| SKILL.md format subtly incompatible | Low | Medium | Validation in 5.4 TC-ANOMALY-01; fallback to adapting phrasing |
| Matrix E2EE broken under hermes | Medium | High | Re-login flow in entrypoint; verify with Element Web |
| hermes-agent crashes on startup | Low | High | Rollback procedure (6.2) is < 5 min |
| Config bridge drops a critical key | Medium | Medium | Unit test bridge script (5.2); compare generated config.yaml against AGENTS.md spec |
| mcporter not on hermes PATH | Low | Medium | Dockerfile installs mcporter; verify in image build (5.1) |

### 7.3 Non-blocking observations

- Hermes `sessions/` directory enables cross-round anomaly tracking (future enhancement, not in scope)
- If hermes-agent exposes a Python API (not just CLI), future skills could be Python-native (Approach B evolution)
- `copaw` runtime (3rd option in v1.1.2) is not evaluated — out of scope

---

## 8. Milestones

| # | Milestone | Exit criteria |
|---|-----------|---------------|
| M1 | Resolve blocking questions Q1-Q5 | All answered with citations to docs/source |
| M2 | Build custom image | 5.1 passes |
| M3 | Write entrypoint + bridge scripts | 5.2 passes |
| M4 | Local integration test | 5.3 passes |
| M5 | E2E functional test | 5.4 passes |
| M6 | Regression + observability | 5.5 + 5.6 pass |
| M7 | PR review + merge | Merged to master |

**M1 is the gate**. If hermes-agent is not available as a pip package, this
design must be revised (possibly: wait for HiClaw to ship a hermes-enabled
worker image, or extract hermes-agent from a different distribution).

---

## 9. Out of Scope

- Migrating graph-worker to hermes (stays on openclaw)
- Migrating any worker to copaw (not evaluated)
- Python-native skill rewrite (Approach B — future enhancement after Approach A validates)
- Canary/dual-run infrastructure (Approach C — unnecessary for pilot)
- Hermes `sessions/` cross-round anomaly tracking (future enhancement)
- Production k8s manifests update (follow-on PR after local validation)

---

## 10. Assumptions (stated, pending user confirmation)

| # | Assumption | If wrong |
|---|------------|----------|
| A1 | Only analytics-worker migrates; graph-worker stays openclaw | Scope expands; redo blast radius analysis |
| A2 | Full runtime replacement, not parallel canary | If canary needed, switch to Approach C |
| A3 | Matrix account `@analytics-worker` is reused | If new account needed, update init-workers.sh + Manager allowlist |
| A4 | SKILL.md files are directly portable | If not, add a skill-adaptation sub-milestone to M3 |
| A5 | result.json contract must stay unchanged | If contract can change, simplify Step 3b (remove heredoc, use Python dataclass) |
| A6 | Rollback must be possible in < 5 min | If slower acceptable, simplify rollback procedure |
| A7 | No new LLM provider; still Higress gateway | If provider changes, update bridge .env generation |

---

## 11. Next Steps (after spec approval)

Per `brainstorming` SKILL.md terminal state, this spec transitions to the
`writing-plans` skill, which will produce a step-by-step implementation plan
in `docs/superpowers/plans/2026-06-28-analytics-hermes-migration-plan.md`.

The plan will:
1. Sequence the milestones M1-M7 into concrete tasks
2. Specify test cases for each task (TDD per `testing.md` rules)
3. Identify which tasks can run in parallel
4. Define the PR structure (single PR vs split)
