#!/bin/bash
# HoneyBadge Manager Init — runs INSIDE the Manager container
#
# This script is the internal equivalent of init-workers.sh, but requires
# no docker exec/cp — it runs directly inside the Manager container.
#
# Config files are mounted read-only at /opt/honeybadge/config/ via docker-compose:
#   /opt/honeybadge/config/manager/agent/SOUL.md
#   /opt/honeybadge/config/manager/agent/AGENTS.md
#   /opt/honeybadge/config/workers/{worker}/agent/SOUL.md
#   /opt/honeybadge/config/workers/{worker}/agent/skills/...
#
# All steps are idempotent — safe to run on every container start.

set -uo pipefail

# Config paths
HB_CONFIG="/opt/honeybadge/config"
MANAGER_WORKSPACE="/root/manager-workspace"
CREATE_WORKER="/opt/hiclaw/agent/skills/worker-management/scripts/create-worker.sh"
MATRIX_DOMAIN="${HICLAW_MATRIX_DOMAIN:-matrix-local.hiclaw.io}"
LLM_API_KEY="${HICLAW_LLM_API_KEY:-${LLM_API_KEY:-}}"

# ANSI colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[init]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*"; }

# ---------------------------------------------------------------------------
# Helper: inject custom content after <!-- hiclaw-builtin-end --> marker
# Usage: inject_after_marker <builtin_file> <custom_file> <label>
# ---------------------------------------------------------------------------
inject_after_marker() {
    local builtin="$1"
    local custom="$2"
    local label="$3"

    if [ ! -f "$custom" ]; then
        warn "  $label: custom file not found at $custom"
        return 1
    fi

    if [ -f "$builtin" ] && grep -q "hiclaw-builtin-end" "$builtin"; then
        # Keep built-in section, append custom HoneyBadge content after marker
        sed -n '1,/hiclaw-builtin-end/p' "$builtin" > /tmp/merged-inject.md
        echo "" >> /tmp/merged-inject.md
        cat "$custom" >> /tmp/merged-inject.md
        cp /tmp/merged-inject.md "$builtin"
        rm -f /tmp/merged-inject.md
        log "  $label: appended custom content after builtin section"
    else
        # No builtin marker — just use our custom file
        cp "$custom" "$builtin"
        log "  $label: replaced with custom content (no builtin marker found)"
    fi
}

# =========================================================================
# Step 1: Upload worker SOUL.md + skills to MinIO
#         (This doesn't need the Manager workspace — can run immediately)
# =========================================================================
log "Step 1: Uploading worker configs to MinIO..."

for worker in graph-worker analytics-worker; do
    SOUL_SRC="$HB_CONFIG/workers/$worker/agent/SOUL.md"
    if [ -f "$SOUL_SRC" ]; then
        mc cp "$SOUL_SRC" "hiclaw/hiclaw-storage/agents/$worker/SOUL.md"
        log "  $worker/SOUL.md uploaded to MinIO"
    else
        warn "  $worker/SOUL.md not found at $SOUL_SRC"
    fi

    # Upload skills directory if it exists
    SKILLS_DIR="$HB_CONFIG/workers/$worker/agent/skills"
    if [ -d "$SKILLS_DIR" ]; then
        mc mirror --overwrite "$SKILLS_DIR/" "hiclaw/hiclaw-storage/agents/$worker/skills/"
        log "  $worker/skills/ uploaded to MinIO"
    fi
done

# =========================================================================
# Step 2: Register workers using create-worker.sh
# =========================================================================
log "Step 2: Registering workers..."

for worker in graph-worker analytics-worker; do
    if [ -x "$CREATE_WORKER" ] || [ -f "$CREATE_WORKER" ]; then
        bash "$CREATE_WORKER" --name "$worker" --skills file-sync,mcporter 2>&1 \
            && log "  $worker registered" \
            || warn "  $worker registration failed (may already exist)"
    else
        warn "  create-worker.sh not found at $CREATE_WORKER"
    fi
done

