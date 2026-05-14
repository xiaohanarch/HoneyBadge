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
GENERATE_WORKER_CFG="/opt/hiclaw/agent/skills/worker-management/scripts/generate-worker-config.sh"
MATRIX_DOMAIN="${HICLAW_MATRIX_DOMAIN:-matrix-local.hiclaw.io}"
MATRIX_URL="${HICLAW_MATRIX_URL:-http://${MATRIX_DOMAIN}:6167}"
LLM_API_KEY="${HICLAW_LLM_API_KEY:-${LLM_API_KEY:-}}"
REGISTRY_FILE="${MANAGER_WORKSPACE}/workers-registry.json"
MANAGER_MXID="@manager:${MATRIX_DOMAIN}"

# Dev gateway mode: in compose on WSL2, Higress segfaults so an nginx sidecar
# (hiclaw-aigw-bypass) handles /v1/* instead. When set to "nginx-bypass" we
# skip Higress consumer/route wiring; production k3s always uses real Higress.
DEV_GATEWAY="${HICLAW_DEV_GATEWAY:-higress}"

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

# ---------------------------------------------------------------------------
# v1.1.0 split: ensure mc alias points at hiclaw-embedded MinIO
# (upstream may have pre-configured 'hiclaw' to localhost which is now empty)
# ---------------------------------------------------------------------------
if command -v mc >/dev/null 2>&1; then
    mc alias set hiclaw \
        "http://hiclaw-embedded:9000" \
        "${HICLAW_ADMIN_USER:-admin}" \
        "${HICLAW_ADMIN_PASSWORD:-admin1234}" \
        --api S3v4 >/dev/null 2>&1 || warn "  mc alias set 'hiclaw' failed (will retry on first use)"

    # Ensure hiclaw-storage bucket exists. v1.1.0 split moved MinIO from the
    # manager Pod (where the bucket was pre-seeded by the upstream image) to
    # hiclaw-embedded, which boots with an empty MinIO. Step 1's `mc cp`
    # silently fails if the bucket is missing; create it idempotently here.
    mc mb --ignore-existing hiclaw/hiclaw-storage >/dev/null 2>&1 \
        && log "  hiclaw-storage bucket ready (created or already present)" \
        || warn "  mc mb hiclaw/hiclaw-storage failed (MinIO may not be ready yet)"
fi

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

    # Ensure AGENTS.md exists. v1.1.0 worker-entrypoint.sh hard-requires
    # openclaw.json + SOUL.md + AGENTS.md before it will start the agent.
    # The HoneyBadge config tree ships only SOUL.md & skills/ for workers
    # (AGENTS.md was historically generated by the removed create-worker.sh),
    # so generate a minimal placeholder if no source AGENTS.md is present.
    AGENTS_SRC="$HB_CONFIG/workers/$worker/agent/AGENTS.md"
    if [ -f "$AGENTS_SRC" ]; then
        mc cp "$AGENTS_SRC" "hiclaw/hiclaw-storage/agents/$worker/AGENTS.md"
        log "  $worker/AGENTS.md uploaded to MinIO"
    else
        TMP_AGENTS=$(mktemp)
        cat > "$TMP_AGENTS" <<AGENTS_EOF
# AGENTS.md — ${worker}

You are **@${worker}**, a HoneyBadge worker agent reporting to **@manager**.

## Team

- **@manager** — your team leader. Read tasks from DMs from @manager.
- **@graph-worker** — sibling worker (graph queries).
- **@analytics-worker** — sibling worker (analytics).

## Responsibilities

