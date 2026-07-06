#!/bin/bash
# HoneyBadge Worker Initialization Script
#
# The Manager container auto-runs manager-init-internal.sh on every startup
# via entrypoint-wrapper.sh. That script:
#   - Creates the hiclaw-storage MinIO bucket
#   - Registers workers on Matrix (generate-worker-config.sh, NOT the
#     removed create-worker.sh)
#   - Generates openclaw.json for each worker and uploads to MinIO
#   - Patches worker LLM baseUrl/model and Manager allowlist
#
# This script waits for the auto-init to complete, then applies fallback
# patches and MCP registration that the auto-init may not cover:
#   1. Ensures the MinIO bucket exists (safety net for race conditions)
#   2. Waits for the "HoneyBadge auto-init complete!" marker
#   3. Verifies worker openclaw.json exists in MinIO
#   4. Patches Manager allowlist for @hb-* users (Approach B)
#   5. Ensures Higress LLM route (Higress mode only; skipped in nginx-bypass)
#   6. Registers MCP servers in workers + Manager via mcporter
#
# Usage:
#   cd deploy/docker && docker compose up -d
#   bash ../../deploy/hiclaw/init-workers.sh
#
# Check auto-init log:
#   docker exec honeybadge-hiclaw-manager cat /var/log/hiclaw/honeybadge-init.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# On Windows (Git Bash/MSYS2), convert to Windows-style path for Docker compatibility.
# Docker for Windows cannot resolve Unix-style paths like /d/dev/HoneyBadge.
if command -v cygpath &>/dev/null; then
    PROJECT_ROOT="$(cygpath -m "$PROJECT_ROOT")"
    TMP_DIR="$(cygpath -m /tmp)"
else
    TMP_DIR="/tmp"
fi

# Source .env for LLM_API_KEY and other config (if not already in environment)
ENV_FILE="$PROJECT_ROOT/deploy/docker/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# Manager + Workers MUST use a tool-calling-capable model (glm-5.2).
# glm-4-flash cannot call skills (fast-query.sh) properly.
# Do NOT fall back to LLM_MODEL here — LLM_MODEL may be glm-4-flash (for
# MCP servers' nGQL generation only), which would break the Manager.
MANAGER_LLM_MODEL="${MANAGER_LLM_MODEL:-glm-5.2}"

MANAGER_CONTAINER="${MANAGER_CONTAINER:-honeybadge-hiclaw-manager}"
# v1.1.0 split: MinIO/Higress/Tuwunel now run in hiclaw-embedded.
# mc operations and Higress health checks target EMBEDDED_CONTAINER;
# manager-workspace file edits and Python patches stay in MANAGER_CONTAINER.
EMBEDDED_CONTAINER="${EMBEDDED_CONTAINER:-honeybadge-hiclaw-embedded}"
REG_TOKEN="${HICLAW_REGISTRATION_TOKEN:-honeybadge-reg-token}"
MATRIX_DOMAIN="${HICLAW_MATRIX_DOMAIN:-matrix-local.hiclaw.io}"