# =========================================================================
# Step 2b: Fix worker LLM baseUrl and model
#
# create-worker.sh generates openclaw.json with baseUrl=http://hiclaw-manager:8080/v1.
# Higress requires Host: aigw-local.hiclaw.io for routing.
# baseUrl MUST end with /v1 (OpenAI JS SDK appends /chat/completions directly).
# =========================================================================
log "Step 2b: Patching worker LLM baseUrl and model..."

for worker in graph-worker analytics-worker; do
    python3 -c "
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

model_name = os.environ.get('HICLAW_DEFAULT_MODEL', 'MiniMax-M2.7')
changed = False

providers = cfg.get('models', {}).get('providers', {})
for name, p in providers.items():
    old = p.get('baseUrl', '')
    if 'aigw-local.hiclaw.io:8080/v1' not in old:
        p['baseUrl'] = 'http://aigw-local.hiclaw.io:8080/v1'
        print('Patched ' + name + ' baseUrl: ' + old + ' -> ' + p['baseUrl'])
        changed = True
    for model in p.get('models', []):
        old_id = model.get('id', '')
        if old_id != model_name:
            model['id'] = model_name
            model['name'] = model_name
            print('Updated model: ' + old_id + ' -> ' + model_name)
            changed = True
        if model.pop('reasoning', None) is not None:
            print('Removed reasoning:true from ' + model.get('id', ''))
            changed = True

agents = cfg.get('agents', {}).get('defaults', {}).get('model', {})
old_primary = agents.get('primary', '')
if model_name not in old_primary:
    for name in providers.keys():
        agents['primary'] = name + '/' + model_name
        print('Updated primary: ' + old_primary + ' -> ' + agents['primary'])
        changed = True
        break

# Fix Matrix homeserver port: Tuwunel runs on 6167, NOT Higress gateway port 8080.
# create-worker.sh may generate the wrong port; always enforce 6167 here.
matrix_cfg = cfg.get('channels', {}).get('matrix', {})
hs = matrix_cfg.get('homeserver', '')
if hs and ':8080' in hs and 'matrix-local.hiclaw.io' in hs:
    fixed = hs.replace(':8080', ':6167')
    matrix_cfg['homeserver'] = fixed
    print('Fixed Matrix homeserver port: ' + hs + ' -> ' + fixed)
    changed = True

# Context pruning + concurrent boost (performance optimization)
if 'agents' not in cfg:
    cfg['agents'] = {}
if 'defaults' not in cfg['agents']:
    cfg['agents']['defaults'] = {}
defaults = cfg['agents']['defaults']
if defaults.get('maxConcurrent') != 8:
    defaults['maxConcurrent'] = 8
    print('Set maxConcurrent: 8')
    changed = True
if defaults.get('contextTokens') != 40000:
    defaults['contextTokens'] = 40000
    print('Set contextTokens: 40000')
    changed = True
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
    changed = True
if defaults.get('subagents', {}).get('maxConcurrent') != 8:
    defaults['subagents'] = {'maxConcurrent': 8}
    print('Set subagents.maxConcurrent: 8')
    changed = True

if changed:
    with open(cfg_path, 'w') as f:
        json.dump(cfg, f, indent=2)
    print('Saved changes to ' + cfg_path)
else:
    print('No changes needed for ${worker}')
" && log "  $worker config patched" || warn "  Failed to patch $worker config"

    # Sync patched config to MinIO
    mc cp "/root/hiclaw-fs/agents/$worker/openclaw.json" \
        "hiclaw/hiclaw-storage/agents/$worker/openclaw.json" 2>/dev/null \
        && log "  $worker openclaw.json synced to MinIO" \
        || warn "  MinIO sync skipped for $worker"
done

# =========================================================================
# Step 2c: Ensure Higress LLM route for DashScope/MiniMax exists
#
# setup-higress.sh creates an auto-generated route at / with NO API key.
# We create a more-specific route at /v1/ that injects the real API key.
# =========================================================================
log "Step 2c: Ensuring Higress LLM route..."

HIGRESS_AUTH="$(echo -n "${HICLAW_ADMIN_USER:-admin}:${HICLAW_ADMIN_PASSWORD:-admin1234}" | base64)"

