#!/bin/bash
# HoneyBadge Worker Initialization Script — MANUAL FALLBACK
#
# NOTE: This script is now OPTIONAL. The Manager container auto-runs
# manager-init-internal.sh on every startup via entrypoint-wrapper.sh.
# Use this script only for debugging or if auto-init fails.
#
# What it does:
#   1. Copies worker SOUL.md files into HiClaw Manager's MinIO-accessible filesystem
#   2. Calls create-worker.sh for each worker (inside Manager container)
#      → creates Matrix user accounts in Tuwunel
#      → creates Higress consumer entries
#      → generates openclaw.json in MinIO (workers need this to start)
#   3. (Approach B) Per-user Matrix accounts are provisioned at login via honeybadge-auth
#   4. Registers HoneyBadge MCP servers in Higress AI Gateway
#
# Usage (only if auto-init fails):
#   cd deploy/docker && docker compose up -d
#   # Wait ~60s for hiclaw-manager to become healthy
#   bash ../../deploy/hiclaw/init-workers.sh
#
# Check auto-init log first:
#   docker exec honeybadge-hiclaw-manager cat /var/log/hiclaw/honeybadge-init.log
#
# Re-run after: docker compose down -v (data volumes wiped)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source .env for LLM_API_KEY and other config (if not already in environment)
ENV_FILE="$PROJECT_ROOT/deploy/docker/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

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
# 1b. Inject Manager's custom SOUL.md and AGENTS.md into the Manager container
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
            # Keep built-in section, append custom HoneyBadge content after it
            sed -n "1,/hiclaw-builtin-end/p" "$BUILTIN" > /tmp/merged-soul.md
            echo "" >> /tmp/merged-soul.md
            cat "$CUSTOM" >> /tmp/merged-soul.md
            cp /tmp/merged-soul.md "$BUILTIN"
            echo "Manager SOUL.md: appended custom content after builtin section"
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
# 2. Upload worker SOUL.md files into MinIO via mc (inside Manager container)
#    MinIO bucket path: hiclaw-storage/agents/{WORKER_NAME}/SOUL.md
#    The mc alias 'hiclaw' is pre-configured by start-mc-mirror.sh
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
        docker cp "$SKILLS_DIR" "$EMBEDDED_CONTAINER:/tmp/${worker}-skills"
        docker exec "$EMBEDDED_CONTAINER" bash -c \
            "mc mirror /tmp/${worker}-skills/ hiclaw/hiclaw-storage/agents/${worker}/skills/"
        log "  → ${worker}/skills/ uploaded to MinIO"
    fi
done

# ---------------------------------------------------------------------------
# 3. Register workers using create-worker.sh (runs inside Manager container)
#    This creates Matrix users, Higress consumers, and generates openclaw.json
# ---------------------------------------------------------------------------
CREATE_WORKER="/opt/hiclaw/agent/skills/worker-management/scripts/create-worker.sh"

log "Registering graph-worker..."
docker exec "$MANAGER_CONTAINER" bash -c \
    "$CREATE_WORKER --name graph-worker --skills file-sync,mcporter 2>&1" \
    && log "  → graph-worker registered" \
    || warn "  create-worker.sh for graph-worker failed (may already exist)"

log "Registering analytics-worker..."
docker exec "$MANAGER_CONTAINER" bash -c \
    "$CREATE_WORKER --name analytics-worker --skills file-sync,mcporter 2>&1" \
    && log "  → analytics-worker registered" \
    || warn "  create-worker.sh for analytics-worker failed (may already exist)"

# ---------------------------------------------------------------------------
# 3b. Fix worker LLM baseUrl: hiclaw-manager:8080 → aigw-local.hiclaw.io:8080
#     and update model name to qwen3.5-plus
#
#     create-worker.sh generates openclaw.json with baseUrl=http://hiclaw-manager:8080/v1.
#     Higress requires Host: aigw-local.hiclaw.io to route AI requests.
#     docker-compose.yaml gives hiclaw-manager a network alias aigw-local.hiclaw.io,
#     so workers resolve this name to the manager's current IP via Docker DNS —
#     no hardcoded IPs needed.
#
#     CRITICAL: baseUrl MUST end with /v1. OpenAI JS SDK v6 appends /chat/completions
#     directly (no /v1). Without /v1 in baseUrl, path is /chat/completions which
#     misses the /v1/ route → falls to internal route with no API key → 404.
#
#     IRON RULE: Workers NEVER call any LLM directly. ALL LLM calls MUST route
#     through Higress AI Gateway at http://aigw-local.hiclaw.io:8080/v1. No exceptions.
# ---------------------------------------------------------------------------
log "Fixing worker LLM baseUrl (→ aigw-local.hiclaw.io:8080/v1) and model (→ MiniMax-M2.7-highspeed)..."
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
        if old_id != 'MiniMax-M2.7-highspeed':
            model['id'] = 'MiniMax-M2.7-highspeed'
            model['name'] = 'MiniMax-M2.7-highspeed'
            print('Updated model: ' + old_id + ' -> MiniMax-M2.7-highspeed')
        # Always remove reasoning:true — openclaw thinking mode sends Claude-style
        # thinking blocks that DashScope rejects with role-ordering 400 errors.
        model.pop('reasoning', None)

