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
- `deploy/hiclaw/Dockerfile.hermes-worker` — **new** (extends worker image, installs hermes-agent + PYTHONPATH)
- `deploy/hiclaw/hermes-worker-entrypoint.sh` — **new** (parallel to worker-entrypoint.sh)
- `deploy/hiclaw/hermes-config-bridge.sh` — **new** (openclaw.json → config.yaml + .env)
- `deploy/hiclaw/worker-init-wrapper.sh` — **modified** (detect runtime, branch init logic)
- `deploy/docker/docker-compose.yaml` — **modified** (analytics-worker: image + entrypoint)
- `hiclaw/workers/analytics-worker/agent/SOUL.md` — **modified** (identity + Python module references + result_builder call)
- `hiclaw/workers/analytics-worker/agent/AGENTS.md` — **new** (hermes-specific behavioral rules + Python module reference)
- `hiclaw/workers/analytics-worker/agent/skills/common/` — **new** (Approach B: mcp_client.py, result_builder.py, severity.py, session_state.py)
- `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/` — **new** (Approach B: detect.py, patterns.py)
- `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/SKILL.md` — **modified** (reference Python entry points)
- `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/lib/` — **new** (Approach B: decompose.py, cross_reference.py)
- `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/SKILL.md` — **modified** (reference Python entry points)
- `tests/test_mcp_client.py`, `tests/test_result_builder.py`, `tests/test_severity.py`, `tests/test_session_state.py`, `tests/test_detect.py`, `tests/test_decompose.py` — **new** (Approach B TDD)

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

### 2.4 Skills porting strategy (Approach B: Python enhancement)

**Decision**: Rewrite both skills to use typed Python modules instead of raw
`mcporter` CLI strings. SKILL.md files are updated to instruct the LLM to call
Python entry points.

**Rationale** (Approach B selected by user):
- Hermes is Python-native — Python modules get type safety, proper error handling, testability
- Current SKILL.md files embed `mcporter call ...` strings that the LLM must format correctly (fragile)
- Python modules encapsulate detection logic (thresholds, severity classification) that currently lives as prose
- Enables structured result.json via dataclass + `json.dumps` (no heredoc)
- Enables cross-round anomaly tracking via hermes `sessions/` (openclaw cannot do this)

**Current state of skills** (both are pure markdown, no scripts):
- `anomaly-detection/SKILL.md` — 67 lines, detection patterns as prose + mcporter CLI examples
- `multi-step-analysis/SKILL.md` — 63 lines, decomposition flow as prose + mcporter CLI examples

**Target state** (Approach B):
- Each skill gains a `lib/` directory with typed Python modules
- SKILL.md instructs LLM to call `python3 -m anomaly_detection.detect ...` instead of raw mcporter
- Shared `common/` package provides MCP client wrapper + result builder

### 2.5 Python module architecture (Approach B)

**Decision**: Add a `common/` package shared by both skills, plus per-skill `lib/` modules.

```
hiclaw/workers/analytics-worker/agent/skills/
├── common/                          # NEW — shared library
│   ├── __init__.py
│   ├── mcp_client.py                # typed wrapper over mcporter subprocess
│   ├── result_builder.py            # dataclass-based result.json builder
│   ├── severity.py                  # INFO/WARNING/ALERT enum + threshold logic
│   └── session_state.py             # hermes sessions/ cross-round state
├── anomaly-detection/
│   ├── SKILL.md                     # MODIFIED — references Python entry points
│   └── lib/
│       ├── __init__.py
│       ├── detect.py                # three-way matching, duplicate invoice, etc.
│       └── patterns.py              # pattern definitions + thresholds
├── multi-step-analysis/
│   ├── SKILL.md                     # MODIFIED — references Python entry points
│   └── lib/
│       ├── __init__.py
│       ├── decompose.py             # question decomposition logic
│       └── cross_reference.py       # cross-query pattern matching
```

### 2.6 result.json generation (Approach B)

**Decision**: Replace the Python heredoc in SOUL.md Step 3b with a call to
`common.result_builder.build_result_json()`.