# Determine the LLM host for the Host header from the base URL
LLM_HOST="${HICLAW_OPENAI_BASE_URL:-https://api.minimaxi.com/v1}"
# Extract hostname from URL (strip protocol and path)
LLM_HOST=$(echo "$LLM_HOST" | sed -E 's|^https?://||; s|/.*||')

# Wait for openai-compat.dns service source
log "  Waiting for openai-compat.dns service source..."
for i in $(seq 1 20); do
    SVC=$(curl -sf 'http://localhost:8001/v1/service-sources/openai-compat' 2>/dev/null || true)
    if echo "$SVC" | grep -q '"name":"openai-compat"'; then
        log "  openai-compat.dns ready"
        break
    fi
    if [ "$i" -eq 20 ]; then
        warn "  openai-compat.dns not found after 60s — LLM route may not work"
    fi
    sleep 3
done

# Build route JSON
ROUTE_JSON="{\"name\":\"llm-minimax-route\",\"domains\":[\"aigw-local.hiclaw.io\"],\"path\":{\"matchType\":\"PRE\",\"matchValue\":\"/v1/\",\"caseSensitive\":false},\"services\":[{\"name\":\"openai-compat.dns\",\"port\":443,\"weight\":100}],\"proxyNextUpstream\":{\"enabled\":true,\"attempts\":3,\"timeout\":120000,\"conditions\":[\"error\",\"timeout\",\"non_idempotent\"]},\"headerControl\":{\"enabled\":true,\"request\":{\"add\":[{\"key\":\"user-agent\",\"value\":\"HiClaw/v1.0.6\"}],\"set\":[{\"key\":\"Authorization\",\"value\":\"Bearer ${LLM_API_KEY}\"},{\"key\":\"Host\",\"value\":\"${LLM_HOST}\"}],\"remove\":[]}},\"authConfig\":{\"enabled\":false}}"

# PUT to update, fall back to POST to create
RESULT=$(curl -sf -X PUT 'http://localhost:8001/v1/routes/llm-minimax-route' \
    -H "Authorization: Basic $HIGRESS_AUTH" -H 'Content-Type: application/json' \
    -d "$ROUTE_JSON" 2>&1 || true)

if echo "$RESULT" | grep -q '"name":"llm-minimax-route"'; then
    log "  llm-minimax-route updated"
else
    curl -sf -X POST 'http://localhost:8001/v1/routes' \
        -H "Authorization: Basic $HIGRESS_AUTH" -H 'Content-Type: application/json' \
        -d "$ROUTE_JSON" 2>&1 \
        && log "  llm-minimax-route created" \
        || warn "  Failed to create/update LLM route"
fi

# =========================================================================
# Step 3: Wait for Manager workspace, then inject SOUL.md + AGENTS.md
#
# The manager-agent creates /root/manager-workspace/ asynchronously after
# openclaw-gateway starts. We must wait for it before injecting.
# =========================================================================
log "Step 3: Waiting for Manager workspace to be ready..."

for i in $(seq 1 60); do
    if [ -f "$MANAGER_WORKSPACE/SOUL.md" ]; then
        log "  Manager workspace ready (SOUL.md exists after ${i}x5s)"
        break
    fi
    if [ "$i" -eq 60 ]; then
        warn "  Manager workspace not ready after 5 min — skipping SOUL.md injection"
    fi
    sleep 5
done

