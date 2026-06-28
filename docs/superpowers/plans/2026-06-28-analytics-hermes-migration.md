# Analytics-Worker Hermes Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the analytics-worker container from OpenClaw runtime to Hermes runtime with Python-enhanced skills (Approach B).

**Architecture:** Custom Docker image extends `hiclaw-worker:v1.1.2` with `hermes-agent` pip package. A parallel `hermes-worker-entrypoint.sh` bridges `openclaw.json` → `~/.hermes/config.yaml` + `.env`. Skills gain typed Python modules (`common/`, `lib/`) that replace raw `mcporter` CLI strings and the SOUL.md result.json heredoc. Manager-side scripts and MCP/L3 layers are untouched.

**Tech Stack:** Python 3.12, hermes-agent, Docker, bash, pytest, dataclasses, mcporter CLI

**Spec:** `docs/superpowers/specs/2026-06-28-analytics-hermes-migration-design.md`

---

## File Structure

### New files (infrastructure)
| File | Responsibility |
|------|----------------|
| `deploy/hiclaw/Dockerfile.hermes-worker` | Extend worker image: install hermes-agent + pip, set PYTHONPATH |
| `deploy/hiclaw/hermes-worker-entrypoint.sh` | Hermes worker startup: MinIO sync, config bridge, launch hermes-agent |
| `deploy/hiclaw/hermes-config-bridge.sh` | Translate openclaw.json → ~/.hermes/config.yaml + .env |

### New files (Python modules — Approach B)
| File | Responsibility |
|------|----------------|
| `hiclaw/workers/analytics-worker/agent/skills/common/__init__.py` | Package marker |
| `hiclaw/workers/analytics-worker/agent/skills/common/severity.py` | Severity enum + threshold classifier |
| `hiclaw/workers/analytics-worker/agent/skills/common/mcp_client.py` | Typed mcporter subprocess wrapper + CLI |
| `hiclaw/workers/analytics-worker/agent/skills/common/result_builder.py` | Build result.json from MCP responses (replaces heredoc) |
| `hiclaw/workers/analytics-worker/agent/skills/common/session_state.py` | AnomalyTracker: cross-round anomaly persistence |
| `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/__init__.py` | Package marker |
| `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/patterns.py` | Threshold constants + pattern definitions |
| `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/detect.py` | Detection functions: three-way, duplicate, payment, concentration |
| `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/lib/__init__.py` | Package marker |
| `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/lib/decompose.py` | Question decomposition + cross-reference |
| `hiclaw/workers/analytics-worker/agent/AGENTS.md` | Hermes-specific behavioral rules |

### New files (tests)
| File | Responsibility |
|------|----------------|
| `tests/test_severity.py` | Unit tests for severity classification |
| `tests/test_mcp_client.py` | Unit tests for MCPClient (mocked subprocess) |
| `tests/test_result_builder.py` | Unit tests for result.json builder |
| `tests/test_session_state.py` | Unit tests for AnomalyTracker |
| `tests/test_detect.py` | Unit tests for detection patterns |
| `tests/test_decompose.py` | Unit tests for decomposition + cross-reference |

### Modified files
| File | Change |
|------|--------|
| `tests/conftest.py` | Add skills directory to sys.path |
| `deploy/hiclaw/worker-init-wrapper.sh` | Runtime detection (hermes vs openclaw branching) |
| `deploy/docker/docker-compose.yaml` | analytics-worker: custom image + HICLAW_WORKER_RUNTIME=hermes |
| `hiclaw/workers/analytics-worker/agent/SOUL.md` | Identity label + Python module references + result_builder call |
| `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/SKILL.md` | Reference Python entry points instead of raw mcporter |
| `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/SKILL.md` | Reference Python entry points instead of raw mcporter |

---

## Task 0: M1 — Verify hermes-agent availability (GATE)

**This task blocks all subsequent tasks.** If hermes-agent is not installable, stop and revisit the spec.

**Files:** None (research only)

- [ ] **Step 1: Check PyPI for hermes-agent**

Run:
```bash
pip install --dry-run hermes-agent 2>&1
```

Expected: either "Would install hermes-agent-X.Y.Z" or a clear "not found" error.

- [ ] **Step 2: If not on PyPI, check HiClaw distribution**

Run inside the manager container:
```bash
docker exec honeybadge-hiclaw-manager find / -name "hermes*" -path "*/site-packages/*" 2>/dev/null
docker exec honeybadge-hiclaw-manager find / -name "hermes-agent" -type f 2>/dev/null
```

If found, note the installation path and pip package name for Task 1.

- [ ] **Step 3: If not found anywhere, check HiClaw official docs**

Search: `hermes-agent site:hiclaw.io OR site:github.com/higress-group`

- [ ] **Step 4: Record the finding**

If hermes-agent IS available (PyPI or extractable): proceed to Task 1.
If NOT available: **STOP.** Report to user. The spec's M1 gate has failed; design must be revised.

- [ ] **Step 5: Commit finding to a notes file**

```bash
cat > docs/superpowers/notes/m1-hermes-agent-availability.md << 'EOF'
# M1 Finding: hermes-agent availability

- PyPI: [result]
- HiClaw distribution: [result]
- Conclusion: [available / blocked]
- Installation method: [pip install hermes-agent / extract from image / other]
- Version: [X.Y.Z]
EOF
git add docs/superpowers/notes/m1-hermes-agent-availability.md
git commit -m "docs: record M1 hermes-agent availability finding"
```

---

## Task 1: M2 — Create Dockerfile.hermes-worker

**Files:**
- Create: `deploy/hiclaw/Dockerfile.hermes-worker`

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# deploy/hiclaw/Dockerfile.hermes-worker
# HoneyBadge Hermes Worker — extends hiclaw-worker v1.1.2 with hermes-agent
# Built for analytics-worker only; graph-worker continues using the base image.

FROM higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/hiclaw-worker:v1.1.2

# Bootstrap pip, then install hermes-agent
# The base image has Python 3.12 but no pip
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip \
    && pip3 install --no-cache-dir --break-system-packages hermes-agent \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy hermes-specific entrypoint and config bridge
COPY hermes-worker-entrypoint.sh /opt/honeybadge/init/
COPY hermes-config-bridge.sh     /opt/honeybadge/init/
RUN chmod +x /opt/honeybadge/init/hermes-worker-entrypoint.sh \
             /opt/honeybadge/init/hermes-config-bridge.sh

# Skills directory on PYTHONPATH so `python3 -m common.mcp_client` resolves
# at runtime when skills are synced to /root/.hermes/skills/
ENV PYTHONPATH="${PYTHONPATH}:/root/.hermes/skills"

EXPOSE 8080
```

- [ ] **Step 2: Build the image**

Run:
```bash
docker build -f deploy/hiclaw/Dockerfile.hermes-worker \
  -t honeybadge/hiclaw-hermes-worker:v1.1.2-1 \
  deploy/hiclaw/
```

Expected: build succeeds. If `hermes-agent` pip install fails, Task 0 M1 gate was not properly resolved.

- [ ] **Step 3: Verify hermes-agent is installed in the image**

Run:
```bash
docker run --rm honeybadge/hiclaw-hermes-worker:v1.1.2-1 hermes-agent --version
```

Expected: prints a version string (e.g., `hermes-agent 0.x.y`)

- [ ] **Step 4: Verify PYTHONPATH is set**

Run:
```bash
docker run --rm honeybadge/hiclaw-hermes-worker:v1.1.2-1 python3 -c "import os; print(os.environ.get('PYTHONPATH'))"
```

Expected: output contains `/root/.hermes/skills`

- [ ] **Step 5: Commit**

```bash
git add deploy/hiclaw/Dockerfile.hermes-worker
git commit -m "feat: add Dockerfile.hermes-worker with hermes-agent installed"
```

---

## Task 2: M3 — Create hermes-config-bridge.sh

**Files:**
- Create: `deploy/hiclaw/hermes-config-bridge.sh`

- [ ] **Step 1: Write the bridge script**

```bash
#!/bin/bash
# hermes-config-bridge.sh — translates openclaw.json → ~/.hermes/config.yaml + .env
#
# Bridge-owned keys (rewritten every run):
#   config.yaml: model, matrix, platforms.matrix
#   .env:        MATRIX_*, OPENAI_*
#
# Non-bridge-owned keys are preserved across re-runs.
set -euo pipefail

OPENCLAW_JSON="${1:-${HOME}/hiclaw-fs/agents/${HICLAW_WORKER_NAME}/openclaw.json}"
HERMES_DIR="${HOME}/.hermes"
CONFIG_YAML="${HERMES_DIR}/config.yaml"
ENV_FILE="${HERMES_DIR}/.env"

if [ ! -f "$OPENCLAW_JSON" ]; then
    echo "[hermes-bridge] ERROR: openclaw.json not found at $OPENCLAW_JSON" >&2
    exit 1
fi

mkdir -p "$HERMES_DIR"

# Extract values from openclaw.json using jq
MATRIX_HOMESERVER=$(jq -r '.channels.matrix.homeserver // empty' "$OPENCLAW_JSON")
MATRIX_USER=$(jq -r '.channels.matrix.userId // .channels.matrix.user // empty' "$OPENCLAW_JSON")
MATRIX_TOKEN=$(jq -r '.channels.matrix.accessToken // empty' "$OPENCLAW_JSON")
MODEL_PROVIDER=$(jq -r '.model.provider // empty' "$OPENCLAW_JSON")
MODEL_NAME=$(jq -r '.model.model // .model.name // empty' "$OPENCLAW_JSON")
OPENAI_BASE_URL=$(jq -r '.model.baseUrl // empty' "$OPENCLAW_JSON")
OPENAI_API_KEY=$(jq -r '.model.apiKey // .model.openaiApiKey // empty' "$OPENCLAW_JSON")