**Before** (current, in SOUL.md):
```bash
python3 - << 'JSONEOF'
import json, re, os, sys
# ... 40 lines of inline script parsing /tmp/mcp_*.json
JSONEOF
```

**After** (Approach B):
```bash
python3 -m common.result_builder \
  --task-id "{task-id}" \
  --generate-file /tmp/mcp_generate.json \
  --execute-file /tmp/mcp_execute.json \
  --result-md "{task_dir}/result.md" \
  --output "{task_dir}/result.json"
```

**Benefits**:
- Type-safe (dataclass with mypy validation)
- Testable in isolation (unit test with fixtures)
- Reusable by both skills
- Contract enforced at code level, not string-template level

### 2.7 Cross-round anomaly tracking via hermes sessions/ (Approach B)

**Decision**: Use hermes `~/.hermes/sessions/` to persist anomaly state across
query rounds within a single analysis task.

**Current limitation** (openclaw): Each `mcporter call` is stateless. The LLM
must re-read /tmp files and re-derive what was already flagged. Round 3 doesn't
"remember" round 1's findings except via LLM context.

**Approach B enhancement**: `common.session_state.AnomalyTracker` persists to
`~/.hermes/sessions/{task-id}/anomalies.json` after each round:
- Deduplicates anomalies already flagged
- Tracks severity escalation (INFO → WARNING → ALERT across rounds)
- Provides a summary at task completion for the audit log

**Out of scope for this migration**: Cross-task learning (persisting anomalies
across different task IDs) — that requires a shared store and is a future enhancement.

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

### 4.6 `hiclaw/workers/analytics-worker/agent/SOUL.md` (modified — Approach B)

Changes from current SOUL.md:

1. **Identity line**: "Analytics Worker" → "Analytics Worker (Hermes runtime)"
2. **"How to Call MCP Tools" section**: Replace raw `mcporter call` examples with
   Python module entry points:
   ```bash
   # Instead of: mcporter call honeybadge-nebula.generate_query --args '{"question":"..."}'
   # Use:
   python3 -m common.mcp_client generate_query --question "..."
   python3 -m common.mcp_client validate_and_execute --ngql "..." --user-id "..."
   ```
3. **Step 3b (result.json)**: Replace the 40-line Python heredoc with:
   ```bash
   python3 -m common.result_builder \
     --task-id "{task-id}" \
     --generate-file /tmp/mcp_generate.json \
     --execute-file /tmp/mcp_execute.json \
     --result-md "$TASK_DIR/result.md" \
     --output "$TASK_DIR/result.json"
   ```
4. **Step 2 (execute analysis)**: Add session state tracking:
   ```bash
   # After each round, persist anomalies for cross-round deduplication
   python3 -m common.session_state save \
     --task-id "{task-id}" \
     --round 2 \
     --anomalies '[{"type":"duplicate_invoice","severity":"WARNING",...}]'
   ```
5. **Add "Python Module Reference" section** at the end of SOUL.md documenting
   the available `common.*` and skill-specific `lib.*` entry points.

**Unchanged**: Step 1 (read spec), Step 3a (result.md heredoc), Step 4 (mc sync),
Step 5 (notify completion), Constraints section, Core Behavior section.

### 4.7 `hiclaw/workers/analytics-worker/agent/AGENTS.md` (new)

Mirror the structure of `/opt/hiclaw/agent/hermes-worker-agent/AGENTS.md`
(from the manager container) but customized for analytics-worker's role:
- Workspace layout: `~/.hermes/`
- Config bridge behavior
- @mention protocol (same as openclaw)
- NO_REPLY rules (same)
- Task execution workflow (same 5 steps as SOUL.md)
- **Python module reference** (Approach B): document `common.*` and skill `lib.*` entry points

### 4.8 Python Enhancement Modules (Approach B — new)

#### 4.8.1 `skills/common/mcp_client.py`

Typed wrapper over `mcporter` subprocess calls. Replaces raw CLI strings in SKILL.md.