if [ -f "$MANAGER_WORKSPACE/SOUL.md" ]; then
    log "Step 3b: Injecting Manager SOUL.md and AGENTS.md..."

    inject_after_marker \
        "$MANAGER_WORKSPACE/SOUL.md" \
        "$HB_CONFIG/manager/agent/SOUL.md" \
        "Manager SOUL.md"

    inject_after_marker \
        "$MANAGER_WORKSPACE/AGENTS.md" \
        "$HB_CONFIG/manager/agent/AGENTS.md" \
        "Manager AGENTS.md"

    # Sync Manager agent files to MinIO for persistence
    mc cp "$MANAGER_WORKSPACE/SOUL.md" hiclaw/hiclaw-storage/agents/manager/SOUL.md 2>/dev/null \
        && log "  Manager SOUL.md synced to MinIO" || true
    mc cp "$MANAGER_WORKSPACE/AGENTS.md" hiclaw/hiclaw-storage/agents/manager/AGENTS.md 2>/dev/null \
        && log "  Manager AGENTS.md synced to MinIO" || true

    # CRITICAL: The openclaw agent workspace is /root, so it reads /root/SOUL.md.
    # The inject step above writes to $MANAGER_WORKSPACE/SOUL.md (a subdirectory),
    # but the agent never looks there. Copy to /root/ so the agent actually uses
    # the HoneyBadge SOUL.md (not the generic default from the Docker image).
    cp "$MANAGER_WORKSPACE/SOUL.md" /root/SOUL.md \
        && log "  Copied SOUL.md to /root/ for agent workspace" \
        || warn "  Failed to copy SOUL.md to /root/"
    cp "$MANAGER_WORKSPACE/AGENTS.md" /root/AGENTS.md \
        && log "  Copied AGENTS.md to /root/ for agent workspace" \
        || warn "  Failed to copy AGENTS.md to /root/"

    # HEARTBEAT.md is the Manager's periodic task-check loop. Without this,
    # the heartbeat runs but finds nothing to do — results never get pulled
    # from MinIO shared storage and sent to the admin DM room.
    # IMPORTANT: openclaw-gateway (started by supervisord) creates its own
    # default HEARTBEAT.md at startup. We must copy our version AFTER that
    # process exists, otherwise our copy gets overwritten.
    # Wait for openclaw-gateway process to appear before copying.
    log "  Waiting for openclaw-gateway to start (so we overwrite its default HEARTBEAT.md)..."
    for i in $(seq 1 20); do
        if pgrep -x "openclaw-gateway" > /dev/null 2>&1; then
            log "  openclaw-gateway is running."
            break
        fi
        sleep 2
    done
    if [ -f "$MANAGER_WORKSPACE/HEARTBEAT.md" ]; then
        cp "$MANAGER_WORKSPACE/HEARTBEAT.md" /root/HEARTBEAT.md \
            && log "  Copied HEARTBEAT.md to /root/ for heartbeat loop" \
            || warn "  Failed to copy HEARTBEAT.md to /root/"
    fi
fi

# =========================================================================
# Step 4: Patch Manager allowlist for @hb-* users
# =========================================================================
log "Step 4: Patching Manager allowlist..."

python3 -c "
import json, os

cfg_path = '$MANAGER_WORKSPACE/openclaw.json'
if not os.path.exists(cfg_path):
    print('Manager openclaw.json not found at ' + cfg_path)
    exit(0)

with open(cfg_path) as f:
    cfg = json.load(f)

domain = '$MATRIX_DOMAIN'
hb_users = [
    '@admin:' + domain,
    '@hb-admin:' + domain,
    '@hb-analyst:' + domain,
    '@hb-auditor:' + domain,
    '@hb-procurement_lead:' + domain,
    '@hb-subsidiary_lead:' + domain,
    '@honeybadge-gateway:' + domain,
]

channels = cfg.setdefault('channels', {}).setdefault('matrix', {})
channels['dm'] = {'policy': 'allowlist', 'allowFrom': hb_users}
channels['groupAllowFrom'] = hb_users

# Remove reasoning:true from all models
for p in cfg.get('models', {}).get('providers', {}).values():
    for m in p.get('models', []):
        if m.pop('reasoning', None) is not None:
            print('Removed reasoning:true from ' + m.get('id', ''))

with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2)
print('Manager allowlist patched')
" && log "  Manager allowlist updated" || warn "  Failed to patch Manager allowlist"

# Sync Manager config to MinIO
mc cp "$MANAGER_WORKSPACE/openclaw.json" \
    hiclaw/hiclaw-storage/agents/manager/openclaw.json 2>/dev/null \
    && log "  Manager openclaw.json synced to MinIO" \
    || warn "  MinIO sync skipped"

# =========================================================================
# Done
# =========================================================================
log "HoneyBadge auto-init complete!"
log "Workers will pick up configs from MinIO on (re)start."