See your \`SOUL.md\` for role-specific behavior. Follow the workflows
described in your skills under \`/root/skills/\`.

## Communication

- Receive tasks from @manager via Matrix DM.
- Push intermediate artifacts to MinIO under \`agents/${worker}/\`.
- Report completion back to @manager with a summary + artifact location.
AGENTS_EOF
        mc cp "$TMP_AGENTS" "hiclaw/hiclaw-storage/agents/$worker/AGENTS.md" >/dev/null 2>&1 \
            && log "  $worker/AGENTS.md (minimal placeholder) uploaded to MinIO" \
            || warn "  Failed to upload $worker/AGENTS.md to MinIO"
        rm -f "$TMP_AGENTS"
    fi
done

# =========================================================================
# Step 1b: Symlink /root/openclaw.json -> /root/manager-workspace/openclaw.json
#
# v1.0.9 LEGACY (kept for safety): create-worker.sh used to hardcode
# MANAGER_CONFIG="${HOME}/openclaw.json" and abort if missing. v1.1.0
# replaced create-worker.sh with generate-worker-config.sh, which does NOT
# read /root/openclaw.json — making this section dead-but-harmless code.
# The symlink itself (if created) costs nothing; we leave the section in
# place so a downgrade path stays available, and the warning is benign.
# =========================================================================
log "Step 1b: Ensuring /root/openclaw.json symlink (v1.0.9 compatibility)..."

MANAGER_OPENCLAW="$MANAGER_WORKSPACE/openclaw.json"
ROOT_OPENCLAW="/root/openclaw.json"

for i in $(seq 1 24); do
    if [ -f "$MANAGER_OPENCLAW" ]; then
        break
    fi
    sleep 5
done

if [ -f "$MANAGER_OPENCLAW" ]; then
    # Replace any existing file/symlink with a symlink to the real config.
    if [ ! -L "$ROOT_OPENCLAW" ] || [ "$(readlink "$ROOT_OPENCLAW")" != "$MANAGER_OPENCLAW" ]; then
        rm -f "$ROOT_OPENCLAW"
        ln -s "$MANAGER_OPENCLAW" "$ROOT_OPENCLAW"
        log "  Symlinked $ROOT_OPENCLAW -> $MANAGER_OPENCLAW"
    else
        log "  Symlink already in place"
    fi
else
    warn "  Manager openclaw.json not ready after 120s — Step 4 (allowlist patch) may also fail"
fi

# =========================================================================
# Step 2: Register workers (v1.1.0 flow)
#
# v1.1.0 removed create-worker.sh. The manager-agent skill ships
# generate-worker-config.sh which produces openclaw.json given a Matrix
# access token + LLM gateway key. We must perform Matrix registration
# and secret generation ourselves (in real k8s the controller does this).
#
# Idempotency: skip if openclaw.json already exists in MinIO. If the
# Matrix user already exists from a prior boot but MinIO is empty, fall
# back to login using the persisted /data/worker-creds/<worker>.env.
# =========================================================================
log "Step 2: Registering workers..."

REG_TOKEN="${HICLAW_REGISTRATION_TOKEN:-honeybadge-reg-token}"
DEFAULT_MODEL="${HICLAW_DEFAULT_MODEL:-glm-5}"
WORKER_CREDS_DIR="/data/worker-creds"
mkdir -p "$WORKER_CREDS_DIR"

# Extract Manager Matrix access token from openclaw.json (set by openclaw-gateway
# after login). Used to auto-join Manager↔Worker DM rooms created below so the
# Manager can both send dispatches and receive replies.
MANAGER_TOKEN=""
if [ -f "$MANAGER_OPENCLAW" ]; then
    MANAGER_TOKEN=$(python3 -c "
import json
try:
    with open('$MANAGER_OPENCLAW') as f:
        cfg = json.load(f)
    print(cfg.get('channels', {}).get('matrix', {}).get('accessToken', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")
fi
if [ -z "$MANAGER_TOKEN" ]; then
    warn "  Manager Matrix accessToken not yet available — DM rooms may not get joined"
fi

for worker in graph-worker analytics-worker; do
    # Load any previously persisted state for this worker (room_id etc.)
    WORKER_ROOM_ID=""
    if [ -f "${WORKER_CREDS_DIR}/${worker}.env" ]; then
        # shellcheck disable=SC1090
        WORKER_ROOM_ID=$(. "${WORKER_CREDS_DIR}/${worker}.env" 2>/dev/null && echo "${WORKER_ROOM_ID:-}")
    fi
    # Idempotency: skip fresh Matrix registration + config generation if
    # MinIO already has the worker config. We deliberately do NOT `continue`
    # here — the workers-registry.json refresh at the end of this loop must
    # run on every boot, otherwise the registry stays {"workers": {}} after
    # the first successful provisioning and Manager forgets its team.
    NEEDS_FRESH_REGISTRATION=true
    if mc stat "hiclaw/hiclaw-storage/agents/$worker/openclaw.json" >/dev/null 2>&1; then
        log "  $worker openclaw.json already in MinIO — skipping fresh registration"
        NEEDS_FRESH_REGISTRATION=false
    fi

    if [ "$NEEDS_FRESH_REGISTRATION" = "true" ]; then

    log "  Registering $worker on Matrix..."

    WORKER_TOKEN=""
    WORKER_PWD=""

    # Fresh registration path
    GEN_PWD=$(openssl rand -base64 24 | tr -d '=+/' | head -c 32)
    REG_BODY="{\"username\":\"${worker}\",\"password\":\"${GEN_PWD}\",\"auth\":{\"type\":\"m.login.registration_token\",\"token\":\"${REG_TOKEN}\"}}"
    REG_RESULT=$(curl -sf -X POST "${MATRIX_URL}/_matrix/client/v3/register" \
        -H 'Content-Type: application/json' -d "$REG_BODY" 2>&1) || true

    WORKER_TOKEN=$(echo "$REG_RESULT" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("access_token", ""))
except Exception:
    print("")
' 2>/dev/null || echo "")

    if [ -n "$WORKER_TOKEN" ]; then
        WORKER_PWD="$GEN_PWD"
        log "  $worker Matrix registration ok"
    elif echo "$REG_RESULT" | grep -q 'M_USER_IN_USE'; then
        # User already exists — try login with persisted creds
        if [ -f "${WORKER_CREDS_DIR}/${worker}.env" ]; then
            # shellcheck disable=SC1090
            EXISTING_PWD=$(. "${WORKER_CREDS_DIR}/${worker}.env" 2>/dev/null && echo "$WORKER_PASSWORD")
            if [ -n "$EXISTING_PWD" ]; then
                LOGIN_BODY="{\"type\":\"m.login.password\",\"identifier\":{\"type\":\"m.id.user\",\"user\":\"${worker}\"},\"password\":\"${EXISTING_PWD}\"}"
                LOGIN_RESULT=$(curl -sf -X POST "${MATRIX_URL}/_matrix/client/v3/login" \
                    -H 'Content-Type: application/json' -d "$LOGIN_BODY" 2>&1) || true
                WORKER_TOKEN=$(echo "$LOGIN_RESULT" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("access_token", ""))
except Exception:
    print("")
' 2>/dev/null || echo "")
                if [ -n "$WORKER_TOKEN" ]; then
                    WORKER_PWD="$EXISTING_PWD"
                    log "  $worker exists — recovered via login from persisted creds"
                fi
            fi
        fi
    else
        warn "  $worker register call failed: $REG_RESULT"
    fi

    if [ -z "$WORKER_TOKEN" ]; then
        warn "  Could not obtain Matrix token for $worker — skipping config generation"
        continue
    fi

    # Ensure a Manager↔Worker DM room exists. dispatch-to-worker.sh reads
    # workers-registry.json and requires `room_id` + `matrix_user_id` to send
    # tasks; without a real room the dispatcher errors out with KeyError.
    # Idempotent: skip if we already have a persisted WORKER_ROOM_ID.
    if [ -z "$WORKER_ROOM_ID" ]; then
        ROOM_BODY="{\"preset\":\"trusted_private_chat\",\"invite\":[\"${MANAGER_MXID}\"],\"is_direct\":true,\"name\":\"manager-${worker}\"}"
        ROOM_RESULT=$(curl -sf -X POST "${MATRIX_URL}/_matrix/client/v3/createRoom" \
            -H "Authorization: Bearer $WORKER_TOKEN" \
            -H 'Content-Type: application/json' \
            -d "$ROOM_BODY" 2>&1) || ROOM_RESULT=""
        WORKER_ROOM_ID=$(echo "$ROOM_RESULT" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("room_id", ""))
except Exception:
    print("")
' 2>/dev/null || echo "")
        if [ -n "$WORKER_ROOM_ID" ]; then
            log "  $worker DM room created: $WORKER_ROOM_ID"
            # Make Manager join so dispatch.sh sends + replies both work
            if [ -n "$MANAGER_TOKEN" ]; then
                curl -sf -X POST "${MATRIX_URL}/_matrix/client/v3/rooms/${WORKER_ROOM_ID}/join" \
                    -H "Authorization: Bearer $MANAGER_TOKEN" \
                    -H 'Content-Type: application/json' \
                    -d '{}' >/dev/null 2>&1 \
                    && log "  Manager joined $worker DM room" \
                    || warn "  Manager failed to join $worker DM room (will retry on next boot)"
            fi
        else
            warn "  $worker DM room creation failed: $ROOM_RESULT"
        fi
    fi

    # Generate gateway key. In nginx-bypass mode this value is stripped &
    # replaced by the bypass nginx; in real Higress mode it must be registered
    # as a key-auth credential on the worker's Higress consumer.
    WORKER_GW_KEY=$(openssl rand -hex 16)

    # Run v1.1.0 generate-worker-config.sh — this produces openclaw.json and
    # uploads it to MinIO (per the script's own contract).
    if [ ! -x "$GENERATE_WORKER_CFG" ] && [ ! -f "$GENERATE_WORKER_CFG" ]; then
        warn "  generate-worker-config.sh not found at $GENERATE_WORKER_CFG"
        continue
    fi

    bash "$GENERATE_WORKER_CFG" "$worker" "$WORKER_TOKEN" "$WORKER_GW_KEY" "$DEFAULT_MODEL" 2>&1 \
        && log "  $worker openclaw.json generated" \
        || warn "  generate-worker-config.sh failed for $worker"

    # Upload the freshly-generated config to MinIO immediately so that
    # idempotency check passes on next boot even if Step 2b doesn't run.
    GEN_CFG="/root/hiclaw-fs/agents/${worker}/openclaw.json"
    if [ -f "$GEN_CFG" ]; then
        mc cp "$GEN_CFG" "hiclaw/hiclaw-storage/agents/$worker/openclaw.json" >/dev/null 2>&1 \
            && log "  $worker openclaw.json uploaded to MinIO" \
            || warn "  Failed to upload $worker openclaw.json to MinIO"
    fi

    # Persist password + room_id to /data/worker-creds + MinIO (controller-
    # injected secrets simulation; matches k8s consumer-credential pattern).
    # WORKER_ROOM_ID is read back at the top of this loop on subsequent boots
    # so we don't keep creating new DM rooms.
    {
        echo "WORKER_PASSWORD=${WORKER_PWD}"
        [ -n "$WORKER_ROOM_ID" ] && echo "WORKER_ROOM_ID=${WORKER_ROOM_ID}"
    } > "${WORKER_CREDS_DIR}/${worker}.env"
    chmod 600 "${WORKER_CREDS_DIR}/${worker}.env"
    echo "${WORKER_PWD}" | mc pipe "hiclaw/hiclaw-storage/agents/$worker/credentials/matrix/password" >/dev/null 2>&1 \
        && log "  $worker password persisted to MinIO" \
        || warn "  Failed to persist $worker password to MinIO"

    fi  # end NEEDS_FRESH_REGISTRATION

    # Self-heal: pre-existing deployments (MinIO already has worker config,
    # NEEDS_FRESH_REGISTRATION=false) won't have created a DM room above.
    # If we still have no WORKER_ROOM_ID but a persisted password exists,
    # do a login → create room → persist room_id. This makes the registry
    # schema fix retro-active without forcing re-provisioning.
    if [ -z "$WORKER_ROOM_ID" ] && [ -f "${WORKER_CREDS_DIR}/${worker}.env" ]; then
        # shellcheck disable=SC1090
        HEAL_PWD=$(. "${WORKER_CREDS_DIR}/${worker}.env" 2>/dev/null && echo "$WORKER_PASSWORD")
        if [ -n "$HEAL_PWD" ]; then
            HEAL_LOGIN_BODY="{\"type\":\"m.login.password\",\"identifier\":{\"type\":\"m.id.user\",\"user\":\"${worker}\"},\"password\":\"${HEAL_PWD}\"}"
            HEAL_LOGIN_RESULT=$(curl -sf -X POST "${MATRIX_URL}/_matrix/client/v3/login" \
                -H 'Content-Type: application/json' -d "$HEAL_LOGIN_BODY" 2>&1) || HEAL_LOGIN_RESULT=""
            HEAL_TOKEN=$(echo "$HEAL_LOGIN_RESULT" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("access_token", ""))
except Exception:
    print("")
' 2>/dev/null || echo "")
            if [ -n "$HEAL_TOKEN" ]; then
                ROOM_BODY="{\"preset\":\"trusted_private_chat\",\"invite\":[\"${MANAGER_MXID}\"],\"is_direct\":true,\"name\":\"manager-${worker}\"}"
                ROOM_RESULT=$(curl -sf -X POST "${MATRIX_URL}/_matrix/client/v3/createRoom" \
                    -H "Authorization: Bearer $HEAL_TOKEN" \
                    -H 'Content-Type: application/json' \
                    -d "$ROOM_BODY" 2>&1) || ROOM_RESULT=""
                WORKER_ROOM_ID=$(echo "$ROOM_RESULT" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("room_id", ""))
except Exception:
    print("")
' 2>/dev/null || echo "")
                if [ -n "$WORKER_ROOM_ID" ]; then
                    log "  $worker self-heal: DM room created: $WORKER_ROOM_ID"
                    if [ -n "$MANAGER_TOKEN" ]; then
                        curl -sf -X POST "${MATRIX_URL}/_matrix/client/v3/rooms/${WORKER_ROOM_ID}/join" \
                            -H "Authorization: Bearer $MANAGER_TOKEN" \
                            -H 'Content-Type: application/json' \
                            -d '{}' >/dev/null 2>&1 \
                            && log "  Manager joined $worker DM room (self-heal)" \
                            || warn "  Manager failed to join $worker DM room (self-heal)"
                    fi
                    # Persist room_id alongside existing password line
                    {
                        echo "WORKER_PASSWORD=${HEAL_PWD}"
                        echo "WORKER_ROOM_ID=${WORKER_ROOM_ID}"
                    } > "${WORKER_CREDS_DIR}/${worker}.env"
                    chmod 600 "${WORKER_CREDS_DIR}/${worker}.env"
                fi
            else
                warn "  $worker self-heal login failed: $HEAL_LOGIN_RESULT"
            fi
        fi
    fi

    # Update workers-registry.json (Manager reads this to know its team).
    # Runs unconditionally on every boot — the jq merge preserves the
    # original registered_at timestamp if it already exists, so this is
    # safe to repeat. Without this, the registry never gets populated when
    # MinIO already has the worker config (idempotent restart case).
    if [ -f "$REGISTRY_FILE" ]; then
        TMP_REG=$(mktemp)
        # Schema contract with dispatch-to-worker.sh:
        #   - `matrix_user_id` (NOT `matrix_id`) is what dispatch reads
        #   - `room_id` is the Manager↔Worker DM room created above
        # We keep `matrix_id` too for any older readers, but the canonical
        # fields are `matrix_user_id` + `room_id`. Preserve existing room_id
        # if already set so re-runs don't clobber a working room.
        if jq --arg name "$worker" \
              --arg matrix_id "@${worker}:${MATRIX_DOMAIN}" \
              --arg room "$WORKER_ROOM_ID" \
              --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
              '.workers[$name] = {
                  "name": $name,
                  "matrix_id": $matrix_id,
                  "matrix_user_id": $matrix_id,
                  "room_id": (.workers[$name].room_id // $room),
                  "runtime": "openclaw",
                  "deployment": "local",
                  "role": "worker",
                  "skills": ["file-sync", "mcporter"],
                  "registered_at": (.workers[$name].registered_at // $ts)
              } | .updated_at = $ts' \
              "$REGISTRY_FILE" > "$TMP_REG"; then
            mv "$TMP_REG" "$REGISTRY_FILE"
            log "  $worker present in workers-registry.json"
        else
            rm -f "$TMP_REG"
            warn "  Failed to update workers-registry.json for $worker"
        fi
    else
        warn "  workers-registry.json not found at $REGISTRY_FILE"
    fi
done

# Sync workers-registry.json back to MinIO so workers can see siblings
if [ -f "$REGISTRY_FILE" ]; then
    mc cp "$REGISTRY_FILE" "hiclaw/hiclaw-storage/agents/manager/workers-registry.json" 2>/dev/null \
        && log "  workers-registry.json synced to MinIO" \
        || warn "  workers-registry.json MinIO sync skipped"
fi

# =========================================================================
# Step 2b: Fix worker LLM baseUrl and model
#
# v1.1.0 generate-worker-config.sh writes to /root/hiclaw-fs/agents/<w>/openclaw.json
# (the manager container's local filesystem). We patch in-place there, then
# sync to MinIO — which is what workers actually read at startup.
#
# Worker baseUrl must end with /v1 (OpenAI JS SDK appends /chat/completions
# directly). The host alias `aigw-local.hiclaw.io` resolves to the bypass
# nginx in dev (HICLAW_DEV_GATEWAY=nginx-bypass) or real Higress in prod.
# =========================================================================
log "Step 2b: Patching worker LLM baseUrl and model..."

for worker in graph-worker analytics-worker; do
    LOCAL_CFG="/root/hiclaw-fs/agents/${worker}/openclaw.json"
    if [ ! -f "$LOCAL_CFG" ]; then
        warn "  $worker openclaw.json not at $LOCAL_CFG — skipping patch"
        continue
    fi

    python3 -c "
import json, os, sys

cfg_path = '$LOCAL_CFG'
if not os.path.exists(cfg_path):
    print('openclaw.json not found at ' + cfg_path)
    sys.exit(0)

with open(cfg_path) as f:
    cfg = json.load(f)

model_name = os.environ.get('HICLAW_DEFAULT_MODEL', 'glm-5')
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

# Allow plain http:// to matrix-local.hiclaw.io. The worker's matrix client
# (matrix-rust-sdk) rejects http:// unless the homeserver host is in private
# or loopback space. It checks the hostname STRING, not the resolved IP,
# so a private ClusterIP behind a .io hostname still fails the check.
# HiClaw's manager template already sets this flag (see
# /opt/hiclaw/configs/manager-openclaw.json.tmpl), but generate-worker-config.sh
# does not propagate it to workers. Mirror manager behavior here.
if matrix_cfg:
    network = matrix_cfg.get('network')
    if not isinstance(network, dict):
        network = {}
    if not network.get('dangerouslyAllowPrivateNetwork'):
        network['dangerouslyAllowPrivateNetwork'] = True
        matrix_cfg['network'] = network
        print('Enabled matrix.network.dangerouslyAllowPrivateNetwork=true')
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

    # Sync patched config back to MinIO (canonical source in v1.1.0)
    mc cp "$LOCAL_CFG" \
        "hiclaw/hiclaw-storage/agents/$worker/openclaw.json" 2>/dev/null \
        && log "  $worker openclaw.json synced to MinIO" \
        || warn "  MinIO sync skipped for $worker"
done

# =========================================================================
# Step 2c: Ensure Higress LLM route for Aliyun Bailian (DashScope) exists
#
# setup-higress.sh creates an auto-generated route at / with NO API key.
# We create a more-specific route at /v1/ that injects the real API key
# and rewrites the Host header so the openai-compat.dns upstream
# (coding.dashscope.aliyuncs.com:443 per the default McpBridge registry)
# accepts the request with the right vhost.
#
# DEV ONLY: skipped when HICLAW_DEV_GATEWAY=nginx-bypass — the bypass
# nginx (hiclaw-aigw-bypass) handles /v1/* directly. Production k3s
# always runs real Higress; this branch must execute on ECS.
# =========================================================================
if [ "$DEV_GATEWAY" = "nginx-bypass" ]; then
    log "Step 2c: SKIPPED (HICLAW_DEV_GATEWAY=nginx-bypass — using hiclaw-aigw-bypass sidecar)"
else
    log "Step 2c: Ensuring Higress LLM route..."

    HIGRESS_AUTH="$(echo -n "${HICLAW_ADMIN_USER:-admin}:${HICLAW_ADMIN_PASSWORD:-admin1234}" | base64)"

    # Determine the LLM host for the Host header from the base URL.
    # Default falls back to Aliyun Bailian (DashScope) coding endpoint,
    # matching the McpBridge openai-compat upstream registered by Higress.
    LLM_HOST="${HICLAW_OPENAI_BASE_URL:-https://coding.dashscope.aliyuncs.com/v1}"
    # Extract hostname from URL (strip protocol and path)
    LLM_HOST=$(echo "$LLM_HOST" | sed -E 's|^https?://||; s|/.*||')

    # Wait for openai-compat.dns service source
    log "  Waiting for openai-compat.dns service source..."
    for i in $(seq 1 20); do
        SVC=$(curl -sf 'http://hiclaw-embedded:8001/v1/service-sources/openai-compat' 2>/dev/null || true)
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
    ROUTE_JSON="{\"name\":\"llm-minimax-route\",\"domains\":[\"aigw-local.hiclaw.io\"],\"path\":{\"matchType\":\"PRE\",\"matchValue\":\"/v1/\",\"caseSensitive\":false},\"services\":[{\"name\":\"openai-compat.dns\",\"port\":443,\"weight\":100}],\"proxyNextUpstream\":{\"enabled\":true,\"attempts\":3,\"timeout\":120000,\"conditions\":[\"error\",\"timeout\",\"non_idempotent\"]},\"headerControl\":{\"enabled\":true,\"request\":{\"add\":[{\"key\":\"user-agent\",\"value\":\"HiClaw/v1.0.9\"}],\"set\":[{\"key\":\"Authorization\",\"value\":\"Bearer ${LLM_API_KEY}\"},{\"key\":\"Host\",\"value\":\"${LLM_HOST}\"}],\"remove\":[]}},\"authConfig\":{\"enabled\":false}}"

    # PUT to update, fall back to POST to create
    RESULT=$(curl -sf -X PUT 'http://hiclaw-embedded:8001/v1/routes/llm-minimax-route' \
        -H "Authorization: Basic $HIGRESS_AUTH" -H 'Content-Type: application/json' \
        -d "$ROUTE_JSON" 2>&1 || true)

    if echo "$RESULT" | grep -q '"name":"llm-minimax-route"'; then
        log "  llm-minimax-route updated"
    else
        curl -sf -X POST 'http://hiclaw-embedded:8001/v1/routes' \
            -H "Authorization: Basic $HIGRESS_AUTH" -H 'Content-Type: application/json' \
            -d "$ROUTE_JSON" 2>&1 \
            && log "  llm-minimax-route created" \
            || warn "  Failed to create/update LLM route"
    fi
fi

# =========================================================================
# Step 2d: Create/update Higress manager consumer (v1.1.0 k8s-mode parity)
#
# In real k8s, the controller registers the manager as a Higress consumer
# with key-auth using HICLAW_MANAGER_GATEWAY_KEY. The slim manager-agent
# uses this token to call MCP servers via the gateway.
#
# In Compose we simulate the controller by creating the consumer here.
# Idempotent: PUT first, fall back to POST.
#
# DEV ONLY: skipped when HICLAW_DEV_GATEWAY=nginx-bypass — the bypass
# nginx does not enforce key-auth (it strips inbound Authorization and
# injects the upstream LLM key). Production k3s requires this branch.
# =========================================================================
if [ "$DEV_GATEWAY" = "nginx-bypass" ]; then
    log "Step 2d: SKIPPED (HICLAW_DEV_GATEWAY=nginx-bypass — bypass nginx does not enforce key-auth)"
else
    log "Step 2d: Ensuring Higress manager consumer..."

    MGR_GW_KEY="${HICLAW_MANAGER_GATEWAY_KEY:-}"
    if [ -z "$MGR_GW_KEY" ]; then
        warn "  HICLAW_MANAGER_GATEWAY_KEY not set — skipping consumer registration"
    else
        CONSUMER_JSON="{\"name\":\"manager\",\"credentials\":[{\"type\":\"key-auth\",\"source\":\"BEARER\",\"values\":[\"${MGR_GW_KEY}\"]}]}"
        RESULT=$(curl -sf -X PUT 'http://hiclaw-embedded:8001/v1/consumers/manager' \
            -H "Authorization: Basic $HIGRESS_AUTH" -H 'Content-Type: application/json' \
            -d "$CONSUMER_JSON" 2>&1 || true)
        if echo "$RESULT" | grep -q '"name":"manager"'; then
            log "  manager consumer updated"
        else
            curl -sf -X POST 'http://hiclaw-embedded:8001/v1/consumers' \
                -H "Authorization: Basic $HIGRESS_AUTH" -H 'Content-Type: application/json' \
                -d "$CONSUMER_JSON" 2>&1 \
                && log "  manager consumer created" \
                || warn "  Failed to create/update manager consumer"
        fi
    fi
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

# Workers must be allowed to send in group rooms so the Manager can receive
# their completion messages and forward results to the user DM. Without this,
# worker replies in group rooms are dropped by groupAllowFrom and
# result-watcher never sees the completion signal.
# Mirrors deploy/hiclaw/init-workers.sh which sets the same combined list
# in the docker-compose flow; this keeps k8s parity with compose.
workers = [
    '@graph-worker:' + domain,
    '@analytics-worker:' + domain,
]

channels = cfg.setdefault('channels', {}).setdefault('matrix', {})
channels['dm'] = {'policy': 'allowlist', 'allowFrom': hb_users}
channels['groupAllowFrom'] = hb_users + workers

# Fix Manager LLM baseUrl (template generates http://:8080/v1 if HICLAW_AI_GATEWAY_DOMAIN unset)
for name, p in cfg.get('models', {}).get('providers', {}).items():
    old = p.get('baseUrl', '')
    if old and 'aigw-local.hiclaw.io:8080/v1' not in old:
        p['baseUrl'] = 'http://aigw-local.hiclaw.io:8080/v1'
        print('Patched Manager provider ' + name + ' baseUrl: ' + repr(old) + ' -> ' + p['baseUrl'])

# Remove reasoning:true from all models
for p in cfg.get('models', {}).get('providers', {}).values():
    for m in p.get('models', []):
        if m.pop('reasoning', None) is not None:
            print('Removed reasoning:true from ' + m.get('id', ''))

# Note: the v1.0.x memorySearch pop() workaround was removed in v1.1.0.
# v1.1.0 only injects agents.defaults.memorySearch when HICLAW_EMBEDDING_MODEL
# is non-empty (see /opt/hiclaw/scripts/init/start-manager-agent.sh and
# /opt/hiclaw/scripts/lib/hiclaw-env.sh: `HICLAW_EMBEDDING_MODEL="${HICLAW_EMBEDDING_MODEL-text-embedding-v4}"`).
# docker-compose.yaml sets HICLAW_EMBEDDING_MODEL="" explicitly so the upstream
# never injects memorySearch in the first place, making this scrub a no-op.
# Evidence: docs/1.1.0-upgrade-evidence/bucket1-memorysearch-default-check.log.

# Context pruning — prevents unbounded Manager context growth (mirrors Worker settings)
mgr_defaults = cfg.setdefault('agents', {}).setdefault('defaults', {})
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
print('Manager allowlist patched, context pruning applied')
" && log "  Manager allowlist updated" || warn "  Failed to patch Manager allowlist"

# Sync Manager config to MinIO
mc cp "$MANAGER_WORKSPACE/openclaw.json" \
    hiclaw/hiclaw-storage/agents/manager/openclaw.json 2>/dev/null \
    && log "  Manager openclaw.json synced to MinIO" \
    || warn "  MinIO sync skipped"

# =========================================================================
# Step 5: REMOVED in v1.1.0 upgrade
#
# v1.0.9 had a hot-reload deadlock workaround that killed openclaw-gateway
# so supervisord would respawn it. v1.1.0's slim manager image dropped
# supervisord — there is no respawner. Killing the process here would now
# kill the container itself (PID 1 chain), causing a restart loop.
#
# v1.1.0's native manager-agent does not exhibit the v1.0.9 hot-reload
# deadlock; this workaround is dead code and dangerous, so it is removed.
# =========================================================================

# =========================================================================
# Done
# =========================================================================
log "HoneyBadge auto-init complete!"
log "Workers will pick up configs from MinIO on (re)start."