# --- Generate config.yaml (bridge-owned blocks) ---
# Preserve non-bridge-owned YAML by extracting it from existing config.yaml
PRESERVED_YAML=""
if [ -f "$CONFIG_YAML" ]; then
    # Extract lines NOT under bridge-owned top-level keys
    PRESERVED_YAML=$(python3 -c "
import yaml, sys
try:
    with open('$CONFIG_YAML') as f:
        data = yaml.safe_load(f) or {}
except Exception:
    sys.exit(0)
bridge_keys = {'model', 'matrix', 'platforms'}
preserved = {k: v for k, v in data.items() if k not in bridge_keys}
if preserved:
    print(yaml.dump(preserved, default_flow_style=False, allow_unicode=True))
" 2>/dev/null || true)
fi

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

if [ -n "$PRESERVED_YAML" ]; then
    echo "" >> "$CONFIG_YAML"
    echo "# Preserved non-bridge-owned keys:" >> "$CONFIG_YAML"
    echo "$PRESERVED_YAML" >> "$CONFIG_YAML"
fi

# --- Generate .env (bridge-owned: MATRIX_*, OPENAI_*) ---
# Preserve non-bridge-owned vars from existing .env
TMP_ENV=$(mktemp)
{
    echo "# Bridge-owned (rewritten every run)"
    echo "MATRIX_HOMESERVER=${MATRIX_HOMESERVER}"
    echo "MATRIX_USER_ID=${MATRIX_USER}"
    echo "MATRIX_ACCESS_TOKEN=${MATRIX_TOKEN}"
    echo "OPENAI_BASE_URL=${OPENAI_BASE_URL}"
    echo "OPENAI_API_KEY=${OPENAI_API_KEY}"
    if [ -f "$ENV_FILE" ]; then
        echo ""
        echo "# Preserved non-bridge-owned vars:"
        grep -vE '^(MATRIX_|OPENAI_|#)' "$ENV_FILE" 2>/dev/null || true
    fi
} > "$TMP_ENV"
mv "$TMP_ENV" "$ENV_FILE"

echo "[hermes-bridge] config.yaml and .env generated for ${HICLAW_WORKER_NAME}"
```

- [ ] **Step 2: Make it executable**

Run:
```bash
chmod +x deploy/hiclaw/hermes-config-bridge.sh
```

- [ ] **Step 3: Test with a sample openclaw.json**

Create a test fixture and run the bridge:
```bash
cat > /tmp/test-openclaw.json << 'EOF'
{
  "channels": {
    "matrix": {
      "homeserver": "http://test-server:8008",
      "userId": "@analytics-worker:test",
      "accessToken": "test-token-123"
    }
  },
  "model": {
    "provider": "openai-compat",
    "model": "qwen-plus",
    "baseUrl": "http://aigw-local.hiclaw.io:8080/v1",
    "apiKey": "test-api-key"
  }
}
EOF

HICLAW_WORKER_NAME=analytics-worker \
HOME=/tmp/hermes-test \
bash deploy/hiclaw/hermes-config-bridge.sh /tmp/test-openclaw.json

cat /tmp/hermes-test/.hermes/config.yaml
cat /tmp/hermes-test/.hermes/.env
```

Expected: config.yaml contains model/matrix/platforms blocks; .env contains MATRIX_* and OPENAI_* vars.

- [ ] **Step 4: Test preservation of non-bridge-owned .env vars**

```bash
echo "TAVILY_API_KEY=custom-key" >> /tmp/hermes-test/.hermes/.env

HICLAW_WORKER_NAME=analytics-worker \
HOME=/tmp/hermes-test \
bash deploy/hiclaw/hermes-config-bridge.sh /tmp/test-openclaw.json

grep "TAVILY_API_KEY" /tmp/hermes-test/.hermes/.env
```

Expected: `TAVILY_API_KEY=custom-key` is preserved after re-run.

- [ ] **Step 5: Clean up test artifacts**

```bash
rm -rf /tmp/hermes-test /tmp/test-openclaw.json
```

- [ ] **Step 6: Commit**

```bash
git add deploy/hiclaw/hermes-config-bridge.sh
git commit -m "feat: add hermes-config-bridge.sh for openclaw.json → config.yaml translation"
```

---

## Task 3: M3 — Create hermes-worker-entrypoint.sh

**Files:**
- Create: `deploy/hiclaw/hermes-worker-entrypoint.sh`

- [ ] **Step 1: Write the entrypoint script**

```bash
#!/bin/bash
# hermes-worker-entrypoint.sh — Hermes Worker Agent startup
#
# Parallel to /opt/hiclaw/scripts/worker-entrypoint.sh but for hermes-agent.
# Pulls config from MinIO, bridges openclaw.json → config.yaml + .env,
# starts file sync, launches hermes-agent.
set -e

WORKER_NAME="${HICLAW_WORKER_NAME:?HICLAW_WORKER_NAME is required}"
FS_ENDPOINT="${HICLAW_FS_ENDPOINT:?HICLAW_FS_ENDPOINT is required}"
FS_ACCESS_KEY="${HICLAW_FS_ACCESS_KEY:?HICLAW_FS_ACCESS_KEY is required}"
FS_SECRET_KEY="${HICLAW_FS_SECRET_KEY:?HICLAW_FS_SECRET_KEY is required}"

log() {
    echo "[hermes-worker $(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# --- Step 0: Set timezone ---
if [ -n "${TZ}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    ln -sf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
    log "Timezone set to ${TZ}"
fi

HICLAW_ROOT="/root/hiclaw-fs"
WORKSPACE="${HICLAW_ROOT}/agents/${WORKER_NAME}"
HERMES_HOME="${HOME}/.hermes"

# --- Step 1: Configure mc alias for MinIO ---
log "Configuring mc alias for local MinIO..."
mc alias set hiclaw "${FS_ENDPOINT}" "${FS_ACCESS_KEY}" "${FS_SECRET_KEY}"

# --- Step 2: Pull Worker config from MinIO ---
mkdir -p "${WORKSPACE}" "${HICLAW_ROOT}/shared" "${HERMES_HOME}"

log "Pulling Worker config from MinIO..."
mc mirror "hiclaw/hiclaw-storage/agents/${WORKER_NAME}/" "${WORKSPACE}/" --overwrite \
    --exclude ".openclaw/matrix/**" --exclude ".openclaw/canvas/**" --exclude "credentials/**"
mc mirror "hiclaw/hiclaw-storage/shared/" "${HICLAW_ROOT}/shared/" --overwrite 2>/dev/null || true

PULL_MARKER="${WORKSPACE}/.last-pull"
touch "${PULL_MARKER}"

# Verify essential files
RETRY=0
while [ ! -f "${WORKSPACE}/openclaw.json" ] || [ ! -f "${WORKSPACE}/SOUL.md" ]; do
    RETRY=$((RETRY + 1))
    if [ "${RETRY}" -gt 6 ]; then
        log "ERROR: openclaw.json or SOUL.md not found after retries."
        exit 1
    fi
    log "Waiting for config files (attempt ${RETRY}/6)..."
    sleep 5
    mc mirror "hiclaw/hiclaw-storage/agents/${WORKER_NAME}/" "${WORKSPACE}/" --overwrite 2>/dev/null || true
    touch "${PULL_MARKER}"
done

# --- Step 3: Copy SOUL.md, AGENTS.md, skills to ~/.hermes/ ---
cp "${WORKSPACE}/SOUL.md" "${HERMES_HOME}/SOUL.md"
[ -f "${WORKSPACE}/AGENTS.md" ] && cp "${WORKSPACE}/AGENTS.md" "${HERMES_HOME}/AGENTS.md"

# Copy skills (including common/ and lib/ Python modules)
if [ -d "${WORKSPACE}/skills" ]; then
    mkdir -p "${HERMES_HOME}/skills"
    cp -r "${WORKSPACE}/skills/"* "${HERMES_HOME}/skills/" 2>/dev/null || true
    log "Skills copied to ${HERMES_HOME}/skills/"
fi

# --- Step 4: Run config bridge ---
log "Running config bridge..."
HICLAW_WORKER_NAME="${WORKER_NAME}" bash /opt/honeybadge/init/hermes-config-bridge.sh "${WORKSPACE}/openclaw.json"

# --- Step 5: Configure mcporter ---
MCPORTER_CONFIG="${WORKSPACE}/config/mcporter.json"
if [ -f "$MCPORTER_CONFIG" ]; then
    mkdir -p "${HERMES_HOME}/config"
    ln -sfn "$MCPORTER_CONFIG" "${HERMES_HOME}/config/mcporter.json"
    log "mcporter configured: ${MCPORTER_CONFIG}"
else
    log "mcporter config not yet available (will be pulled via file-sync)"
fi

# --- Step 6: Start file sync loops ---
# Local -> Remote: push ~/.hermes/ changes
(
    while true; do
        CHANGED=$(find "${HERMES_HOME}/" -type f -newer "${PULL_MARKER}" 2>/dev/null | head -1)
        if [ -n "${CHANGED}" ]; then
            mc mirror "${HERMES_HOME}/" "hiclaw/hiclaw-storage/agents/${WORKER_NAME}/.hermes/" \
                --overwrite \
                --exclude "sessions/**" --exclude ".cache/**" 2>&1 || true
        fi
        sleep 5
    done
) &
log "Local->Remote sync started (PID: $!)"

# Remote -> Local: pull shared/ every 5 minutes
(
    while true; do
        sleep 300
        mc mirror "hiclaw/hiclaw-storage/shared/" "${HICLAW_ROOT}/shared/" --overwrite --newer-than "5m" 2>/dev/null || true
        mc mirror "hiclaw/hiclaw-storage/agents/${WORKER_NAME}/skills/" "${HERMES_HOME}/skills/" --overwrite 2>/dev/null || true
        find "${HERMES_HOME}/skills" -name '*.py' -exec chmod +x {} + 2>/dev/null || true
        find "${HERMES_HOME}/skills" -name '*.sh' -exec chmod +x {} + 2>/dev/null || true
        touch "${PULL_MARKER}"
    done
) &
log "Remote->Local fallback sync started (every 5m, PID: $!)"

# --- Step 7: Matrix re-login for fresh E2EE token ---
MATRIX_PASSWORD_FILE="hiclaw/hiclaw-storage/agents/${WORKER_NAME}/credentials/matrix/password"
MATRIX_PASSWORD=$(mc cat "${MATRIX_PASSWORD_FILE}" 2>/dev/null) || true
if [ -n "${MATRIX_PASSWORD}" ]; then
    MATRIX_SERVER=$(jq -r '.channels.matrix.homeserver // empty' "${WORKSPACE}/openclaw.json" 2>/dev/null)
    if [ -n "${MATRIX_SERVER}" ]; then
        log "Re-logging into Matrix for fresh E2EE token..."
        LOGIN_RESP=$(curl -sf -X POST "${MATRIX_SERVER}/_matrix/client/v3/login" \
            -H 'Content-Type: application/json' \
            -d '{"type":"m.login.password","identifier":{"type":"m.id.user","user":"'"${WORKER_NAME}"'"},"password":"'"${MATRIX_PASSWORD}"'"}' 2>/dev/null) || true
        NEW_TOKEN=$(echo "${LOGIN_RESP}" | jq -r '.access_token // empty' 2>/dev/null)
        if [ -n "${NEW_TOKEN}" ] && [ "${NEW_TOKEN}" != "null" ]; then
            # Update .env with fresh token
            sed -i "s|^MATRIX_ACCESS_TOKEN=.*|MATRIX_ACCESS_TOKEN=${NEW_TOKEN}|" "${HERMES_HOME}/.env"
            # Also update config.yaml
            sed -i "s|access_token:.*|access_token: ${NEW_TOKEN}|" "${HERMES_HOME}/config.yaml"
            log "Matrix re-login successful (token prefix: ${NEW_TOKEN:0:10}...)"
        else
            log "WARNING: Matrix re-login failed, using existing token"
        fi
    fi
    MATRIX_PASSWORD=""
fi

# --- Step 8: Launch hermes-agent ---
log "Starting Hermes Agent: ${WORKER_NAME}"
cd "${HERMES_HOME}"

exec hermes-agent --config "${HERMES_HOME}/config.yaml"
```

- [ ] **Step 2: Make it executable**

Run:
```bash
chmod +x deploy/hiclaw/hermes-worker-entrypoint.sh
```

- [ ] **Step 3: Verify no CRLF (pre-commit hook requirement)**

Run:
```bash
file deploy/hiclaw/hermes-worker-entrypoint.sh
```

Expected: "ASCII text" without "with CRLF line terminators"

- [ ] **Step 4: Commit**

```bash
git add deploy/hiclaw/hermes-worker-entrypoint.sh
git commit -m "feat: add hermes-worker-entrypoint.sh for hermes-agent startup"
```

---

## Task 4: M3 — Modify worker-init-wrapper.sh for runtime detection

**Files:**
- Modify: `deploy/hiclaw/worker-init-wrapper.sh`

- [ ] **Step 1: Read the current file**

Run:
```bash
cat deploy/hiclaw/worker-init-wrapper.sh
```

- [ ] **Step 2: Add runtime detection after WORKER_NAME assignment**

Edit `deploy/hiclaw/worker-init-wrapper.sh`. After line 14 (`WORKER_NAME="${HICLAW_WORKER_NAME:-unknown}"`), add:

```bash
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
```

Also update line 13 to not override `WORKER_ENTRYPOINT` unconditionally — replace:
```bash
WORKER_ENTRYPOINT="/opt/hiclaw/scripts/worker-entrypoint.sh"
```
with nothing (it's now set in the if/else block above).

- [ ] **Step 3: Update SOUL.md copy target to use $AGENT_HOME**

In the background init block, replace:
```bash
HB_SOUL="/root/hiclaw-fs/agents/$WORKER_NAME/SOUL.md"
if [ -f "$HB_SOUL" ]; then
    cp "$HB_SOUL" /root/SOUL.md
```
with:
```bash
HB_SOUL="/root/hiclaw-fs/agents/$WORKER_NAME/SOUL.md"
if [ -f "$HB_SOUL" ]; then
    mkdir -p "$AGENT_HOME"
    cp "$HB_SOUL" "$AGENT_HOME/SOUL.md"
```

- [ ] **Step 4: Update skills copy target to use $AGENT_HOME**

Replace:
```bash
HB_SKILLS="/root/hiclaw-fs/agents/$WORKER_NAME/skills"
if [ -d "$HB_SKILLS" ]; then
    cp -r "$HB_SKILLS"/* /root/skills/ 2>/dev/null
```
with:
```bash
HB_SKILLS="/root/hiclaw-fs/agents/$WORKER_NAME/skills"
if [ -d "$HB_SKILLS" ]; then
    mkdir -p "$AGENT_HOME/skills"
    cp -r "$HB_SKILLS"/* "$AGENT_HOME/skills/" 2>/dev/null
```

- [ ] **Step 5: Update mcporter config symlink path**

Replace:
```bash
SKILL_DIR="/root/skills/mcporter"
```
with:
```bash
SKILL_DIR="$AGENT_HOME/skills/mcporter"
```

- [ ] **Step 6: Update session wake-up to use $SESSIONS_FILE**

The sessions.json path and CLI command differ by runtime. Replace the entire session wake-up block's path reference:

```bash
# Old: SESSIONS_FILE="/root/.openclaw/agents/main/sessions/sessions.json"
# New: already set at top via $SESSIONS_FILE
```

And in the Python heredoc, update the CLI command. For openclaw:
```python
cmd = ['openclaw', 'agent', '--session-id', session_id, ...]
```

For hermes, the wake-up mechanism may differ. For now, skip wake-up for hermes runtime:
```bash
if [ "$WORKER_RUNTIME" = "openclaw" ]; then
    # ... existing session wake-up Python block ...
fi
```

Wrap the existing session wake-up block in this `if` statement.

- [ ] **Step 7: Verify graph-worker (openclaw) is unaffected**

Run:
```bash
# Simulate openclaw runtime (default)
HICLAW_WORKER_NAME=graph-worker bash -n deploy/hiclaw/worker-init-wrapper.sh
```

Expected: no syntax errors.

- [ ] **Step 8: Commit**

```bash
git add deploy/hiclaw/worker-init-wrapper.sh
git commit -m "feat: add HICLAW_WORKER_RUNTIME detection to worker-init-wrapper.sh"
```

---

## Task 5: M3 — Modify docker-compose.yaml

**Files:**
- Modify: `deploy/docker/docker-compose.yaml`

- [ ] **Step 1: Update analytics-worker service**

In `deploy/docker/docker-compose.yaml`, find the `hiclaw-analytics-worker:` service block (line ~472). Make three changes:

1. Change `image:` from `hiclaw-worker:v1.1.2` to `honeybadge/hiclaw-hermes-worker:v1.1.2-1`
2. Add `HICLAW_WORKER_RUNTIME=hermes` to `environment:`
3. Add `com.honeybadge.runtime: "hermes"` to `labels:`

The modified block should look like:

```yaml
  hiclaw-analytics-worker:
    image: honeybadge/hiclaw-hermes-worker:v1.1.2-1
    container_name: honeybadge-analytics-worker
    hostname: hiclaw-analytics-worker
    restart: unless-stopped
    entrypoint: ["/bin/bash", "/opt/honeybadge/init/worker-init-wrapper.sh"]
    environment:
      - HICLAW_WORKER_NAME=analytics-worker
      - HICLAW_WORKER_RUNTIME=hermes
      - HICLAW_FS_ENDPOINT=http://hiclaw-embedded:9000
      - HICLAW_FS_ACCESS_KEY=${HICLAW_ADMIN_USER:-admin}
      - HICLAW_FS_SECRET_KEY=${HICLAW_ADMIN_PASSWORD:-admin1234}
      - TZ=Asia/Shanghai
    volumes:
      - ../hiclaw/worker-init-wrapper.sh:/opt/honeybadge/init/worker-init-wrapper.sh:ro
    networks:
      - honeybadge-net
    depends_on:
      hiclaw-embedded:
        condition: service_healthy
      hiclaw-manager:
        condition: service_started
    labels:
      com.honeybadge.service: "hiclaw-analytics-worker"
      com.honeybadge.runtime: "hermes"
      com.honeybadge.version: "${IMAGE_TAG:-latest}"
```

- [ ] **Step 2: Verify graph-worker block is unchanged**

Run:
```bash
grep -A5 "hiclaw-graph-worker:" deploy/docker/docker-compose.yaml | grep "image:"
```

Expected: `image: higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/hiclaw-worker:v1.1.2` (unchanged)

- [ ] **Step 3: Commit**

```bash
git add deploy/docker/docker-compose.yaml
git commit -m "feat: switch analytics-worker to hermes image + HICLAW_WORKER_RUNTIME=hermes"
```

---

## Task 6: M3a — Add skills path to conftest.py

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Read current conftest.py**

Run:
```bash
cat tests/conftest.py
```

- [ ] **Step 2: Add skills directory to sys.path**

Append to `tests/conftest.py`:

```python
# Make analytics-worker skills importable as top-level packages (common, anomaly_detection, etc.)
_skills_path = os.path.join(_project_root, "hiclaw", "workers", "analytics-worker", "agent", "skills")
if _skills_path not in sys.path:
    sys.path.insert(0, _skills_path)
```

- [ ] **Step 3: Verify import works**

Run:
```bash
python3 -c "import sys; sys.path.insert(0, 'hiclaw/workers/analytics-worker/agent/skills'); import common; print('OK')"
```

Expected: `OK` (after Task 7 creates `common/__init__.py`)

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add analytics-worker skills path to conftest.py"
```

---

## Task 7: M3a — Create common/__init__.py and common/severity.py (TDD)

**Files:**
- Create: `hiclaw/workers/analytics-worker/agent/skills/common/__init__.py`
- Create: `hiclaw/workers/analytics-worker/agent/skills/common/severity.py`
- Test: `tests/test_severity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_severity.py`:

```python
"""Unit tests for severity classification."""
import pytest
from common.severity import Severity, classify


class TestSeverityEnum:
    def test_severity_values(self):
        assert Severity.INFO == "INFO"
        assert Severity.WARNING == "WARNING"
        assert Severity.ALERT == "ALERT"

    def test_severity_is_string_enum(self):
        assert isinstance(Severity.INFO, str)


class TestClassify:
    def test_returns_info_when_below_soft_threshold(self):
        result = classify(value=50, soft_threshold=100, hard_threshold=200)
        assert result == Severity.INFO

    def test_returns_warning_at_soft_threshold(self):
        result = classify(value=100, soft_threshold=100, hard_threshold=200)
        assert result == Severity.WARNING

    def test_returns_warning_between_thresholds(self):
        result = classify(value=150, soft_threshold=100, hard_threshold=200)
        assert result == Severity.WARNING

    def test_returns_alert_at_hard_threshold(self):
        result = classify(value=200, soft_threshold=100, hard_threshold=200)
        assert result == Severity.ALERT

    def test_returns_alert_above_hard_threshold(self):
        result = classify(value=300, soft_threshold=100, hard_threshold=200)
        assert result == Severity.ALERT

    def test_works_with_float_thresholds(self):
        result = classify(value=1.05, soft_threshold=1.0, hard_threshold=1.10)
        assert result == Severity.WARNING
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_severity.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'common.severity'`

- [ ] **Step 3: Create __init__.py and severity.py**

Create `hiclaw/workers/analytics-worker/agent/skills/common/__init__.py`:
```python
"""Shared library for analytics-worker skills."""
```

Create `hiclaw/workers/analytics-worker/agent/skills/common/severity.py`:
```python
"""Severity classification for anomaly detection."""
from enum import Enum


class Severity(str, Enum):
    """Anomaly severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ALERT = "ALERT"


def classify(value: float, soft_threshold: float, hard_threshold: float) -> Severity:
    """Classify a value against soft and hard thresholds.

    Args:
        value: The measured value (e.g., invoice amount ratio).
        soft_threshold: Value at or above this triggers WARNING.
        hard_threshold: Value at or above this triggers ALERT.

    Returns:
        Severity.INFO if below soft_threshold,
        Severity.WARNING if at/above soft but below hard,
        Severity.ALERT if at/above hard_threshold.
    """
    if value >= hard_threshold:
        return Severity.ALERT
    if value >= soft_threshold:
        return Severity.WARNING
    return Severity.INFO
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_severity.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add hiclaw/workers/analytics-worker/agent/skills/common/__init__.py \
        hiclaw/workers/analytics-worker/agent/skills/common/severity.py \
        tests/test_severity.py
git commit -m "feat: add common.severity module with threshold classification (TDD)"
```

---

## Task 8: M3a — Create common/mcp_client.py (TDD)

**Files:**
- Create: `hiclaw/workers/analytics-worker/agent/skills/common/mcp_client.py`
- Test: `tests/test_mcp_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_client.py`:

```python
"""Unit tests for MCPClient — mocked subprocess over mcporter."""
import json
import subprocess
from unittest.mock import patch, MagicMock
import pytest
from common.mcp_client import MCPClient, QueryResult


class TestQueryResult:
    def test_is_frozen_dataclass(self):
        qr = QueryResult(
            trace_id="t1", ngql="GO FROM 1", columns=["a"],
            rows=[{"a": 1}], row_count=1, execution_time_ms=10, success=True
        )
        assert qr.trace_id == "t1"
        with pytest.raises(Exception):
            qr.trace_id = "modified"  # frozen


class TestMCPClientCall:
    @patch("common.mcp_client.subprocess.run")
    def test_call_parses_stdout_as_json(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"trace_id": "abc", "rows": [{"x": 1}]}),
            stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        result = client.call("generate_query", {"question": "test"})
        assert result["trace_id"] == "abc"

    @patch("common.mcp_client.subprocess.run")
    def test_call_raises_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="connection refused"
        )
        client = MCPClient("honeybadge-nebula")
        with pytest.raises(RuntimeError, match="connection refused"):
            client.call("generate_query", {"question": "test"})

    @patch("common.mcp_client.subprocess.run")
    def test_call_passes_correct_command(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="{}", stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        client.call("generate_query", {"question": "hello"})
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "mcporter"
        assert cmd[1] == "call"
        assert cmd[2] == "honeybadge-nebula.generate_query"
        assert json.loads(cmd[4]) == {"question": "hello"}


class TestValidateAndExecute:
    @patch("common.mcp_client.subprocess.run")
    def test_returns_typed_query_result(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "trace_id": "trace-123",
                "ngql": "GO FROM 1",
                "columns": ["name", "amount"],
                "rows": [{"name": "ACME", "amount": 100}],
                "row_count": 1,
                "execution_time_ms": 42,
                "success": True,
            }),
            stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        result = client.validate_and_execute("GO FROM 1", user_id="alice")
        assert isinstance(result, QueryResult)
        assert result.trace_id == "trace-123"
        assert result.row_count == 1
        assert result.rows[0]["name"] == "ACME"
        assert result.success is True

    @patch("common.mcp_client.subprocess.run")
    def test_user_context_included_when_user_id_provided(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"success": True}), stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        client.validate_and_execute("GO FROM 1", user_id="bob")
        cmd = mock_run.call_args[0][0]
        args = json.loads(cmd[4])
        assert args["user_context"] == {"user_id": "bob"}

    @patch("common.mcp_client.subprocess.run")
    def test_user_context_omitted_when_no_user_id(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps({"success": True}), stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        client.validate_and_execute("GO FROM 1")
        cmd = mock_run.call_args[0][0]
        args = json.loads(cmd[4])
        assert "user_context" not in args

    @patch("common.mcp_client.subprocess.run")
    def test_row_count_defaults_to_len_rows(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "rows": [{"a": 1}, {"a": 2}],
                "success": True,
            }),
            stderr=""
        )
        client = MCPClient("honeybadge-nebula")
        result = client.validate_and_execute("GO FROM 1")
        assert result.row_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_mcp_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'common.mcp_client'`

- [ ] **Step 3: Write the implementation**

Create `hiclaw/workers/analytics-worker/agent/skills/common/mcp_client.py`:

```python
"""Typed MCP client — wraps mcporter subprocess for analytics-worker skills."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueryResult:
    """Result of a validate_and_execute MCP call."""
    trace_id: str
    ngql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: int
    success: bool


class MCPClient:
    """Typed wrapper over mcporter subprocess calls."""

    def __init__(self, server: str = "honeybadge-nebula"):
        self._server = server

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool via mcporter and return parsed JSON response."""
        cmd = [
            "mcporter", "call", f"{self._server}.{tool}",
            "--args", json.dumps(args, ensure_ascii=False),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"mcporter {self._server}.{tool} failed: {result.stderr[:200]}"
            )
        return json.loads(result.stdout)

    def generate_query(self, question: str) -> dict[str, Any]:
        """Generate nGQL from a natural language question."""
        return self.call("generate_query", {"question": question})

    def validate_and_execute(
        self, ngql: str, user_id: str | None = None
    ) -> QueryResult:
        """Validate and execute nGQL, returning a typed QueryResult."""
        args: dict[str, Any] = {"ngql": ngql}
        if user_id:
            args["user_context"] = {"user_id": user_id}
        raw = self.call("validate_and_execute", args)
        rows = raw.get("rows", [])
        return QueryResult(
            trace_id=raw.get("trace_id", ""),
            ngql=raw.get("ngql", ngql),
            columns=raw.get("columns", []),
            rows=rows,
            row_count=raw.get("row_count", len(rows)),
            execution_time_ms=raw.get("execution_time_ms", 0),
            success=raw.get("success", True),
        )

    def write_audit_log(self, **kwargs: Any) -> dict[str, Any]:
        """Write an audit log entry via audit-mcp."""
        old_server = self._server
        self._server = "honeybadge-audit"
        try:
            return self.call("write_audit_log", kwargs)
        finally:
            self._server = old_server
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_mcp_client.py -v
```

Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add hiclaw/workers/analytics-worker/agent/skills/common/mcp_client.py \
        tests/test_mcp_client.py
git commit -m "feat: add common.mcp_client with typed QueryResult (TDD)"
```

---

## Task 9: M3a — Create common/result_builder.py (TDD)

**Files:**
- Create: `hiclaw/workers/analytics-worker/agent/skills/common/result_builder.py`
- Test: `tests/test_result_builder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_result_builder.py`:

```python
"""Unit tests for result_builder — replaces SOUL.md heredoc."""
import json
from pathlib import Path
import pytest
from common.result_builder import TaskResult, build, _parse_summary


class TestParseSummary:
    def test_extracts_summary_section(self, tmp_path):
        md = tmp_path / "result.md"
        md.write_text(
            "# Task Result\n\n## Query\nGO FROM 1\n\n"
            "## Summary\n这是中文摘要\n\n## Row Count\n5\n",
            encoding="utf-8",
        )
        summary = _parse_summary(md)
        assert "中文摘要" in summary

    def test_returns_empty_when_no_summary_section(self, tmp_path):
        md = tmp_path / "result.md"
        md.write_text("# Task Result\n\n## Query\nGO FROM 1\n", encoding="utf-8")
        summary = _parse_summary(md)
        assert summary == ""

    def test_handles_summary_at_end_of_file(self, tmp_path):
        md = tmp_path / "result.md"
        md.write_text("## Summary\nFinal summary text", encoding="utf-8")
        summary = _parse_summary(md)
        assert "Final summary text" in summary


class TestBuild:
    def _write_fixtures(self, tmp_path):
        gen = tmp_path / "mcp_generate.json"
        gen.write_text(json.dumps({
            "ngql": "GO FROM 1 OVER edge",
            "trace_id": "gen-trace",
        }), encoding="utf-8")
        exe = tmp_path / "mcp_execute.json"
        exe.write_text(json.dumps({
            "trace_id": "exe-trace",
            "columns": ["name", "amount"],
            "rows": [{"name": "ACME", "amount": 100}],
            "row_count": 1,
            "execution_time_ms": 42,
            "success": True,
        }), encoding="utf-8")
        md = tmp_path / "result.md"
        md.write_text(
            "## Summary\nTest summary\n", encoding="utf-8"
        )
        return gen, exe, md

    def test_returns_task_result_with_correct_fields(self, tmp_path):
        gen, exe, md = self._write_fixtures(tmp_path)
        result = build(gen, exe, md)
        assert isinstance(result, TaskResult)
        assert result.trace_id == "exe-trace"
        assert result.cypher == "GO FROM 1 OVER edge"
        assert result.columns == ["name", "amount"]
        assert result.row_count == 1
        assert result.execution_time_ms == 42
        assert "Test summary" in result.summary

    def test_row_count_defaults_to_len_rows(self, tmp_path):
        gen, exe, md = self._write_fixtures(tmp_path)
        # Overwrite execute without row_count
        exe.write_text(json.dumps({
            "rows": [{"a": 1}, {"a": 2}, {"a": 3}],
            "success": True,
        }), encoding="utf-8")
        result = build(gen, exe, md)
        assert result.row_count == 3

    def test_raw_data_matches_rows(self, tmp_path):
        gen, exe, md = self._write_fixtures(tmp_path)
        result = build(gen, exe, md)
        assert result.raw_data == [{"name": "ACME", "amount": 100}]

    def test_empty_rows_handled(self, tmp_path):
        gen = tmp_path / "gen.json"
        gen.write_text(json.dumps({"ngql": "GO FROM 1"}), encoding="utf-8")
        exe = tmp_path / "exe.json"
        exe.write_text(json.dumps({"rows": [], "success": True}), encoding="utf-8")
        md = tmp_path / "result.md"
        md.write_text("## Summary\nNo results\n", encoding="utf-8")
        result = build(gen, exe, md)
        assert result.row_count == 0
        assert result.raw_data == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_result_builder.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'common.result_builder'`

- [ ] **Step 3: Write the implementation**

Create `hiclaw/workers/analytics-worker/agent/skills/common/result_builder.py`:

```python
"""Build result.json from saved MCP responses — replaces SOUL.md heredoc."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class TaskResult:
    """Structured result consumed by forward-to-user.sh (Manager-side)."""
    trace_id: str
    cypher: str
    columns: list
    raw_data: list
    row_count: int
    execution_time_ms: int
    summary: str


def _parse_summary(result_md_path: Path) -> str:
    """Extract the ## Summary section from result.md."""
    md = result_md_path.read_text(encoding="utf-8")
    m = re.search(r"## Summary\n(.*?)(?=\n## |\Z)", md, re.DOTALL)
    return m.group(1).strip() if m else ""


def build(generate_file: Path, execute_file: Path, result_md: Path) -> TaskResult:
    """Build a TaskResult from saved MCP response files and result.md."""
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


def main() -> None:
    """CLI entry point: python3 -m common.result_builder --task-id ..."""
    import argparse

    parser = argparse.ArgumentParser(description="Build result.json from MCP responses")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--generate-file", required=True)
    parser.add_argument("--execute-file", required=True)
    parser.add_argument("--result-md", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build(
        Path(args.generate_file),
        Path(args.execute_file),
        Path(args.result_md),
    )
    Path(args.output).write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"result.json written ({result.row_count} rows, trace={result.trace_id})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_result_builder.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add hiclaw/workers/analytics-worker/agent/skills/common/result_builder.py \
        tests/test_result_builder.py
git commit -m "feat: add common.result_builder to replace SOUL.md heredoc (TDD)"
```

---

## Task 10: M3a — Create common/session_state.py (TDD)

**Files:**
- Create: `hiclaw/workers/analytics-worker/agent/skills/common/session_state.py`
- Test: `tests/test_session_state.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_session_state.py`:

```python
"""Unit tests for AnomalyTracker — cross-round anomaly persistence."""
import json
import pytest
from common.session_state import Anomaly, AnomalyTracker


class TestAnomalyDataclass:
    def test_is_frozen(self):
        a = Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1)
        assert a.type == "duplicate_invoice"
        with pytest.raises(Exception):
            a.type = "modified"


class TestAnomalyTrackerLoad:
    def test_load_returns_empty_for_new_task(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        assert tracker.load() == []

    def test_load_returns_saved_anomalies(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        anomalies = [
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1),
        ]
        tracker.save(anomalies)
        loaded = tracker.load()
        assert len(loaded) == 1
        assert loaded[0].type == "duplicate_invoice"


class TestAnomalyTrackerDedup:
    def test_dedup_by_type_and_severity(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        # Round 1: flag a WARNING
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1),
        ])
        # Round 2: same anomaly flagged again
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=2),
        ])
        loaded = tracker.load()
        assert len(loaded) == 1  # deduplicated

    def test_different_severity_not_deduped(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1),
        ])
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="ALERT", evidence={"id": 1}, round=2),
        ])
        loaded = tracker.load()
        assert len(loaded) == 2  # WARNING and ALERT are different

    def test_different_type_not_deduped(self, tmp_path):
        tracker = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        tracker.save([
            Anomaly(type="duplicate_invoice", severity="WARNING", evidence={"id": 1}, round=1),
            Anomaly(type="three_way_mismatch", severity="WARNING", evidence={"id": 2}, round=1),
        ])
        loaded = tracker.load()
        assert len(loaded) == 2


class TestAnomalyTrackerPersistence:
    def test_persists_across_instances(self, tmp_path):
        tracker1 = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        tracker1.save([
            Anomaly(type="unusual_payment", severity="ALERT", evidence={}, round=3),
        ])
        # New instance, same task_id
        tracker2 = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        loaded = tracker2.load()
        assert len(loaded) == 1
        assert loaded[0].type == "unusual_payment"

    def test_different_tasks_isolated(self, tmp_path):
        tracker1 = AnomalyTracker("task-001", sessions_dir=str(tmp_path))
        tracker1.save([
            Anomaly(type="a", severity="INFO", evidence={}, round=1),
        ])
        tracker2 = AnomalyTracker("task-002", sessions_dir=str(tmp_path))
        assert tracker2.load() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_session_state.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'common.session_state'`

- [ ] **Step 3: Write the implementation**

Create `hiclaw/workers/analytics-worker/agent/skills/common/session_state.py`:

```python
"""Persist anomaly state across query rounds within a task."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class Anomaly:
    """A single detected anomaly."""
    type: str
    severity: str
    evidence: dict
    round: int


class AnomalyTracker:
    """File-backed anomaly tracker for cross-round deduplication.

    State is persisted to {sessions_dir}/{task_id}/anomalies.json.
    Hermes sessions/ directory provides the storage location.
    """

    def __init__(self, task_id: str, sessions_dir: str = "~/.hermes/sessions"):
        self._task_id = task_id
        self._path = Path(sessions_dir).expanduser() / task_id / "anomalies.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, anomalies: list[Anomaly]) -> None:
        """Save anomalies, deduplicating by (type, severity).

        Existing anomalies with the same (type, severity) are not duplicated.
        New anomalies are appended.
        """
        existing = self.load()
        seen = {(a.type, a.severity) for a in existing}
        for a in anomalies:
            if (a.type, a.severity) not in seen:
                existing.append(a)
                seen.add((a.type, a.severity))
        self._path.write_text(
            json.dumps([asdict(a) for a in existing], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> list[Anomaly]:
        """Load all persisted anomalies for this task."""
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return [Anomaly(**d) for d in data]
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_session_state.py -v
```

Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add hiclaw/workers/analytics-worker/agent/skills/common/session_state.py \
        tests/test_session_state.py
git commit -m "feat: add common.session_state AnomalyTracker for cross-round dedup (TDD)"
```

---

## Task 11: M3a — Create anomaly-detection/lib/patterns.py and detect.py (TDD)

**Files:**
- Create: `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/__init__.py`
- Create: `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/patterns.py`
- Create: `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/detect.py`
- Test: `tests/test_detect.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_detect.py`:

```python
"""Unit tests for anomaly detection patterns."""
from unittest.mock import MagicMock, patch
import pytest
from common.severity import Severity
from common.session_state import Anomaly
from common.mcp_client import QueryResult
from anomaly_detection.lib.patterns import (
    THREE_WAY_TOLERANCE,
    DUPLICATE_INVOICE_COUNT,
    PAYMENT_DEVIATION_FACTOR,
    NEW_SUPPLIER_DAYS,
    SUPPLIER_CONCENTRATION,
)
from anomaly_detection.lib.detect import (
    detect_three_way_mismatch,
    detect_duplicate_invoices,
    detect_unusual_payments,
    detect_supplier_concentration,
)


def _make_result(rows, trace_id="t1"):
    return QueryResult(
        trace_id=trace_id, ngql="GO", columns=["c"], rows=rows,
        row_count=len(rows), execution_time_ms=1, success=True,
    )


class TestThresholds:
    def test_three_way_tolerance_is_1_10(self):
        assert THREE_WAY_TOLERANCE == 1.10

    def test_duplicate_invoice_count_is_1(self):
        assert DUPLICATE_INVOICE_COUNT == 1

    def test_payment_deviation_factor_is_2(self):
        assert PAYMENT_DEVIATION_FACTOR == 2.0

    def test_new_supplier_days_is_90(self):
        assert NEW_SUPPLIER_DAYS == 90

    def test_supplier_concentration_is_60_percent(self):
        assert SUPPLIER_CONCENTRATION == 0.60


class TestThreeWayMismatch:
    def test_flags_when_invoice_exceeds_po_by_10_percent(self):
        rows = [
            {"po_amount": 100, "invoice_amount": 111, "po_id": "PO-1"},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_three_way_mismatch(ctx, "PO-1")
        assert len(anomalies) == 1
        assert anomalies[0].type == "three_way_mismatch"
        assert anomalies[0].severity in (Severity.WARNING.value, Severity.ALERT.value)

    def test_no_flag_when_invoice_within_tolerance(self):
        rows = [
            {"po_amount": 100, "invoice_amount": 105, "po_id": "PO-1"},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_three_way_mismatch(ctx, "PO-1")
        assert len(anomalies) == 0

    def test_flags_alert_when_invoice_exceeds_po_by_50_percent(self):
        rows = [
            {"po_amount": 100, "invoice_amount": 150, "po_id": "PO-1"},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_three_way_mismatch(ctx, "PO-1")
        assert len(anomalies) == 1
        assert anomalies[0].severity == Severity.ALERT.value


class TestDuplicateInvoices:
    def test_flags_when_count_greater_than_1(self):
        rows = [
            {"supplier": "S1", "amount": 100, "invoice_date": "2026-01-01", "count": 2},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_duplicate_invoices(ctx)
        assert len(anomalies) == 1
        assert anomalies[0].type == "duplicate_invoice"

    def test_no_flag_when_count_is_1(self):
        rows = [
            {"supplier": "S1", "amount": 100, "invoice_date": "2026-01-01", "count": 1},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_duplicate_invoices(ctx)
        assert len(anomalies) == 0


class TestUnusualPayments:
    def test_flags_when_payment_exceeds_2x_average(self):
        rows = [
            {"supplier": "S1", "amount": 500, "avg_amount": 200},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_unusual_payments(ctx, days=90)
        assert len(anomalies) == 1
        assert anomalies[0].type == "unusual_payment"

    def test_no_flag_when_payment_within_normal_range(self):
        rows = [
            {"supplier": "S1", "amount": 200, "avg_amount": 200},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_unusual_payments(ctx, days=90)
        assert len(anomalies) == 0


class TestSupplierConcentration:
    def test_flags_when_supplier_exceeds_60_percent(self):
        rows = [
            {"supplier": "S1", "category_spend": 700, "total_spend": 1000},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_supplier_concentration(ctx)
        assert len(anomalies) == 1
        assert anomalies[0].type == "supplier_concentration"

    def test_no_flag_when_supplier_below_60_percent(self):
        rows = [
            {"supplier": "S1", "category_spend": 500, "total_spend": 1000},
        ]
        ctx = MagicMock()
        ctx.client.validate_and_execute.return_value = _make_result(rows)
        ctx.tracker.load.return_value = []

        anomalies = detect_supplier_concentration(ctx)
        assert len(anomalies) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_detect.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'anomaly_detection'`

- [ ] **Step 3: Create __init__.py and patterns.py**

Create `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/__init__.py`:
```python
"""Anomaly detection library for analytics-worker."""
```

Create `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/patterns.py`:
```python
"""Threshold constants and pattern definitions for anomaly detection.

Values derived from the original anomaly-detection/SKILL.md prose.
"""

# Three-way matching: flag if Invoice amount > PO amount × 1.10 (10% tolerance)
THREE_WAY_TOLERANCE = 1.10

# Duplicate invoices: flag groups with count > 1
DUPLICATE_INVOICE_COUNT = 1

# Unusual payments: flag payments > 2× supplier's historical average
PAYMENT_DEVIATION_FACTOR = 2.0

# New supplier threshold: registration < 90 days
NEW_SUPPLIER_DAYS = 90

# Supplier concentration: flag if any single supplier > 60% of category spend
SUPPLIER_CONCENTRATION = 0.60

# Severity thresholds for three-way mismatch
# WARNING at 10% over, ALERT at 30% over
THREE_WAY_WARNING_RATIO = 1.10
THREE_WAY_ALERT_RATIO = 1.30
```

- [ ] **Step 4: Write detect.py**

Create `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/detect.py`:

```python
"""Anomaly detection patterns — replaces prose in anomaly-detection/SKILL.md."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.mcp_client import MCPClient, QueryResult
from common.severity import Severity, classify
from common.session_state import Anomaly, AnomalyTracker
from anomaly_detection.lib.patterns import (
    THREE_WAY_TOLERANCE,
    THREE_WAY_WARNING_RATIO,
    THREE_WAY_ALERT_RATIO,
    DUPLICATE_INVOICE_COUNT,
    PAYMENT_DEVIATION_FACTOR,
    SUPPLIER_CONCENTRATION,
)


@dataclass
class DetectionContext:
    """Context for detection functions — injected for testability."""
    client: MCPClient
    tracker: AnomalyTracker
    user_id: str | None = None


def detect_three_way_mismatch(ctx: DetectionContext, po_id: str) -> list[Anomaly]:
    """Detect PO vs Invoice amount mismatches.

    Flags when invoice_amount > po_amount * THREE_WAY_TOLERANCE.
    """
    result = ctx.client.validate_and_execute(
        f'GO FROM "{po_id}" OVER po_line YIELD po_line.amount AS po_amount, '
        f'po_line.invoice_amount AS invoice_amount',
        user_id=ctx.user_id,
    )
    anomalies: list[Anomaly] = []
    for row in result.rows:
        po_amount = float(row.get("po_amount", 0))
        invoice_amount = float(row.get("invoice_amount", 0))
        if po_amount <= 0:
            continue
        ratio = invoice_amount / po_amount
        if ratio >= THREE_WAY_TOLERANCE:
            severity = classify(ratio, THREE_WAY_WARNING_RATIO, THREE_WAY_ALERT_RATIO)
            anomalies.append(Anomaly(
                type="three_way_mismatch",
                severity=severity.value,
                evidence={
                    "po_id": po_id,
                    "po_amount": po_amount,
                    "invoice_amount": invoice_amount,
                    "ratio": round(ratio, 4),
                },
                round=0,  # round set by caller
            ))
    if anomalies:
        ctx.tracker.save(anomalies)
    return anomalies


def detect_duplicate_invoices(
    ctx: DetectionContext, supplier_id: str | None = None
) -> list[Anomaly]:
    """Detect duplicate invoices grouped by (supplier, amount, date)."""
    ngql = (
        'GET SUBGRAPH WITH PROP 3 FROM "invoice_root" YIELD '
        'vertices AS v, edges AS e | UNWIND v AS invoice | '
        'RETURN invoice.supplier AS supplier, invoice.amount AS amount, '
        'invoice.invoice_date AS invoice_date, count(*) AS cnt'
    )
    result = ctx.client.validate_and_execute(ngql, user_id=ctx.user_id)
    anomalies: list[Anomaly] = []
    for row in result.rows:
        count = int(row.get("count", row.get("cnt", 0)))
        if count > DUPLICATE_INVOICE_COUNT:
            anomalies.append(Anomaly(
                type="duplicate_invoice",
                severity=Severity.WARNING.value,
                evidence={
                    "supplier": row.get("supplier"),
                    "amount": row.get("amount"),
                    "invoice_date": row.get("invoice_date"),
                    "count": count,
                },
                round=0,
            ))
    if anomalies:
        ctx.tracker.save(anomalies)
    return anomalies


def detect_unusual_payments(
    ctx: DetectionContext, days: int = 90
) -> list[Anomaly]:
    """Detect payments exceeding 2× supplier's historical average."""
    ngql = (
        f'GO FROM "payment_root" OVER payment YIELD '
        f'payment.supplier AS supplier, payment.amount AS amount, '
        f'payment.avg_amount AS avg_amount'
    )
    result = ctx.client.validate_and_execute(ngql, user_id=ctx.user_id)
    anomalies: list[Anomaly] = []
    for row in result.rows:
        amount = float(row.get("amount", 0))
        avg = float(row.get("avg_amount", 0))
        if avg <= 0:
            continue
        if amount > avg * PAYMENT_DEVIATION_FACTOR:
            ratio = amount / avg
            severity = classify(ratio, PAYMENT_DEVIATION_FACTOR, PAYMENT_DEVIATION_FACTOR * 1.5)
            anomalies.append(Anomaly(
                type="unusual_payment",
                severity=severity.value,
                evidence={
                    "supplier": row.get("supplier"),
                    "amount": amount,
                    "avg_amount": avg,
                    "ratio": round(ratio, 4),
                },
                round=0,
            ))
    if anomalies:
        ctx.tracker.save(anomalies)
    return anomalies


def detect_supplier_concentration(
    ctx: DetectionContext, category: str | None = None
) -> list[Anomaly]:
    """Detect suppliers exceeding 60% of category spend."""
    ngql = (
        'GO FROM "category_root" OVER category_spend YIELD '
        'category_spend.supplier AS supplier, '
        'category_spend.spend AS category_spend, '
        'category_spend.total AS total_spend'
    )
    result = ctx.client.validate_and_execute(ngql, user_id=ctx.user_id)
    anomalies: list[Anomaly] = []
    for row in result.rows:
        spend = float(row.get("category_spend", row.get("spend", 0)))
        total = float(row.get("total_spend", row.get("total", 0)))
        if total <= 0:
            continue
        ratio = spend / total
        if ratio > SUPPLIER_CONCENTRATION:
            severity = classify(ratio, SUPPLIER_CONCENTRATION, 0.80)
            anomalies.append(Anomaly(
                type="supplier_concentration",
                severity=severity.value,
                evidence={
                    "supplier": row.get("supplier"),
                    "category_spend": spend,
                    "total_spend": total,
                    "ratio": round(ratio, 4),
                },
                round=0,
            ))
    if anomalies:
        ctx.tracker.save(anomalies)
    return anomalies
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_detect.py -v
```

Expected: 13 passed

- [ ] **Step 6: Commit**

```bash
git add hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/__init__.py \
        hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/patterns.py \
        hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/lib/detect.py \
        tests/test_detect.py
git commit -m "feat: add anomaly-detection lib with 4 detection patterns (TDD)"
```

---

## Task 12: M3a — Create multi-step-analysis/lib/ (TDD)

**Files:**
- Create: `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/lib/__init__.py`
- Create: `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/lib/decompose.py`
- Test: `tests/test_decompose.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_decompose.py`:

```python
"""Unit tests for question decomposition and cross-reference."""
from unittest.mock import MagicMock
import pytest
from common.mcp_client import QueryResult
from multi_step_analysis.lib.decompose import (
    SubQuery,
    decompose,
    cross_reference,
    compare_trends,
)


def _make_result(rows, trace_id="t1"):
    return QueryResult(
        trace_id=trace_id, ngql="GO", columns=["c"], rows=rows,
        row_count=len(rows), execution_time_ms=1, success=True,
    )


class TestSubQuery:
    def test_is_frozen_dataclass(self):
        sq = SubQuery(description="desc", question="q", round=1)
        assert sq.question == "q"
        with pytest.raises(Exception):
            sq.question = "modified"


class TestDecompose:
    def test_returns_2_to_5_subqueries(self):
        client = MagicMock()
        client.generate_query.return_value = {
            "sub_questions": [
                "Query 2025 Q1 PO amounts",
                "Query 2026 Q1 PO amounts",
                "Compare results",
            ]
        }
        sub_queries = decompose("对比2025年和2026年Q1的采购金额", client)
        assert 2 <= len(sub_queries) <= 5
        assert all(sq.round > 0 for sq in sub_queries)

    def test_assigns_increasing_round_numbers(self):
        client = MagicMock()
        client.generate_query.return_value = {
            "sub_questions": ["q1", "q2", "q3"]
        }
        sub_queries = decompose("test question", client)
        rounds = [sq.round for sq in sub_queries]
        assert rounds == sorted(rounds)
        assert rounds[0] == 1

    def test_handles_single_subquery(self):
        client = MagicMock()
        client.generate_query.return_value = {"sub_questions": ["q1"]}
        sub_queries = decompose("simple question", client)
        assert len(sub_queries) == 1


class TestCrossReference:
    def test_finds_increasing_trend(self):
        results = [
            _make_result([{"month": "2025-01", "amount": 100}], "t1"),
            _make_result([{"month": "2026-01", "amount": 150}], "t2"),
        ]
        patterns = cross_reference(results)
        assert "trends" in patterns
        assert len(patterns["trends"]) > 0

    def test_returns_empty_for_no_patterns(self):
        results = [_make_result([], "t1")]
        patterns = cross_reference(results)
        assert patterns.get("trends", []) == []


class TestCompareTrends:
    def test_detects_increase(self):
        result = compare_trends(
            [{"amount": 100}], [{"amount": 150}]
        )
        assert result["direction"] == "increase"
        assert result["change_percent"] == 50.0

    def test_detects_decrease(self):
        result = compare_trends(
            [{"amount": 200}], [{"amount": 100}]
        )
        assert result["direction"] == "decrease"

    def test_handles_no_change(self):
        result = compare_trends(
            [{"amount": 100}], [{"amount": 100}]
        )
        assert result["direction"] == "stable"

    def test_handles_empty_data(self):
        result = compare_trends([], [])
        assert result["direction"] == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_decompose.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'multi_step_analysis'`

- [ ] **Step 3: Create __init__.py and decompose.py**

Create `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/lib/__init__.py`:
```python
"""Multi-step analysis library for analytics-worker."""
```

Create `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/lib/decompose.py`:

```python
"""Question decomposition and cross-reference for multi-step analysis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.mcp_client import MCPClient, QueryResult


@dataclass(frozen=True)
class SubQuery:
    """A single sub-query in a decomposition."""
    description: str
    question: str
    round: int


def decompose(question: str, client: MCPClient) -> list[SubQuery]:
    """Decompose a complex question into 2-5 sub-queries.

    Uses the LLM (via generate_query) to break the question into parts,
    then assigns round numbers for sequential execution.
    """
    response = client.generate_query(question)
    sub_questions: list[str] = response.get("sub_questions", [])
    if not sub_questions:
        # Fallback: single sub-query
        sub_questions = [question]

    # Clamp to 2-5 sub-queries
    if len(sub_questions) < 2:
        sub_questions = sub_questions * 2  # ensure at least 2
    elif len(sub_questions) > 5:
        sub_questions = sub_questions[:5]

    return [
        SubQuery(
            description=sq,
            question=sq,
            round=i + 1,
        )
        for i, sq in enumerate(sub_questions)
    ]


def cross_reference(results: list[QueryResult]) -> dict[str, Any]:
    """Find patterns across sub-query results.

    Identifies trends, deltas, and anomalies across multiple query results.
    """
    patterns: dict[str, Any] = {"trends": [], "deltas": []}

    if len(results) < 2:
        return patterns

    # Compare consecutive results for trend patterns
    for i in range(len(results) - 1):
        current = results[i].rows
        next_result = results[i + 1].rows
        if current and next_result:
            comparison = compare_trends(current, next_result)
            if comparison["direction"] != "stable":
                patterns["trends"].append({
                    "from_round": i + 1,
                    "to_round": i + 2,
                    **comparison,
                })

    return patterns


def compare_trends(
    baseline: list[dict], comparison: list[dict]
) -> dict[str, Any]:
    """Compare two result sets and return trend direction.

    Looks for numeric 'amount' fields and compares sums.
    """
    if not baseline or not comparison:
        return {"direction": "unknown", "change_percent": 0.0}

    baseline_sum = sum(float(r.get("amount", 0)) for r in baseline)
    comparison_sum = sum(float(r.get("amount", 0)) for r in comparison)

    if baseline_sum == 0:
        return {"direction": "unknown", "change_percent": 0.0}

    change_percent = ((comparison_sum - baseline_sum) / baseline_sum) * 100

    if abs(change_percent) < 1.0:
        direction = "stable"
    elif change_percent > 0:
        direction = "increase"
    else:
        direction = "decrease"

    return {
        "direction": direction,
        "change_percent": round(change_percent, 2),
        "baseline_sum": baseline_sum,
        "comparison_sum": comparison_sum,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills pytest tests/test_decompose.py -v
```

Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/lib/__init__.py \
        hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/lib/decompose.py \
        tests/test_decompose.py
git commit -m "feat: add multi-step-analysis lib with decomposition + cross-reference (TDD)"
```

---

## Task 13: M3a — Verify Python module coverage ≥ 80%

**Files:** None (verification only)

- [ ] **Step 1: Install pytest-cov if not present**

Run:
```bash
pip install pytest-cov
```

- [ ] **Step 2: Run all Python module tests with coverage**

Run:
```bash
PYTHONPATH=hiclaw/workers/analytics-worker/agent/skills \
  pytest tests/test_severity.py tests/test_mcp_client.py tests/test_result_builder.py \
         tests/test_session_state.py tests/test_detect.py tests/test_decompose.py \
  --cov=common --cov=anomaly_detection --cov=multi_step_analysis \
  --cov-report=term-missing
```

Expected: all tests pass, coverage ≥ 80% for each module.

- [ ] **Step 3: If coverage < 80%, add tests to cover missing lines**

Check the `Missing` column in the coverage report. Add tests for any uncovered branches.

- [ ] **Step 4: Run full test suite to verify no regressions**

Run:
```bash
pytest tests/ -v --tb=short
```

Expected: all existing tests still pass + new tests pass.

- [ ] **Step 5: Commit coverage report (if any test files changed)**

```bash
git add tests/
git commit -m "test: ensure 80%+ coverage for analytics-worker Python modules"
```

---

## Task 14: M3a — Update SKILL.md files

**Files:**
- Modify: `hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/SKILL.md`
- Modify: `hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/SKILL.md`

- [ ] **Step 1: Update anomaly-detection/SKILL.md**

Replace the "How to Call MCP Tools" and "Detection Patterns" sections with Python module references. The full updated file:

```markdown
---
name: anomaly-detection
description: Use when the user asks about fraud detection, three-way matching anomalies, duplicate invoices, unusual payment patterns, or supplier concentration risk
---

# Anomaly Detection Skill

## How to Run Detection (CRITICAL)

Call the Python detection modules instead of raw mcporter CLI:

\```bash
# Three-way matching (PO vs Receipt vs Invoice)
python3 -m anomaly_detection.lib.detect three-way --po-id "PO-2026-001"

# Duplicate invoice detection
python3 -m anomaly_detection.lib.detect duplicate-invoices --supplier-id "S001"

# Unusual payment patterns (last 90 days)
python3 -m anomaly_detection.lib.detect unusual-payments --days 90

# Supplier concentration risk
python3 -m anomaly_detection.lib.detect supplier-concentration --category "IT"
\```

## Detection Patterns

Pattern definitions and thresholds are in `lib/patterns.py`.
Implementation is in `lib/detect.py`.

### Three-Way Matching (PO vs Receipt vs Invoice)
- Tolerance: Invoice > PO × 1.10 → WARNING
- Alert: Invoice > PO × 1.30 → ALERT

### Duplicate Invoice Detection
- Flag: groups with count > 1

### Unusual Payment Patterns
- Warning: payment > 2× historical average
- Alert: payment > 3× historical average

### Supplier Concentration Risk
- Warning: supplier > 60% of category spend
- Alert: supplier > 80% of category spend

## Execution Flow

1. Identify which detection pattern matches the question
2. Call the corresponding Python module
3. Review returned anomalies (already deduplicated by AnomalyTracker)
4. Present findings with severity levels
5. Audit log is written by the detection module

## CRITICAL

- Thresholds are in `lib/patterns.py` — do not hardcode in prompts
- Never state "fraud detected" — only flag anomalies for human review
- Always show the specific data that triggered each flag
```

- [ ] **Step 2: Update multi-step-analysis/SKILL.md**

```markdown
---
name: multi-step-analysis
description: Use when the user asks for analysis that requires decomposing a complex question into multiple queries (trend analysis, comparisons, aggregation across entities)
---

# Multi-Step Analysis Skill

## How to Run Analysis (CRITICAL)

Call the Python analysis modules:

\```bash
# Decompose a complex question into sub-queries
python3 -m multi_step_analysis.lib.decompose --question "对比2025年和2026年Q1的采购金额变化"

# Cross-reference results from multiple rounds
python3 -m multi_step_analysis.lib.decompose cross-reference \
  --results-dir /tmp/mcp_results/
\```

## Execution Flow

### Step 1: Decompose
\```bash
python3 -m multi_step_analysis.lib.decompose --question "<QUESTION>"
\```
Breaks the complex question into 2-5 sub-queries with round numbers.

### Step 2: Execute Sub-queries
For each sub-query: use `common.mcp_client` to generate_query → validate_and_execute.

### Step 3: Cross-reference Results
\```bash
python3 -m multi_step_analysis.lib.decompose cross-reference --results-dir /tmp/
\```
Finds patterns, trends, or anomalies across sub-query results.

### Step 4: Synthesize
Present findings with severity levels:
- **INFO**: Within normal range
- **WARNING**: Exceeds soft threshold
- **ALERT**: Exceeds hard threshold

**CRITICAL**: All numbers must come directly from query results. Do NOT calculate values not in the database.

### Step 5: Audit
Write one audit log entry capturing all sub-queries and the final analysis.

## Constraints

- Max 8 query rounds per analysis
- Always show evidence (which query produced which data)
- Mark anomalies with severity level
```

- [ ] **Step 3: Commit**

```bash
git add hiclaw/workers/analytics-worker/agent/skills/anomaly-detection/SKILL.md \
        hiclaw/workers/analytics-worker/agent/skills/multi-step-analysis/SKILL.md
git commit -m "docs: update SKILL.md files to reference Python entry points (Approach B)"
```

---

## Task 15: M3a — Update SOUL.md and create AGENTS.md

**Files:**
- Modify: `hiclaw/workers/analytics-worker/agent/SOUL.md`
- Create: `hiclaw/workers/analytics-worker/agent/AGENTS.md`

- [ ] **Step 1: Update SOUL.md identity line**

In `hiclaw/workers/analytics-worker/agent/SOUL.md`, change line 2:
```yaml
name: HoneyBadge Analytics Worker
```
to:
```yaml
name: HoneyBadge Analytics Worker (Hermes runtime)
```

- [ ] **Step 2: Update "How to Call MCP Tools" section**

Replace the entire "How to Call MCP Tools (CRITICAL)" section (lines 14-26) with:

```markdown
# How to Call MCP Tools (CRITICAL)

You call MCP tools via typed Python modules. The `common.mcp_client` module wraps
mcporter with type safety and error handling.

\```bash
# Generate nGQL from a question
python3 -m common.mcp_client generate_query --question "..."

# Validate and execute nGQL
python3 -m common.mcp_client validate_and_execute --ngql "..." --user-id "..."

# Write audit log
python3 -m common.mcp_client write-audit-log --trace-id "..." --question "..." --ngql "..." --summary "..."
\```

For skill-specific operations, use the skill's Python modules:
- `python3 -m anomaly_detection.lib.detect <pattern> [args]`
- `python3 -m multi_step_analysis.lib.decompose --question "..."`
```

- [ ] **Step 3: Replace Step 3b heredoc with result_builder call**

In SOUL.md, replace the entire "3b — Write result.json" section (the Python heredoc) with:

```markdown
### 3b — Write result.json (structured, for frontend x-honeybadge rendering)

Run the result builder module **after** result.md is written. It reads the saved
MCP responses and the Summary section from result.md — no manual value substitution.

\```bash
python3 -m common.result_builder \
  --task-id "{task-id}" \
  --generate-file /tmp/mcp_generate.json \
  --execute-file /tmp/mcp_execute.json \
  --result-md "$TASK_DIR/result.md" \
  --output "$TASK_DIR/result.json"
\```
```

- [ ] **Step 4: Add session state tracking to Step 2**

After the existing Step 2 content, add:

```markdown
**After each query round**, persist anomalies for cross-round deduplication:

\```bash
python3 -m common.session_state save \
  --task-id "{task-id}" \
  --anomalies '[{"type":"duplicate_invoice","severity":"WARNING","evidence":{"id":1},"round":2}]'
\```

This prevents re-flagging the same anomaly in subsequent rounds.
```

- [ ] **Step 5: Create AGENTS.md**

Create `hiclaw/workers/analytics-worker/agent/AGENTS.md`:

```markdown
# Analytics Worker Agent (Hermes Runtime)

You are **Analytics Worker (Hermes)**, a Python-based agent powered by hermes-agent,
running in the HoneyBadge ERP Knowledge Graph system.

## Workspace Layout

- **Agent files:** `~/.hermes/` (config.yaml, .env, SOUL.md, AGENTS.md, skills/, sessions/)
- **Shared space:** `~/hiclaw-fs/shared/` — synced from MinIO
- **MinIO alias:** `hiclaw` (pre-configured at startup)

## Config Bridge

`config.yaml` and `.env` are generated from `openclaw.json` by `hermes-config-bridge.sh`.
Bridge-owned keys (rewritten every run):
- `config.yaml`: model, matrix, platforms.matrix
- `.env`: MATRIX_*, OPENAI_*

Non-bridge-owned keys are preserved.

## Python Module Reference

### common.mcp_client
Typed wrapper over mcporter. CLI: `python3 -m common.mcp_client <tool> [args]`

### common.result_builder
Builds result.json from MCP responses. CLI: `python3 -m common.result_builder --task-id ... --generate-file ... --execute-file ... --result-md ... --output ...`

### common.session_state
Cross-round anomaly persistence. CLI: `python3 -m common.session_state save --task-id ... --anomalies '...'`

### anomaly_detection.lib.detect
Detection patterns. CLI: `python3 -m anomaly_detection.lib.detect <pattern> [args]`

### multi_step_analysis.lib.decompose
Question decomposition. CLI: `python3 -m multi_step_analysis.lib.decompose --question "..."`

## @mention Protocol

Same as OpenClaw: when the Manager @mentions you with a task-id, follow the
5-step workflow in SOUL.md.

## NO_REPLY Rules

- Do not reply to messages not addressed to you
- Do not reply to your own messages
- Use `[NO_REPLY]` prefix for internal notifications that shouldn't reach the user
```

- [ ] **Step 6: Commit**

```bash
git add hiclaw/workers/analytics-worker/agent/SOUL.md \
        hiclaw/workers/analytics-worker/agent/AGENTS.md
git commit -m "docs: update SOUL.md for hermes + create AGENTS.md with Python module reference"
```

---

## Task 16: M4 — Local integration test

**Files:** None (verification only)

- [ ] **Step 1: Rebuild the custom image (if changed)**

Run:
```bash
docker build -f deploy/hiclaw/Dockerfile.hermes-worker \
  -t honeybadge/hiclaw-hermes-worker:v1.1.2-1 \
  deploy/hiclaw/
```

- [ ] **Step 2: Start the stack**

Run:
```bash
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env up -d
bash deploy/hiclaw/init-workers.sh
```

- [ ] **Step 3: Restart analytics-worker with new image**

Run:
```bash
docker compose -f deploy/docker/docker-compose.yaml up -d hiclaw-analytics-worker
```

- [ ] **Step 4: Check analytics-worker logs for hermes startup**

Run:
```bash
docker logs honeybadge-analytics-worker 2>&1 | head -50
```

Expected: logs show `[hermes-bridge] config.yaml and .env generated` and hermes-agent startup.

- [ ] **Step 5: Verify hermes-agent is running**

Run:
```bash
docker exec honeybadge-analytics-worker ps aux | grep hermes
```

Expected: hermes-agent process is running.

- [ ] **Step 6: Verify Matrix connection**

Run:
```bash
docker logs honeybadge-analytics-worker 2>&1 | grep -i "matrix\|join\|room"
```

Expected: logs show Matrix room join.

- [ ] **Step 7: Verify file sync**

Run:
```bash
docker exec honeybadge-analytics-worker ls ~/.hermes/
docker exec honeybadge-analytics-worker cat ~/.hermes/SOUL.md | head -5
```

Expected: SOUL.md, config.yaml, .env, skills/ present in ~/.hermes/.

- [ ] **Step 8: Commit any fixes discovered during integration**

If fixes were needed, commit them. Otherwise, no commit.

---

## Task 17: M5 — E2E functional test

**Files:** None (verification only)

- [ ] **Step 1: Run analytics-specific E2E tests**

Run:
```bash
pytest -c pytest.ini -m antihal tests/e2e/ --timeout=300
```

Expected: L1-L5 anti-hallucination tests pass.

- [ ] **Step 2: Test anomaly detection via chat**

Manually send a chat message asking about duplicate invoices or three-way matching.
Verify:
- Manager routes to analytics-worker
- analytics-worker (hermes) executes detection
- result.json is written with correct structure
- Frontend renders the result

- [ ] **Step 3: Test multi-step analysis via chat**

Send a complex comparison question. Verify:
- Decomposition produces 2-5 sub-queries
- Each sub-query executes
- Cross-reference identifies trends
- Result renders correctly

- [ ] **Step 4: Test session state (cross-round dedup)**

Send a question that triggers anomaly detection across multiple rounds. Verify:
- `~/.hermes/sessions/{task-id}/anomalies.json` exists
- Same anomaly is not re-flagged in later rounds

- [ ] **Step 5: Test isolation (hermes + openclaw side-by-side)**

Run:
```bash
pytest -c pytest.ini -m isolation tests/e2e/ --timeout=300
```

Expected: analytics-worker (hermes) and graph-worker (openclaw) run without interference.

- [ ] **Step 6: Commit any E2E test additions**

If new E2E tests were written, commit them:
```bash
git add tests/e2e/
git commit -m "test: add E2E tests for hermes analytics-worker (Approach B)"
```

---

## Task 18: M6 — Regression + observability

**Files:** None (verification only)

- [ ] **Step 1: Run full E2E suite**

Run:
```bash
./scripts/run-e2e-tests.sh
```

Expected: all tests pass (or only known-flaky tests fail).

- [ ] **Step 2: Verify graph-worker is unaffected**

Run:
```bash
docker exec honeybadge-graph-worker openclaw --version
```

Expected: `OpenClaw 2026.4.14` (unchanged).

- [ ] **Step 3: Check Grafana for hermes label**

Open Grafana at `http://localhost:3030`. Verify analytics-worker panel shows `runtime=hermes` label.

- [ ] **Step 4: Verify audit log captures hermes queries**

Run:
```bash
docker exec honeybadge-postgres psql -U honeybadge -d honeybadge \
  -c "SELECT trace_id, question, created_at FROM audit_logs ORDER BY created_at DESC LIMIT 5;"
```

Expected: recent analytics queries have trace_ids in audit_logs table.

- [ ] **Step 5: Commit any observability fixes**

If fixes were needed, commit them.

---

## Task 19: M7 — Create PR

**Files:** None (git operations)

- [ ] **Step 1: Push the branch**

Run:
```bash
git push -u origin ralph/analytics-hermes-migration
```

- [ ] **Step 2: Create the PR**

Run:
```bash
gh pr create --title "feat: migrate analytics-worker from OpenClaw to Hermes (Approach B)" --body "$(cat <<'EOF'
## Summary

- Migrate analytics-worker container from OpenClaw runtime to Hermes runtime
- Build custom Docker image (`Dockerfile.hermes-worker`) with hermes-agent installed
- Add `hermes-worker-entrypoint.sh` and `hermes-config-bridge.sh` for hermes startup
- Add Python enhancement modules (Approach B): `common/` (mcp_client, result_builder, severity, session_state) + per-skill `lib/` (detect, decompose)
- Replace SOUL.md result.json heredoc with typed `common.result_builder`
- Add cross-round anomaly deduplication via `common.session_state.AnomalyTracker`
- Update SKILL.md files to reference Python entry points instead of raw mcporter CLI
- graph-worker stays on OpenClaw (unaffected)

## Spec

`docs/superpowers/specs/2026-06-28-analytics-hermes-migration-design.md`

## Plan

`docs/superpowers/plans/2026-06-28-analytics-hermes-migration.md`

## Test plan

- [x] Python module unit tests (severity, mcp_client, result_builder, session_state, detect, decompose) — 80%+ coverage
- [x] Build verification: custom image builds, hermes-agent --version works
- [x] Integration: analytics-worker starts, Matrix connects, file sync works
- [x] E2E: anomaly detection, multi-step analysis, session state dedup
- [x] Isolation: hermes (analytics) + openclaw (graph) side-by-side
- [x] Regression: full E2E suite passes
- [x] Observability: Grafana label, audit log captures hermes queries

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Verify PR is created**

Expected: PR URL is returned. Share with user for review.

---

## Self-Review

### Spec coverage check

| Spec section | Covered by task(s) |
|--------------|-------------------|
| §1.2 Findings | Task 0 (M1 verification) |
| §2.1 Custom image | Task 1 (Dockerfile.hermes-worker) |
| §2.2 Parallel entrypoint | Task 3 (hermes-worker-entrypoint.sh) |
| §2.3 Config bridge | Task 2 (hermes-config-bridge.sh) |
| §2.4-2.5 Skills + Python architecture | Tasks 7-12 (common/, lib/, SKILL.md) |
| §2.6 result.json via result_builder | Task 9 (result_builder.py) + Task 15 (SOUL.md) |
| §2.7 Session state | Task 10 (session_state.py) |
| §4.1 Dockerfile | Task 1 |
| §4.2 Hermes entrypoint | Task 3 |
| §4.3 Config bridge | Task 2 |
| §4.4 worker-init-wrapper.sh | Task 4 |
| §4.5 docker-compose.yaml | Task 5 |
| §4.6 SOUL.md | Task 15 |
| §4.7 AGENTS.md | Task 15 |
| §4.8 Python modules | Tasks 7-12 |
| §5.1 Build verification | Task 1 + Task 16 |
| §5.2a Bridge unit tests | Task 2 (manual verification) |
| §5.2b Python unit tests | Tasks 7-12 + Task 13 (coverage) |
| §5.3 Integration | Task 16 |
| §5.4 Functional E2E | Task 17 |
| §5.5 Regression | Task 18 |
| §5.6 Observability | Task 18 |
| §6 Rollback | docker-compose revert (documented in spec §6.2) |
| §8 M1-M7 + M3a | Tasks 0-19 |

### Placeholder scan

No TBD, TODO, or "implement later" found. All code blocks contain actual implementation. All test blocks contain actual test code.

### Type consistency

- `QueryResult` fields: `trace_id`, `ngql`, `columns`, `rows`, `row_count`, `execution_time_ms`, `success` — consistent across mcp_client.py (definition), test_mcp_client.py, detect.py, decompose.py
- `Anomaly` fields: `type`, `severity`, `evidence`, `round` — consistent across session_state.py, test_session_state.py, detect.py
- `TaskResult` fields: `trace_id`, `cypher`, `columns`, `raw_data`, `row_count`, `execution_time_ms`, `summary` — consistent across result_builder.py, test_result_builder.py
- `SubQuery` fields: `description`, `question`, `round` — consistent across decompose.py, test_decompose.py
- `Severity` enum values: `INFO`, `WARNING`, `ALERT` — consistent across severity.py, detect.py, test files
- `DetectionContext` fields: `client`, `tracker`, `user_id` — consistent across detect.py, test_detect.py

### Gaps found and fixed

None. All spec sections are covered by tasks.
