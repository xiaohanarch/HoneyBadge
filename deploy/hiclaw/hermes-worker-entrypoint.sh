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

# Create underscore symlinks for hyphenated skill directories.
# Python cannot import directories with hyphens (e.g. anomaly-detection),
# but SKILL.md/SOUL.md reference python3 -m anomaly_detection.lib.detect.
create_skill_symlinks() {
    local skills_dir="${HERMES_HOME}/skills"
    [ -d "$skills_dir" ] || return 0
    for d in "$skills_dir"/*/; do
        [ -d "$d" ] || continue
        local name=$(basename "$d")
        case "$name" in
            *-*)
                local underscored=$(echo "$name" | tr '-' '_')
                ln -sfn "$name" "$skills_dir/$underscored" 2>/dev/null || true
                ;;
        esac
    done
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
    create_skill_symlinks
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

(
    while true; do
        sleep 300
        mc mirror "hiclaw/hiclaw-storage/shared/" "${HICLAW_ROOT}/shared/" --overwrite --newer-than "5m" 2>/dev/null || true
        mc mirror "hiclaw/hiclaw-storage/agents/${WORKER_NAME}/skills/" "${HERMES_HOME}/skills/" --overwrite 2>/dev/null || true
        create_skill_symlinks
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
        NEW_USER_ID=$(echo "${LOGIN_RESP}" | jq -r '.user_id // empty' 2>/dev/null)
        if [ -n "${NEW_TOKEN}" ] && [ "${NEW_TOKEN}" != "null" ]; then
            sed -i "s|^MATRIX_ACCESS_TOKEN=.*|MATRIX_ACCESS_TOKEN=${NEW_TOKEN}|" "${HERMES_HOME}/.env"
            sed -i "s|access_token:.*|access_token: ${NEW_TOKEN}|" "${HERMES_HOME}/config.yaml"
            if [ -n "${NEW_USER_ID}" ] && [ "${NEW_USER_ID}" != "null" ]; then
                sed -i "s|^MATRIX_USER_ID=.*|MATRIX_USER_ID=${NEW_USER_ID}|" "${HERMES_HOME}/.env"
                sed -i "s|user_id:.*|user_id: \"${NEW_USER_ID}\"|" "${HERMES_HOME}/config.yaml"
            fi
            log "Matrix re-login successful (token prefix: ${NEW_TOKEN:0:10}...)"
        else
            log "WARNING: Matrix re-login failed, using existing token"
        fi
    fi
    MATRIX_PASSWORD=""
fi

# --- Step 8: Launch hermes gateway (foreground, for Docker) ---
log "Starting Hermes Gateway: ${WORKER_NAME}"
cd "${HERMES_HOME}"

# Ensure model is set in hermes's internal state (config bridge writes config.yaml,
# but hermes model selection also needs this for the gateway runtime)
MODEL_FROM_CONFIG=$(python3 -c "
import yaml
try:
    with open('${HERMES_HOME}/config.yaml') as f:
        print(yaml.safe_load(f).get('model', ''))
except Exception:
    pass
" 2>/dev/null || true)

if [ -n "$MODEL_FROM_CONFIG" ]; then
    export HERMES_ACCEPT_HOOKS=1
    hermes config set model "$MODEL_FROM_CONFIG" 2>/dev/null || true
    log "Model set: ${MODEL_FROM_CONFIG}"
fi

# Run gateway in foreground (recommended for Docker/WSL/Termux)
exec hermes gateway run --accept-hooks