```python
"""Typed MCP client — wraps mcporter subprocess for analytics-worker skills."""
from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class QueryResult:
    trace_id: str
    ngql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: int
    success: bool

class MCPClient:
    def __init__(self, server: str = "honeybadge-nebula"):
        self._server = server

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        cmd = ["mcporter", "call", f"{self._server}.{tool}",
               "--args", json.dumps(args, ensure_ascii=False)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"mcporter {tool} failed: {result.stderr[:200]}")
        return json.loads(result.stdout)

    def generate_query(self, question: str) -> dict:
        return self.call("generate_query", {"question": question})

    def validate_and_execute(self, ngql: str, user_id: str | None = None) -> QueryResult:
        args = {"ngql": ngql}
        if user_id:
            args["user_context"] = {"user_id": user_id}
        raw = self.call("validate_and_execute", args)
        return QueryResult(
            trace_id=raw.get("trace_id", ""),
            ngql=raw.get("ngql", ngql),
            columns=raw.get("columns", []),
            rows=raw.get("rows", []),
            row_count=raw.get("row_count", len(raw.get("rows", []))),
            execution_time_ms=raw.get("execution_time_ms", 0),
            success=raw.get("success", True),
        )

# CLI entry point: python3 -m common.mcp_client generate_query --question "..."
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=["generate_query", "validate_and_execute", ...])
    parser.add_argument("--question"); parser.add_argument("--ngql"); parser.add_argument("--user-id")
    args = parser.parse_args()
    client = MCPClient()
    # ... dispatch
```

#### 4.8.2 `skills/common/result_builder.py`

Replaces the 40-line Python heredoc in SOUL.md Step 3b.

```python
"""Build result.json from saved MCP responses — replaces SOUL.md heredoc."""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass(frozen=True)
class TaskResult:
    trace_id: str
    cypher: str
    columns: list[str]
    raw_data: list[dict]
    row_count: int
    execution_time_ms: int
    summary: str

def _parse_summary(result_md_path: Path) -> str:
    md = result_md_path.read_text(encoding="utf-8")
    m = re.search(r"## Summary\n(.*?)(?=\n## |\Z)", md, re.DOTALL)
    return m.group(1).strip() if m else ""

def build(generate_file: Path, execute_file: Path, result_md: Path) -> TaskResult:
    gen = json.loads(generate_file.read_text(encoding="utf-8"))
    exe = json.loads(execute_file.read_text(encoding="utf-8"))
    rows = exe.get("rows", [])
    return TaskResult(
        trace_id=exe.get("trace_id", ""),
        cypher=gen.get("ngql", ""),
        columns=exe.get("columns", []),
        raw_data=rows,
        row_count=exe.get("row_count", len(rows)),
        execution_time_ms=exe.get("execution_time_ms", 0),
        summary=_parse_summary(result_md),
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--generate-file", required=True)
    parser.add_argument("--execute-file", required=True)
    parser.add_argument("--result-md", required=True)
    parser.add_argument("--output", required=True)
    a = parser.parse_args()
    result = build(Path(a.generate_file), Path(a.execute_file), Path(a.result_md))
    Path(a.output).write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"result.json written ({result.row_count} rows, trace={result.trace_id})")
```

#### 4.8.3 `skills/common/severity.py`

```python
"""Severity classification for anomaly detection."""
from enum import Enum

class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ALERT = "ALERT"

def classify(value: float, soft_threshold: float, hard_threshold: float) -> Severity:
    if value >= hard_threshold:
        return Severity.ALERT
    if value >= soft_threshold:
        return Severity.WARNING
    return Severity.INFO
```

#### 4.8.4 `skills/common/session_state.py`

Cross-round anomaly tracking via hermes `~/.hermes/sessions/`.

```python
"""Persist anomaly state across query rounds within a task."""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class Anomaly:
    type: str
    severity: str
    evidence: dict
    round: int

class AnomalyTracker:
    def __init__(self, task_id: str, sessions_dir: str = "~/.hermes/sessions"):
        self._path = Path(sessions_dir).expanduser() / task_id / "anomalies.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, anomalies: list[Anomaly]) -> None:
        existing = self.load()
        # Deduplicate by (type, severity) — keep highest round
        seen = {(a.type, a.severity) for a in existing}
        for a in anomalies:
            if (a.type, a.severity) not in seen:
                existing.append(a)
                seen.add((a.type, a.severity))
        self._path.write_text(json.dumps([asdict(a) for a in existing], ensure_ascii=False, indent=2))

    def load(self) -> list[Anomaly]:
        if not self._path.exists():
            return []
        return [Anomaly(**d) for d in json.loads(self._path.read_text())]
```