agents = cfg.get('agents', {}).get('defaults', {}).get('model', {})
old_primary = agents.get('primary', '')
if 'MiniMax-M2.7-highspeed' not in old_primary:
    for name in providers.keys():
        agents['primary'] = name + '/MiniMax-M2.7-highspeed'
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
if defaults.get('contextTokens') != 40000:
    defaults['contextTokens'] = 40000
    print('Set contextTokens: 40000')
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
log "Ensuring Higress LLM route (aigw-local.hiclaw.io /v1/ → Minimax/MiniMax-M2.7-highspeed)..."
HIGRESS_AUTH="$(echo -n "${HICLAW_ADMIN_USER:-admin}:${HICLAW_ADMIN_PASSWORD:-admin1234}" | base64)"
LLM_API_KEY="${LLM_API_KEY:-${HICLAW_LLM_API_KEY:-}}"

# Wait for openai-compat.dns service source to exist (created by setup-higress.sh)
log "  Waiting for openai-compat.dns service source..."
for i in $(seq 1 20); do
    SVC=$(docker exec "$MANAGER_CONTAINER" sh -c \
        "curl -sf 'http://hiclaw-embedded:8001/v1/service-sources/openai-compat' 2>/dev/null" || true)
    if echo "$SVC" | grep -q '"name":"openai-compat"'; then
        log "  → openai-compat.dns ready"
        break
    fi
    sleep 3
done

# PUT to update if exists, POST to create if not
RESULT=$(docker exec "$MANAGER_CONTAINER" sh -c \
    "curl -sf -X PUT 'http://hiclaw-embedded:8001/v1/routes/llm-minimax-route' \
      -H 'Authorization: Basic $HIGRESS_AUTH' -H 'Content-Type: application/json' \
      -d '{\"name\":\"llm-minimax-route\",\"domains\":[\"aigw-local.hiclaw.io\"],\"path\":{\"matchType\":\"PRE\",\"matchValue\":\"/v1/\",\"caseSensitive\":false},\"services\":[{\"name\":\"openai-compat.dns\",\"port\":443,\"weight\":100}],\"proxyNextUpstream\":{\"enabled\":true,\"attempts\":3,\"timeout\":120000,\"conditions\":[\"error\",\"timeout\",\"non_idempotent\"]},\"headerControl\":{\"enabled\":true,\"request\":{\"add\":[{\"key\":\"user-agent\",\"value\":\"HiClaw/v1.0.9\"}],\"set\":[{\"key\":\"Authorization\",\"value\":\"Bearer ${LLM_API_KEY}\"},{\"key\":\"Host\",\"value\":\"api.minimaxi.com\"}],\"remove\":[]}},\"authConfig\":{\"enabled\":false}}' 2>&1")

if echo "$RESULT" | grep -q '"name":"llm-minimax-route"'; then
    log "  → llm-minimax-route updated (openai-compat.dns → api.minimaxi.com)"
else
    docker exec "$MANAGER_CONTAINER" sh -c \
        "curl -sf -X POST 'http://hiclaw-embedded:8001/v1/routes' \
          -H 'Authorization: Basic $HIGRESS_AUTH' -H 'Content-Type: application/json' \
          -d '{\"name\":\"llm-minimax-route\",\"domains\":[\"aigw-local.hiclaw.io\"],\"path\":{\"matchType\":\"PRE\",\"matchValue\":\"/v1/\",\"caseSensitive\":false},\"services\":[{\"name\":\"openai-compat.dns\",\"port\":443,\"weight\":100}],\"proxyNextUpstream\":{\"enabled\":true,\"attempts\":3,\"timeout\":120000,\"conditions\":[\"error\",\"timeout\",\"non_idempotent\"]},\"headerControl\":{\"enabled\":true,\"request\":{\"add\":[{\"key\":\"user-agent\",\"value\":\"HiClaw/v1.0.9\"}],\"set\":[{\"key\":\"Authorization\",\"value\":\"Bearer ${LLM_API_KEY}\"},{\"key\":\"Host\",\"value\":\"api.minimaxi.com\"}],\"remove\":[]}},\"authConfig\":{\"enabled\":false}}' 2>&1" \
        && log "  → llm-minimax-route created (openai-compat.dns → api.minimaxi.com)" \
        || warn "  Failed to create/update LLM route (Higress not ready?)"
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
for p in cfg.get('models', {}).get('providers', {}).values():
    for m in p.get('models', []):
        m.pop('reasoning', None)

# Context pruning for Manager (mirrors Worker settings)
if 'agents' not in cfg:
    cfg['agents'] = {}
if 'defaults' not in cfg['agents']:
    cfg['agents']['defaults'] = {}
mgr_defaults = cfg['agents']['defaults']
if mgr_defaults.get('contextTokens') != 40000:
    mgr_defaults['contextTokens'] = 40000
    print('Set Manager contextTokens: 40000')
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
