#!/bin/bash
# HoneyBadge Manager Entrypoint Wrapper
#
# Spawns the HoneyBadge init process in the background, then hands off
# to supervisord as PID 1 (proper signal handling via exec).
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
    # Wait for MinIO to be ready (supervisord starts it)
    echo "[init-bg] Waiting for MinIO..."
    while ! curl -sf http://localhost:9000/minio/health/live >/dev/null 2>&1; do
        sleep 5
    done
    echo "[init-bg] MinIO is ready."

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

# Hand off to supervisord as PID 1
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