#### 4.8.5 `skills/anomaly-detection/lib/detect.py`

Encapsulates detection patterns currently described as prose in SKILL.md.

```python
"""Anomaly detection patterns — replaces prose in anomaly-detection/SKILL.md."""
from __future__ import annotations
from dataclasses import dataclass
from common.mcp_client import MCPClient, QueryResult
from common.severity import Severity, classify
from common.session_state import Anomaly, AnomalyTracker

# Thresholds (from current SKILL.md prose)
THREE_WAY_TOLERANCE = 1.10  # 10% tolerance
DUPLICATE_INVOICE_COUNT = 1  # flag if count > 1
PAYMENT_DEVIATION_FACTOR = 2.0  # flag if > 2x historical average
NEW_SUPPLIER_DAYS = 90
SUPPLIER_CONCENTRATION = 0.60  # flag if > 60% of category spend

@dataclass
class DetectionContext:
    client: MCPClient
    tracker: AnomalyTracker
    user_id: str | None = None

def detect_three_way_mismatch(ctx: DetectionContext, po_id: str) -> list[Anomaly]:
    # Query PO, Receipt, Invoice amounts; compare; flag if invoice > PO * tolerance
    ...

def detect_duplicate_invoices(ctx: DetectionContext, supplier_id: str | None = None) -> list[Anomaly]:
    ...

def detect_unusual_payments(ctx: DetectionContext, days: int = 90) -> list[Anomaly]:
    ...

def detect_supplier_concentration(ctx: DetectionContext, category: str | None = None) -> list[Anomaly]:
    ...
```

#### 4.8.6 `skills/multi-step-analysis/lib/decompose.py`

```python
"""Question decomposition for multi-step analysis."""
from __future__ import annotations
from dataclasses import dataclass
from common.mcp_client import MCPClient

@dataclass(frozen=True)
class SubQuery:
    description: str
    question: str
    round: int

def decompose(question: str, client: MCPClient) -> list[SubQuery]:
    """Use generate_query to break a complex question into sub-queries."""
    ...

def cross_reference(results: list[QueryResult]) -> dict:
    """Find patterns across sub-query results."""
    ...
```

#### 4.8.7 SKILL.md modifications

**`anomaly-detection/SKILL.md`** — replace the "How to Call MCP Tools" and
"Detection Patterns" sections with references to Python modules:

```markdown
## How to Run Detection (CRITICAL)

Call the Python detection modules instead of raw mcporter CLI:

\```bash
# Three-way matching
python3 -m anomaly_detection.lib.detect three-way --po-id "PO-2026-001"

# Duplicate invoices
python3 -m anomaly_detection.lib.detect duplicate-invoices --supplier-id "S001"

# Unusual payments (last 90 days)
python3 -m anomaly_detection.lib.detect unusual-payments --days 90
\```

## Detection Patterns

Pattern definitions and thresholds are in `lib/patterns.py`.
See `lib/detect.py` for the implementation.
```

**`multi-step-analysis/SKILL.md`** — similar restructuring to reference
`lib/decompose.py` and `lib/cross_reference.py`.

#### 4.8.8 Python package layout in Dockerfile

The `Dockerfile.hermes-worker` must add the skills directory to `PYTHONPATH`
so `python3 -m common.mcp_client` resolves:

```dockerfile
ENV PYTHONPATH="${PYTHONPATH}:/root/.hermes/skills"
```

---

## 5. Verification Plan

