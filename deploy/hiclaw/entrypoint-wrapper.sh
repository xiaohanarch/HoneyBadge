#!/bin/bash
# HoneyBadge Manager Entrypoint Wrapper
#
# Spawns the HoneyBadge init process in the background, then hands off
# to the v1.1.0 slim Manager image's native entrypoint as PID 1.
#
# v1.0.9 used supervisord (since the all-in-one image bundled Tuwunel +
# MinIO + Higress + agent under one supervisor tree). v1.1.0 split that
# infra into hiclaw-embedded; the slim manager image no longer ships
# supervisord. Its native entrypoint is start-manager-agent.sh, which
# acts as container entrypoint when HICLAW_RUNTIME=k8s (set in compose).
#
# Mounted into the Manager container via docker-compose volume:
#   ../hiclaw/entrypoint-wrapper.sh:/opt/honeybadge/init/entrypoint-wrapper.sh:ro

set -u

INIT_SCRIPT="/opt/honeybadge/init/manager-init-internal.sh"
LOG_DIR="/var/log/hiclaw"
LOG_FILE="$LOG_DIR/honeybadge-init.log"

mkdir -p "$LOG_DIR"

echo "[entrypoint] Starting HoneyBadge auto-init in background..." | tee -a "$LOG_FILE"

(
    # Wait for MinIO on hiclaw-embedded to be ready (after v1.1.0 split,
    # MinIO no longer runs inside this container).
    echo "[init-bg] Waiting for MinIO on hiclaw-embedded..."
    while ! curl -sf http://hiclaw-embedded:9000/minio/health/live >/dev/null 2>&1; do
        sleep 5
    done
    echo "[init-bg] MinIO is ready."

    # Wait for Tuwunel Matrix homeserver on hiclaw-embedded.
    # In k8s deployments the controller pre-registers @manager before the
    # manager-agent container starts. Compose has no controller, so we must
    # register the @manager account ourselves before manager-agent attempts
    # to log in (otherwise it fails fast on M_FORBIDDEN).
    MATRIX_URL="${HICLAW_MATRIX_URL:-http://matrix-local.hiclaw.io:6167}"
    echo "[init-bg] Waiting for Tuwunel at $MATRIX_URL..."
    for _i in $(seq 1 60); do
        if curl -sf "$MATRIX_URL/_matrix/client/versions" >/dev/null 2>&1; then
            echo "[init-bg] Tuwunel is ready."
            break
        fi
        sleep 5
    done

    # Idempotent @manager registration. v1 register endpoint returns:
    #   200 + access_token on success
    #   400 with errcode=M_USER_IN_USE if already registered (treat as success)
    REG_TOKEN="${HICLAW_REGISTRATION_TOKEN:-honeybadge-reg-token}"
    MGR_PWD="${HICLAW_MANAGER_PASSWORD:-}"
    if [ -z "$MGR_PWD" ]; then
        echo "[init-bg] WARN: HICLAW_MANAGER_PASSWORD empty — skipping @manager registration"
    else
        REG_BODY="{\"username\":\"manager\",\"password\":\"${MGR_PWD}\",\"auth\":{\"type\":\"m.login.registration_token\",\"token\":\"${REG_TOKEN}\"}}"
        for _attempt in 1 2 3 4 5; do
            REG_RESULT=$(curl -sf -X POST "$MATRIX_URL/_matrix/client/v3/register" \
                -H 'Content-Type: application/json' \
                -d "$REG_BODY" 2>&1) || true
            if echo "$REG_RESULT" | grep -qE '"access_token"|M_USER_IN_USE'; then
                echo "[init-bg] @manager registration ok (attempt=$_attempt)."
                break
            fi
            echo "[init-bg] @manager register attempt $_attempt failed; retrying..."
            sleep 5
        done
    fi

    # Wait for Manager Agent to initialize (openclaw-gateway needs ~15s after MinIO)
    echo "[init-bg] Waiting 20s for Manager Agent to start..."
    sleep 20

    # Run the init script
    if [ -f "$INIT_SCRIPT" ]; then
        echo "[init-bg] Running HoneyBadge init..."
        bash "$INIT_SCRIPT" 2>&1
        echo "[init-bg] Init completed with exit code $?."
    else
        echo "[init-bg] ERROR: Init script not found at $INIT_SCRIPT"
    fi
) >> "$LOG_FILE" 2>&1 &

# Hand off to the v1.1.0 native manager-agent entrypoint as PID 1.
# Requires HICLAW_RUNTIME=k8s in the environment so start-manager-agent.sh
# runs in container-entrypoint mode (see slim image's start-manager-agent.sh
# branches on this var; "k8s" is the documented container-entrypoint runtime).
exec /opt/hiclaw/scripts/init/start-manager-agent.sh