# ANSI colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[init]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
die()  { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Verify Manager container is running and healthy
# ---------------------------------------------------------------------------
log "Checking HiClaw Manager container..."
if ! docker inspect "$MANAGER_CONTAINER" &>/dev/null; then
    die "Container '$MANAGER_CONTAINER' not found. Run 'docker compose up -d' first."
fi

STATUS=$(docker inspect --format='{{.State.Status}}' "$MANAGER_CONTAINER")
if [ "$STATUS" != "running" ]; then
    die "Container '$MANAGER_CONTAINER' is not running (status: $STATUS)."
fi

# v1.1.0 split: verify hiclaw-embedded is also running (MinIO/Higress live there)
log "Checking HiClaw Embedded container..."
if ! docker inspect "$EMBEDDED_CONTAINER" &>/dev/null; then
    die "Container '$EMBEDDED_CONTAINER' not found. Run 'docker compose up -d' first."
fi

EMBEDDED_STATUS=$(docker inspect --format='{{.State.Status}}' "$EMBEDDED_CONTAINER")
if [ "$EMBEDDED_STATUS" != "running" ]; then
    die "Container '$EMBEDDED_CONTAINER' is not running (status: $EMBEDDED_STATUS)."
fi

log "Waiting for MinIO to be ready inside Embedded..."
RETRIES=20
until docker exec "$MANAGER_CONTAINER" curl -sf http://hiclaw-embedded:9000/minio/health/live &>/dev/null; do
    RETRIES=$((RETRIES - 1))
    if [ "$RETRIES" -eq 0 ]; then
        die "MinIO is not ready after waiting. Check: docker logs $EMBEDDED_CONTAINER"
    fi
    echo -n "."
    sleep 5
done
echo ""
log "MinIO is ready."

# ---------------------------------------------------------------------------
# 1a. Ensure hiclaw-storage bucket exists (safety net)
#     manager-init-internal.sh creates this, but workers may start their
#     file-sync BEFORE the Manager's background auto-init reaches that step.
#     Creating it here from the host eliminates the "specified bucket does
#     not exist" errors that cause workers to start without configs.
# ---------------------------------------------------------------------------
log "Ensuring hiclaw-storage bucket exists..."
docker exec "$EMBEDDED_CONTAINER" bash -c \
    "mc mb --ignore-existing hiclaw/hiclaw-storage >/dev/null 2>&1 && echo 'bucket ready' || echo 'bucket already exists'" \
    && log "  → hiclaw-storage bucket ready" \
    || warn "  Failed to create bucket (Manager auto-init will retry)"

# ---------------------------------------------------------------------------
# 1b. Wait for Manager auto-init to complete
#     The Manager's entrypoint-wrapper.sh runs manager-init-internal.sh in
#     the background on every startup. That script registers workers on
#     Matrix, generates openclaw.json via generate-worker-config.sh, and
#     uploads configs to MinIO. We MUST wait for it to finish before
#     proceeding — otherwise the patch steps below find no openclaw.json
#     and the "create-worker.sh failed" path silently skips everything.
# ---------------------------------------------------------------------------
log "Waiting for Manager auto-init to complete..."
INIT_LOG="/var/log/hiclaw/honeybadge-init.log"
AUTO_INIT_MARKER="HoneyBadge auto-init complete!"
AUTO_INIT_WAIT_RETRIES="${AUTO_INIT_WAIT_RETRIES:-30}"  # 30 × 10s = 300s max
for i in $(seq 1 "$AUTO_INIT_WAIT_RETRIES"); do
    INIT_CONTENT=$(docker exec "$MANAGER_CONTAINER" cat "$INIT_LOG" 2>/dev/null || echo "")
    if echo "$INIT_CONTENT" | grep -q "$AUTO_INIT_MARKER"; then
        log "  → Manager auto-init complete (attempt $i/$AUTO_INIT_WAIT_RETRIES)"
        break
    fi
    if [ "$i" -eq "$AUTO_INIT_WAIT_RETRIES" ]; then
        warn "  Manager auto-init did not complete within $((AUTO_INIT_WAIT_RETRIES * 10))s"
        warn "  Worker configs may be missing — check: docker exec $MANAGER_CONTAINER cat $INIT_LOG"
    fi
    sleep 10
done

# ---------------------------------------------------------------------------
# 1c. Verify worker openclaw.json exists in MinIO
#     If the auto-init failed to generate configs, workers will start
#     without proper LLM/MCP settings and silently fail to process messages.
#     NOTE: We check from the MANAGER container (not EMBEDDED) because the
#     Manager's mc alias is configured by manager-init-internal.sh to point
#     at hiclaw-embedded:9000, while the EMBEDDED container's alias may have
#     a different configuration that doesn't see the same objects.
# ---------------------------------------------------------------------------
for worker in graph-worker analytics-worker; do
    if docker exec "$MANAGER_CONTAINER" mc stat "hiclaw/hiclaw-storage/agents/${worker}/openclaw.json" >/dev/null 2>&1; then
        log "  → ${worker}/openclaw.json verified in MinIO"
    else
        warn "  ${worker}/openclaw.json NOT in MinIO — workers may not function"
        warn "  Check: docker exec $MANAGER_CONTAINER cat $INIT_LOG"
    fi
done

# ---------------------------------------------------------------------------
# 1d. Inject Manager's custom SOUL.md and AGENTS.md into the Manager container
#     HiClaw generates default SOUL.md/AGENTS.md with a <!-- hiclaw-builtin-end -->
#     marker. Our custom routing logic goes AFTER that marker.
# ---------------------------------------------------------------------------
log "Injecting Manager's custom SOUL.md and AGENTS.md..."

MANAGER_SOUL="$PROJECT_ROOT/hiclaw/manager/agent/SOUL.md"
MANAGER_AGENTS="$PROJECT_ROOT/hiclaw/manager/agent/AGENTS.md"

if [ -f "$MANAGER_SOUL" ]; then
    docker cp "$MANAGER_SOUL" "$MANAGER_CONTAINER:/tmp/hb-manager-soul.md"
    docker exec "$MANAGER_CONTAINER" sh -c '
        BUILTIN="/root/manager-workspace/SOUL.md"
        CUSTOM="/tmp/hb-manager-soul.md"
        if [ -f "$BUILTIN" ] && grep -q "hiclaw-builtin-end" "$BUILTIN"; then
            # Put custom HoneyBadge content FIRST, then built-in section.
            # LLMs pay more attention to content at the beginning of the
            # system prompt, so our routing protocol must come before the
            # HiClaw built-in instructions.
            cat "$CUSTOM" > /tmp/merged-soul.md
            echo "" >> /tmp/merged-soul.md
            sed -n "1,/hiclaw-builtin-end/p" "$BUILTIN" >> /tmp/merged-soul.md
            cp /tmp/merged-soul.md "$BUILTIN"
            echo "Manager SOUL.md: prepended custom content before builtin section"
        else
            # No builtin marker — just use our custom SOUL.md
            cp "$CUSTOM" "$BUILTIN"
            echo "Manager SOUL.md: replaced with custom content"
        fi
    ' && log "  → Manager SOUL.md injected" || warn "  Failed to inject Manager SOUL.md"
else
    warn "  Manager SOUL.md not found at $MANAGER_SOUL"
fi

if [ -f "$MANAGER_AGENTS" ]; then
    docker cp "$MANAGER_AGENTS" "$MANAGER_CONTAINER:/tmp/hb-manager-agents.md"
    docker exec "$MANAGER_CONTAINER" sh -c '
        BUILTIN="/root/manager-workspace/AGENTS.md"
        CUSTOM="/tmp/hb-manager-agents.md"
        if [ -f "$BUILTIN" ] && grep -q "hiclaw-builtin-end" "$BUILTIN"; then
            sed -n "1,/hiclaw-builtin-end/p" "$BUILTIN" > /tmp/merged-agents.md
            echo "" >> /tmp/merged-agents.md
            cat "$CUSTOM" >> /tmp/merged-agents.md
            cp /tmp/merged-agents.md "$BUILTIN"
            echo "Manager AGENTS.md: appended custom content after builtin section"
        else
            cp "$CUSTOM" "$BUILTIN"
            echo "Manager AGENTS.md: replaced with custom content"
        fi
    ' && log "  → Manager AGENTS.md injected" || warn "  Failed to inject Manager AGENTS.md"
else
    warn "  Manager AGENTS.md not found at $MANAGER_AGENTS"
fi

# Sync Manager agent files to MinIO for persistence.
# v1.1.0 split: stage files via host /tmp, then run mc inside hiclaw-embedded.
docker cp "$MANAGER_CONTAINER:/root/manager-workspace/SOUL.md" /tmp/hb-manager-SOUL.md 2>/dev/null && \
    docker cp /tmp/hb-manager-SOUL.md "$EMBEDDED_CONTAINER:/tmp/hb-manager-SOUL.md" && \
    docker exec "$EMBEDDED_CONTAINER" bash -c \
        "mc cp /tmp/hb-manager-SOUL.md hiclaw/hiclaw-storage/agents/manager/SOUL.md 2>/dev/null && echo synced || true" \
    && log "  → Manager SOUL.md synced to MinIO" || true
docker cp "$MANAGER_CONTAINER:/root/manager-workspace/AGENTS.md" /tmp/hb-manager-AGENTS.md 2>/dev/null && \
    docker cp /tmp/hb-manager-AGENTS.md "$EMBEDDED_CONTAINER:/tmp/hb-manager-AGENTS.md" && \
    docker exec "$EMBEDDED_CONTAINER" bash -c \
        "mc cp /tmp/hb-manager-AGENTS.md hiclaw/hiclaw-storage/agents/manager/AGENTS.md 2>/dev/null && echo synced || true" \
    && log "  → Manager AGENTS.md synced to MinIO" || true

# Inject Manager's custom skills (e.g., erp-query-dispatch)
MANAGER_SKILLS="$PROJECT_ROOT/hiclaw/manager/agent/skills"
if [ -d "$MANAGER_SKILLS" ]; then
    log "Injecting Manager custom skills..."
    for skill_dir in "$MANAGER_SKILLS"/*/; do
        skill_name=$(basename "$skill_dir")
        docker exec "$MANAGER_CONTAINER" bash -c "mkdir -p /root/manager-workspace/skills/${skill_name}"
        docker cp "${skill_dir}SKILL.md" "$MANAGER_CONTAINER:/root/manager-workspace/skills/${skill_name}/SKILL.md" 2>/dev/null && \
            log "  → ${skill_name}/SKILL.md injected" || warn "  Failed to inject ${skill_name}"
    done
    # Sync all custom skills to MinIO.
    # v1.1.0 split: copy skills dir to host tmp, then push into embedded for mc.
    docker cp "$MANAGER_CONTAINER:/root/manager-workspace/skills/" /tmp/hb-manager-skills/ 2>/dev/null && \
        docker cp /tmp/hb-manager-skills/ "$EMBEDDED_CONTAINER:/tmp/hb-manager-skills/" && \
        docker exec "$EMBEDDED_CONTAINER" bash -c \
            "mc mirror /tmp/hb-manager-skills/ hiclaw/hiclaw-storage/agents/manager/skills/ --overwrite 2>/dev/null && echo synced || true" \
        && log "  → Manager skills synced to MinIO" || true
fi

# ---------------------------------------------------------------------------
# 2. Upload worker SOUL.md files into MinIO via mc (inside hiclaw-embedded)
#    MinIO bucket path: hiclaw-storage/agents/{WORKER_NAME}/SOUL.md
#    v1.1.0 split: mc runs in EMBEDDED_CONTAINER; the 'hiclaw' alias is
#    pre-configured by the upstream hiclaw-embedded image (localhost:9000).
# ---------------------------------------------------------------------------
log "Uploading worker SOUL.md files to MinIO..."

for worker in graph-worker analytics-worker; do
    SOUL_SRC="$PROJECT_ROOT/hiclaw/workers/$worker/agent/SOUL.md"
    # v1.1.0 split: mc lives in hiclaw-embedded; copy files there for MinIO upload.
    docker cp "$SOUL_SRC" "$EMBEDDED_CONTAINER:/tmp/${worker}-SOUL.md"
    docker exec "$EMBEDDED_CONTAINER" bash -c \
        "mc cp /tmp/${worker}-SOUL.md hiclaw/hiclaw-storage/agents/${worker}/SOUL.md"
    log "  → ${worker}/SOUL.md uploaded to MinIO"

    # Upload skills if they exist
    SKILLS_DIR="$PROJECT_ROOT/hiclaw/workers/$worker/agent/skills"
    if [ -d "$SKILLS_DIR" ]; then
        # Trailing slash on source copies directory CONTENTS (not the dir itself),
        # matching the Manager skills sync pattern above. Without it, docker cp
        # creates a nested skills/skills/ path in MinIO.
        docker cp "$SKILLS_DIR/" "$EMBEDDED_CONTAINER:/tmp/${worker}-skills/"
        docker exec "$EMBEDDED_CONTAINER" bash -c \
            "mc mirror /tmp/${worker}-skills/ hiclaw/hiclaw-storage/agents/${worker}/skills/ --overwrite"
        log "  → ${worker}/skills/ uploaded to MinIO"
    fi
done

# ---------------------------------------------------------------------------
# 3. Worker registration — handled by manager-init-internal.sh
#
#    HiClaw v1.1.0+ removed create-worker.sh. The Manager's auto-init
#    (manager-init-internal.sh Step 2) registers workers on Matrix and
#    generates openclaw.json via generate-worker-config.sh. We verified
#    those configs exist in Step 1c above.
#
#    The patch below is a FALLBACK: if the auto-init's own patch step
#    (Step 2b) didn't run or produced the wrong LLM baseUrl/model, we
#    fix it here. This is idempotent — if the config is already correct,
#    the Python script prints "No changes needed" and exits.
# ---------------------------------------------------------------------------
log "Verifying/patching worker LLM config (→ aigw-local.hiclaw.io:8080/v1, model → ${MANAGER_LLM_MODEL:-glm-5.2})..."
# baseUrl MUST include /v1: OpenAI JS SDK appends /chat/completions directly
# Without /v1: path becomes /chat/completions → misses llm-minimax-route → no API key → 404
for worker in graph-worker analytics-worker; do
    docker exec "$MANAGER_CONTAINER" python3 -c "
import json, os, sys

paths = [
    '/tmp/${worker}-workspace/openclaw.json',
    '/root/hiclaw-fs/agents/${worker}/openclaw.json',
]

cfg_path = None
for p in paths:
    if os.path.exists(p):
        cfg_path = p
        break

if cfg_path is None:
    print('openclaw.json not found for ${worker}')
    sys.exit(0)

with open(cfg_path) as f:
    cfg = json.load(f)

providers = cfg.get('models', {}).get('providers', {})
for name, p in providers.items():
    old = p.get('baseUrl', '')
    if 'aigw-local.hiclaw.io:8080/v1' not in old:
        p['baseUrl'] = 'http://aigw-local.hiclaw.io:8080/v1'
        print('Patched ' + name + ' baseUrl: ' + old + ' -> ' + p['baseUrl'])
    for model in p.get('models', []):
        old_id = model.get('id', '')
        if old_id != '${MANAGER_LLM_MODEL:-glm-5.2}':
            model['id'] = '${MANAGER_LLM_MODEL:-glm-5.2}'
            model['name'] = '${MANAGER_LLM_MODEL:-glm-5.2}'
            print('Updated model: ' + old_id + ' -> ${MANAGER_LLM_MODEL:-glm-5.2}')
        # Always remove reasoning:true — openclaw thinking mode sends Claude-style
        # thinking blocks that DashScope rejects with role-ordering 400 errors.
        model.pop('reasoning', None)
        # Cap maxTokens at 8192 — openclaw ships glm-5.2 with maxTokens=128000,
        # which reserves nearly the entire context window for OUTPUT. That leaves
        # promptBudget = contextWindow - maxTokens ≈ 22K, causing
        # 'Context overflow: prompt too large for the model (precheck)' after
        # only 30-50 tool-loop messages, and auto-compaction trips its
        # 'already_compacted_recently' circuit breaker.
        # glm-5.2 is a chat model — 8K output is plenty for tool calls + summaries.
        old_mt = model.get('maxTokens', 0)
        if old_mt > 8192:
            model['maxTokens'] = 8192
            print('Capped maxTokens: ' + str(old_mt) + ' -> 8192')

agents = cfg.get('agents', {}).get('defaults', {}).get('model', {})
old_primary = agents.get('primary', '')
if '${MANAGER_LLM_MODEL:-glm-5.2}' not in old_primary:
    for name in providers.keys():
        agents['primary'] = name + '/${MANAGER_LLM_MODEL:-glm-5.2}'
        print('Updated primary: ' + old_primary + ' -> ' + agents['primary'])
        break

# Fix Matrix homeserver port: Tuwunel runs on 6167, NOT the Higress gateway port 8080.
# create-worker.sh may generate the wrong port; patch it here.
matrix_cfg = cfg.get('channels', {}).get('matrix', {})
hs = matrix_cfg.get('homeserver', '')
if hs and ':8080' in hs and 'matrix-local.hiclaw.io' in hs:
    fixed = hs.replace(':8080', ':6167')
    matrix_cfg['homeserver'] = fixed
    print('Fixed Matrix homeserver port: ' + hs + ' -> ' + fixed)

# Context pruning + concurrent boost (performance optimization)
if 'agents' not in cfg:
    cfg['agents'] = {}
if 'defaults' not in cfg['agents']:
    cfg['agents']['defaults'] = {}
defaults = cfg['agents']['defaults']
if defaults.get('maxConcurrent') != 8:
    defaults['maxConcurrent'] = 8
    print('Set maxConcurrent: 8')
if defaults.get('contextTokens') != 200000:
    defaults['contextTokens'] = 200000
    print('Set contextTokens: 200000')
if defaults.get('contextPruning', {}).get('mode') != 'cache-ttl':
    defaults['contextPruning'] = {
        'mode': 'cache-ttl',
        'keepLastAssistants': 10,
        'softTrimRatio': 0.7,
        'hardClearRatio': 0.9,
        'hardClear': {
            'enabled': True,
            'placeholder': '[历史对话已自动压缩，当前任务上下文完整保留]'
        }
    }
    print('Set contextPruning')
if defaults.get('subagents', {}).get('maxConcurrent') != 8:
    defaults['subagents'] = {'maxConcurrent': 8}
    print('Set subagents.maxConcurrent: 8')

with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2)
print('done')
" && log "  → ${worker} baseUrl and model patched" || warn "  Failed to patch ${worker}"

    # Sync patched config to MinIO.
    # v1.1.0 split: stage via host /tmp, then run mc inside hiclaw-embedded.
    docker cp "$MANAGER_CONTAINER:/root/hiclaw-fs/agents/${worker}/openclaw.json" \
        "/tmp/${worker}-openclaw.json" 2>/dev/null && \
    docker cp "/tmp/${worker}-openclaw.json" \
        "$EMBEDDED_CONTAINER:/tmp/${worker}-openclaw.json" && \
    docker exec "$EMBEDDED_CONTAINER" bash -c \
        "mc cp /tmp/${worker}-openclaw.json hiclaw/hiclaw-storage/agents/${worker}/openclaw.json 2>/dev/null && echo synced || true" \
        && log "  → ${worker} openclaw.json synced to MinIO" || warn "  MinIO sync skipped for ${worker}"
done

# (Step 3c-pre removed: no longer patching McpBridge YAML directly.
#  HICLAW_LLM_PROVIDER=openai-compat in docker-compose.yaml makes setup-higress.sh
#  create openai-compat.dns → coding.dashscope.aliyuncs.com on every startup via
#  idempotent PUT. The llm-minimax-route (step 3c) uses openai-compat.dns as backend.)

# ---------------------------------------------------------------------------
# 3c. Ensure Higress LLM route for DashScope (qwen3.5-plus) exists
#
#     setup-higress.sh (HICLAW_LLM_PROVIDER=openai-compat) creates an
#     auto-generated route at / that has NO API key injected.
#     We create (or update) a more-specific route at /v1/ that takes priority
#     and injects the real DashScope API key into all LLM requests.
#
#     Backend: openai-compat.dns (→ coding.dashscope.aliyuncs.com:443)
#     This service source is created by setup-higress.sh on every startup and
#     is idempotent (PUT), so it always points to coding.dashscope.aliyuncs.com.
#
#     IRON RULE: ALL LLM calls MUST go through Higress. Workers never call any
#     LLM endpoint directly. This route is the single exit point for all LLM traffic.
# ---------------------------------------------------------------------------
log "Ensuring Higress LLM route (aigw-local.hiclaw.io /v1/ → BigModel/${MANAGER_LLM_MODEL:-glm-5.2})..."
HIGRESS_AUTH="$(echo -n "${HICLAW_ADMIN_USER:-admin}:${HICLAW_ADMIN_PASSWORD:-admin1234}" | base64)"
LLM_API_KEY="${LLM_API_KEY:-${HICLAW_LLM_API_KEY:-}}"

# Wait for openai-compat.dns service source to exist (created by setup-higress.sh).
# This is OPTIONAL — if setup-higress.sh skipped (e.g., placeholder LLM_API_KEY in CI),
# we still want the rest of init-workers.sh to run. Mirror the soft-fail pattern
# from manager-init-internal.sh:661-690.
log "  Waiting for openai-compat.dns service source..."
SVC_READY=0
for i in $(seq 1 20); do
    SVC=$(docker exec "$MANAGER_CONTAINER" sh -c \
        "curl -sf 'http://hiclaw-embedded:8001/v1/service-sources/openai-compat' 2>/dev/null" || true)
    if echo "$SVC" | grep -q '"name":"openai-compat"'; then
        log "  → openai-compat.dns ready"
        SVC_READY=1
        break
    fi
    if [ "$i" -eq 20 ]; then
        warn "  openai-compat.dns not found after 60s — LLM route may not work (set LLM_API_KEY?)"
    fi
    sleep 3
done

# PUT to update if exists, POST to create if not. Wrap in `|| true` so a failure
# here (e.g., missing service-source backend) does not abort the whole script
# under set -euo pipefail.
if [ "$SVC_READY" -eq 1 ]; then
    RESULT=$(docker exec "$MANAGER_CONTAINER" sh -c \
        "curl -sf -X PUT 'http://hiclaw-embedded:8001/v1/routes/llm-minimax-route' \
          -H 'Authorization: Basic $HIGRESS_AUTH' -H 'Content-Type: application/json' \
          -d '{\"name\":\"llm-minimax-route\",\"domains\":[\"aigw-local.hiclaw.io\"],\"path\":{\"matchType\":\"PRE\",\"matchValue\":\"/v1/\",\"caseSensitive\":false},\"services\":[{\"name\":\"openai-compat.dns\",\"port\":443,\"weight\":100}],\"proxyNextUpstream\":{\"enabled\":true,\"attempts\":3,\"timeout\":120000,\"conditions\":[\"error\",\"timeout\",\"non_idempotent\"]},\"headerControl\":{\"enabled\":true,\"request\":{\"add\":[{\"key\":\"user-agent\",\"value\":\"HiClaw/v1.0.9\"}],\"set\":[{\"key\":\"Authorization\",\"value\":\"Bearer ${LLM_API_KEY}\"},{\"key\":\"Host\",\"value\":\"coding.dashscope.aliyuncs.com\"}],\"remove\":[]}},\"authConfig\":{\"enabled\":false}}' 2>&1" || true)

    if echo "$RESULT" | grep -q '"name":"llm-minimax-route"'; then
        log "  → llm-minimax-route updated (openai-compat.dns → coding.dashscope.aliyuncs.com)"
    else
        docker exec "$MANAGER_CONTAINER" sh -c \
            "curl -sf -X POST 'http://hiclaw-embedded:8001/v1/routes' \
              -H 'Authorization: Basic $HIGRESS_AUTH' -H 'Content-Type: application/json' \
              -d '{\"name\":\"llm-minimax-route\",\"domains\":[\"aigw-local.hiclaw.io\"],\"path\":{\"matchType\":\"PRE\",\"matchValue\":\"/v1/\",\"caseSensitive\":false},\"services\":[{\"name\":\"openai-compat.dns\",\"port\":443,\"weight\":100}],\"proxyNextUpstream\":{\"enabled\":true,\"attempts\":3,\"timeout\":120000,\"conditions\":[\"error\",\"timeout\",\"non_idempotent\"]},\"headerControl\":{\"enabled\":true,\"request\":{\"add\":[{\"key\":\"user-agent\",\"value\":\"HiClaw/v1.0.9\"}],\"set\":[{\"key\":\"Authorization\",\"value\":\"Bearer ${LLM_API_KEY}\"},{\"key\":\"Host\",\"value\":\"coding.dashscope.aliyuncs.com\"}],\"remove\":[]}},\"authConfig\":{\"enabled\":false}}' 2>&1" \
            && log "  → llm-minimax-route created (openai-compat.dns → coding.dashscope.aliyuncs.com)" \
            || warn "  Failed to create/update LLM route (Higress not ready?)"
    fi
else
    warn "  Skipping llm-minimax-route — openai-compat.dns backend not registered"
fi

# ---------------------------------------------------------------------------
# 4. Per-user Matrix accounts (Approach B) + patch Manager allowlist
#    Per-user Matrix accounts are provisioned at login time by honeybadge-auth.
#    We must patch Manager's openclaw.json to allow @hb-* users to DM Manager.
# ---------------------------------------------------------------------------
log "Patching Manager allowlist for @hb-* users (Approach B)..."
docker exec "$MANAGER_CONTAINER" bash -c "
python3 -c \"
import json

cfg_path = '/root/manager-workspace/openclaw.json'
with open(cfg_path) as f:
    cfg = json.load(f)

hb_users = [
    '@admin:${MATRIX_DOMAIN}',
    '@hb-admin:${MATRIX_DOMAIN}',
    '@hb-analyst:${MATRIX_DOMAIN}',
    '@hb-auditor:${MATRIX_DOMAIN}',
    '@hb-procurement_lead:${MATRIX_DOMAIN}',
    '@hb-subsidiary_lead:${MATRIX_DOMAIN}',
    '@honeybadge-gateway:${MATRIX_DOMAIN}'
]

# Workers must be allowed to send in group rooms so the Manager can receive
# their completion messages and forward results to the user DM. Without this,
# worker replies in group rooms are dropped by groupAllowFrom and
# result-watcher never sees the completion signal.
workers = [
    '@graph-worker:${MATRIX_DOMAIN}',
    '@analytics-worker:${MATRIX_DOMAIN}',
]

cfg['channels']['matrix']['dm'] = {'policy': 'allowlist', 'allowFrom': hb_users}
cfg['channels']['matrix']['groupAllowFrom'] = hb_users + workers

# Remove reasoning:true from all models — openclaw's thinking mode sends Claude-style
# thinking content blocks that DashScope/qwen3.5-plus rejects with a 400 role error,
# causing 'Message ordering conflict' on every user message.
# Also cap maxTokens at 8192 — the shipped 128000 leaves only ~22K for prompt,
# triggering 'Context overflow' after 30-50 messages and breaking E2E suites.
for p in cfg.get('models', {}).get('providers', {}).values():
    for m in p.get('models', []):
        m.pop('reasoning', None)
        old_mt = m.get('maxTokens', 0)
        if old_mt > 8192:
            m['maxTokens'] = 8192

# Context pruning for Manager (mirrors Worker settings)
if 'agents' not in cfg:
    cfg['agents'] = {}
if 'defaults' not in cfg['agents']:
    cfg['agents']['defaults'] = {}
mgr_defaults = cfg['agents']['defaults']
if mgr_defaults.get('contextTokens') != 200000:
    mgr_defaults['contextTokens'] = 200000
    print('Set Manager contextTokens: 200000')
if mgr_defaults.get('contextPruning', {}).get('mode') != 'cache-ttl':
    mgr_defaults['contextPruning'] = {
        'mode': 'cache-ttl',
        'keepLastAssistants': 10,
        'softTrimRatio': 0.7,
        'hardClearRatio': 0.9,
        'hardClear': {
            'enabled': True,
            'placeholder': '[历史对话已自动压缩，当前任务上下文完整保留]'
        }
    }
    print('Set Manager contextPruning')

with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2)
print('allowlist patched, reasoning removed, context pruning applied')
\"
" && log "  → Manager allowlist updated" || warn "  Failed to patch Manager allowlist"

# Sync to MinIO so it survives restarts.
# v1.1.0 split: stage manager-workspace file via host /tmp, then mc in embedded.
docker cp "$MANAGER_CONTAINER:/root/manager-workspace/openclaw.json" \
    /tmp/hb-manager-openclaw.json 2>/dev/null && \
docker cp /tmp/hb-manager-openclaw.json \
    "$EMBEDDED_CONTAINER:/tmp/hb-manager-openclaw.json" && \
docker exec "$EMBEDDED_CONTAINER" bash -c \
    "mc cp /tmp/hb-manager-openclaw.json hiclaw/hiclaw-storage/agents/manager/openclaw.json 2>/dev/null && echo synced || true" \
    && log "  → Synced to MinIO" || warn "  MinIO sync skipped (optional)"

# ---------------------------------------------------------------------------
# 5. Register MCP servers in each worker via mcporter config add
#
#    We bypass setup-mcp-server.sh (which requires a session cookie from the
#    Higress Console and can expire).  mcporter's CLI directly writes
#    /root/hiclaw-fs/config/mcporter.json inside the worker container, then
#    we persist that file to MinIO so it survives restarts.
# ---------------------------------------------------------------------------
log "Registering MCP servers in workers via mcporter..."

# Map: server-name → streamable-http endpoint inside the Docker network
declare -A MCP_SERVERS=(
    [honeybadge-nebula]="http://honeybadge-nebula-mcp:8000/mcp"
    [honeybadge-audit]="http://honeybadge-audit-mcp:8000/mcp"
    [honeybadge-cache]="http://honeybadge-cache-mcp:8000/mcp"
)

for worker in graph-worker analytics-worker; do
    WORKER_CONTAINER="honeybadge-${worker}"
    log "  Configuring $worker..."
    for server_name in "${!MCP_SERVERS[@]}"; do
        endpoint="${MCP_SERVERS[$server_name]}"
        docker exec "$WORKER_CONTAINER" bash -c \
            "mcporter config add '$server_name' '$endpoint' --allow-http --yes 2>&1" \
            && log "    → $server_name added" \
            || warn "    $server_name already exists or failed"
    done

    # Persist mcporter.json to MinIO so it survives container restarts.
    # v1.1.0 split: stage via host /tmp, then mc in hiclaw-embedded.
    docker cp "${WORKER_CONTAINER}:/root/hiclaw-fs/config/mcporter.json" \
        "/tmp/${worker}-mcporter.json" 2>/dev/null && \
    docker cp "/tmp/${worker}-mcporter.json" \
        "$EMBEDDED_CONTAINER:/tmp/${worker}-mcporter.json" && \
    docker exec "$EMBEDDED_CONTAINER" bash -c \
        "mc cp /tmp/${worker}-mcporter.json hiclaw/hiclaw-storage/agents/${worker}/config/mcporter.json 2>&1 | tail -1" \
        && log "    → mcporter.json synced to MinIO" \
        || warn "    MinIO sync failed (config still active in running container)"
done

# ---------------------------------------------------------------------------
# 5b. Register MCP servers in the MANAGER via direct config write
#
#     The Manager's fast-query and ERP-dispatch skills call mcporter with
#     unprefixed names: `honeybadge-nebula`, `honeybadge-audit`,
#     `honeybadge-cache`. HiClaw's setup-mcp-server.sh would write
#     `mcp-honeybadge-*` (prepends `mcp-`) and point at the broken
#     `localhost:8080/mcp-servers/...` Higress route. To keep parity with
#     the worker config (direct SSE to the MCP containers), we write the
#     file ourselves and sync to MinIO.
#
#     Note: FastMCP exposes /mcp (streamable-http transport) on port 8000.
#     mcporter detects transport from the URL path.
# ---------------------------------------------------------------------------
log "Provisioning Manager mcporter.json (streamable-http, unprefixed names)..."

MANAGER_MCPORTER_JSON='{
  "mcpServers": {
    "honeybadge-nebula": { "baseUrl": "http://honeybadge-nebula-mcp:8000/mcp" },
    "honeybadge-audit":  { "baseUrl": "http://honeybadge-audit-mcp:8000/mcp"  },
    "honeybadge-cache":  { "baseUrl": "http://honeybadge-cache-mcp:8000/mcp"  }
  }
}'

# Write into the Manager container at both the active path
# (/root/config/mcporter.json — what fast-query.sh reads via default
# MCPORTER_CONFIG) and the workspace path (/root/manager-workspace/config/).
# Ensure /root/config/ exists — v1.1.2 may not create it by default.
docker exec "$MANAGER_CONTAINER" mkdir -p /root/config
printf '%s\n' "$MANAGER_MCPORTER_JSON" > "$TMP_DIR/hb-manager-mcporter.json"
docker cp "$TMP_DIR/hb-manager-mcporter.json" \
    "$MANAGER_CONTAINER:/root/config/mcporter.json" \
    && log "  → /root/config/mcporter.json written" \
    || warn "  Failed to write /root/config/mcporter.json"

docker exec "$MANAGER_CONTAINER" bash -c \
    'mkdir -p /root/manager-workspace/config && \
     cp /root/config/mcporter.json /root/manager-workspace/config/mcporter.json' \
    && log "  → /root/manager-workspace/config/mcporter.json written" \
    || warn "  Failed to mirror to manager-workspace"

# Sync to MinIO so it survives Manager container restarts.
docker cp "$TMP_DIR/hb-manager-mcporter.json" \
    "$EMBEDDED_CONTAINER:/tmp/hb-manager-mcporter.json" && \
docker exec "$EMBEDDED_CONTAINER" bash -c \
    "mc cp /tmp/hb-manager-mcporter.json hiclaw/hiclaw-storage/agents/manager/config/mcporter.json 2>&1 | tail -1" \
    && log "  → Manager mcporter.json synced to MinIO" \
    || warn "  MinIO sync failed (config still active in running Manager)"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
log "Worker initialization complete!"
echo ""
echo "  Next steps:"
echo "  1. Restart workers to pick up their new MinIO config:"
echo "       docker compose restart hiclaw-graph-worker hiclaw-analytics-worker"
echo "  2. Start honeybadge-auth service (provisions Matrix accounts at login):"
echo "       docker compose up -d honeybadge-auth"
echo "  3. Access the UI: http://localhost:3000"
echo "     Login: admin/admin123"
echo ""
echo "  Monitor agents via Element Web: http://localhost:18888"
echo "  Inspect MinIO config:           http://localhost:19001  (admin/admin)"