### 5.1 Build verification
- [ ] `docker build -f deploy/hiclaw/Dockerfile.hermes-worker -t honeybadge/hiclaw-hermes-worker:v1.1.2-1 .` succeeds
- [ ] `docker run --rm honeybadge/hiclaw-hermes-worker:v1.1.2-1 hermes-agent --version` returns a version
- [ ] Image size < 1.5GB (openclaw worker is ~1.2GB)

### 5.2 Unit verification

#### 5.2a Bridge script
- [ ] `hermes-config-bridge.sh` produces valid YAML given a sample openclaw.json
- [ ] `hermes-config-bridge.sh` preserves non-bridge-owned `.env` vars across re-runs
- [ ] `hermes-config-bridge.sh` fails loudly if openclaw.json is missing required keys

#### 5.2b Python modules (Approach B) — TDD, 80%+ coverage required
- [ ] `tests/test_mcp_client.py`: `MCPClient.call()` parses mcporter stdout correctly
- [ ] `tests/test_mcp_client.py`: `MCPClient.call()` raises on non-zero exit code
- [ ] `tests/test_mcp_client.py`: `validate_and_execute()` returns properly typed `QueryResult`
- [ ] `tests/test_result_builder.py`: `build()` parses summary from result.md correctly
- [ ] `tests/test_result_builder.py`: `build()` handles missing `## Summary` section gracefully
- [ ] `tests/test_result_builder.py`: CLI entry point writes valid JSON to output path
- [ ] `tests/test_severity.py`: `classify()` returns INFO/WARNING/ALERT at correct thresholds
- [ ] `tests/test_session_state.py`: `AnomalyTracker.save()` deduplicates by (type, severity)
- [ ] `tests/test_session_state.py`: `AnomalyTracker.load()` returns empty list for new task
- [ ] `tests/test_session_state.py`: `AnomalyTracker` persists across instances (file-backed)
- [ ] `tests/test_detect.py`: three-way mismatch flags when invoice > PO * 1.10
- [ ] `tests/test_detect.py`: duplicate invoice flags when count > 1
- [ ] `tests/test_detect.py`: unusual payment flags when amount > 2x historical average
- [ ] `tests/test_detect.py`: supplier concentration flags when > 60% category spend
- [ ] `tests/test_decompose.py`: `decompose()` produces 2-5 sub-queries
- [ ] `tests/test_decompose.py`: `cross_reference()` finds patterns across results
- [ ] `pytest --cov=common --cov=anomaly_detection --cov=multi_step_analysis` reports ≥ 80%

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
- [ ] **TC-ANOMALY-01**: anomaly-detection skill triggers correctly via `python3 -m anomaly_detection.lib.detect`
- [ ] **TC-ANOMALY-02**: three-way matching flags invoice > PO * 1.10 (Approach B Python module)
- [ ] **TC-ANOMALY-03**: duplicate invoice detection flags count > 1 (Approach B Python module)
- [ ] **TC-MULTISTEP-01**: multi-step-analysis skill completes 8-round query via `python3 -m multi_step_analysis.lib.decompose`
- [ ] **TC-SESSION-01**: `AnomalyTracker` persists anomalies across rounds within a task (Approach B session state)
- [ ] **TC-SESSION-02**: Same anomaly flagged in round 1 is not re-flagged in round 3 (deduplication)
- [ ] **TC-RESULT-01**: result.json built by `common.result_builder` matches the contract consumed by forward-to-user.sh

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
- SOUL.md changes (identity label + Python module references) → openclaw ignores unknown Python references; openclaw falls back to its own SOUL.md from MinIO (the hermes-modified version is in the worktree branch, not merged to master until M7)
- Python modules (`common/`, `lib/`) are additive files → openclaw runtime never loads them; they're inert during rollback
- `sessions/` anomaly state files are per-task JSON → harmless if left behind after rollback

---

## 7. Open Questions & Risks

### 7.1 Blocking questions (must resolve before implementation)

| # | Question | How to resolve |
|---|----------|----------------|
| Q1 | Is `hermes-agent` published on PyPI? | `pip install hermes-agent --dry-run` from a machine with pip; or check HiClaw official docs |
| Q2 | What is the exact `config.yaml` schema hermes-agent expects? | Read hermes-agent docs or source; verify against AGENTS.md ownership table |
| Q3 | Does hermes-agent have a health check endpoint? | `hermes-agent --help` or docs; needed for readiness reporter |
| Q4 | How does hermes-agent handle Matrix E2EE? | AGENTS.md mentions "custom Matrix adapter" — verify crypto storage path and re-login flow |
| Q5 | Does hermes-agent support the `exec` tool for mcporter CLI? | **Approach B makes this moot** — Python modules call mcporter via subprocess, not via hermes `exec` tool. Verify `subprocess.run(["mcporter", ...])` works in hermes-agent's Python environment |

### 7.2 Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| hermes-agent not on PyPI | Medium | **Blocker** | Check HiClaw distribution; may need to extract from a hermes-enabled image |
| SKILL.md Python module references not understood by hermes LLM | Low | Medium | Validation in 5.4 TC-ANOMALY-01; SKILL.md instructions are explicit CLI commands |
| Matrix E2EE broken under hermes | Medium | High | Re-login flow in entrypoint; verify with Element Web |
| hermes-agent crashes on startup | Low | High | Rollback procedure (6.2) is < 5 min |
| Config bridge drops a critical key | Medium | Medium | Unit test bridge script (5.2a); compare generated config.yaml against AGENTS.md spec |
| mcporter not on hermes PATH | Low | Medium | Dockerfile installs mcporter; verify in image build (5.1) |
| Python modules have bugs that corrupt result.json | Medium | High | TDD with 80%+ coverage (5.2b); result.json contract test (TC-RESULT-01); rollback to heredoc if needed |
| `sessions/` anomaly state lost on container restart | Low | Low | Per-task state is ephemeral; only matters within a single analysis task |

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
| M3 | Write entrypoint + bridge scripts | 5.2a passes |
| **M3a** | **Write Python enhancement modules (Approach B)** | **5.2b passes (TDD, 80%+ coverage)** |
| M4 | Local integration test | 5.3 passes |
| M5 | E2E functional test | 5.4 passes (incl. TC-SESSION-01/02, TC-ANOMALY-02/03) |
| M6 | Regression + observability | 5.5 + 5.6 pass |
| M7 | PR review + merge | Merged to master |

**M1 is the gate**. If hermes-agent is not available as a pip package, this
design must be revised (possibly: wait for HiClaw to ship a hermes-enabled
worker image, or extract hermes-agent from a different distribution).

**M3a can run in parallel with M3** — Python modules don't depend on the
hermes entrypoint/bridge scripts. TDD: write tests first (RED), implement
(GREEN), then validate against real MCP responses in M4.

---

## 9. Out of Scope

- Migrating graph-worker to hermes (stays on openclaw)
- Migrating any worker to copaw (not evaluated)
- Cross-task anomaly learning (persisting anomalies across different task IDs — future enhancement beyond Approach B's per-task sessions)
- Canary/dual-run infrastructure (Approach C — unnecessary for pilot)
- Production k8s manifests update (follow-on PR after local validation)

---

## 10. Assumptions (stated, pending user confirmation)

| # | Assumption | If wrong |
|---|------------|----------|
| A1 | Only analytics-worker migrates; graph-worker stays openclaw | Scope expands; redo blast radius analysis |
| A2 | Full runtime replacement + Python enhancement (Approach B), not parallel canary | If canary needed, switch to Approach C |
| A3 | Matrix account `@analytics-worker` is reused | If new account needed, update init-workers.sh + Manager allowlist |
| A4 | SKILL.md files restructured to reference Python modules (Approach B) | If hermes rejects SKILL.md format entirely, deeper rewrite needed |
| A5 | result.json contract stays unchanged (built by `common.result_builder` instead of heredoc) | If contract can change, simplify dataclass fields |
| A6 | Rollback must be possible in < 5 min | If slower acceptable, simplify rollback procedure |
| A7 | No new LLM provider; still Higress gateway | If provider changes, update bridge .env generation |
| A8 | `mcporter` CLI is available in the hermes worker container (subprocess calls work) | If not, Dockerfile must install mcporter; verify in M2 |

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
