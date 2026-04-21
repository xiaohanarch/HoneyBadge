#!/bin/bash
# result-watcher.sh — Deterministic background delivery for completed Worker tasks
#
# Launched by dispatch-to-worker.sh after a successful task dispatch.
# Polls MinIO every POLL_INTERVAL seconds for result.json; calls forward-to-user.sh
# as soon as the file appears. Uses a lock file to prevent duplicate instances and
# a delivered marker to prevent duplicate delivery (e.g., if heartbeat also delivers).
#
# Usage:
#   nohup bash result-watcher.sh <task-id> >> /tmp/watcher-<task-id>.log 2>&1 &

set -u

TASK_ID="${1:-}"
if [ -z "$TASK_ID" ]; then
    echo "ERROR: task-id argument required" >&2
    exit 1
fi

POLL_INTERVAL=2
MAX_WAIT=600
ELAPSED=0

TASK_DIR="/root/hiclaw-fs/shared/tasks/$TASK_ID"
RESULT_JSON="$TASK_DIR/result.json"
DELIVERED_MARKER="/tmp/.watcher-delivered-$TASK_ID"
LOCK_FILE="/tmp/.watcher-running-$TASK_ID"

# Resolve the forward-to-user.sh path relative to this script, then fall back
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
FWD_SCRIPT="$SCRIPTS_DIR/forward-to-user.sh"
if [ ! -f "$FWD_SCRIPT" ]; then
    FWD_SCRIPT="/root/manager-workspace/skills/erp-query-dispatch/scripts/forward-to-user.sh"
fi

_log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [watcher-$TASK_ID] $*"; }

# ── Prevent duplicate instances ──────────────────────────────────────────────
if [ -f "$LOCK_FILE" ]; then
    _log "another watcher instance already running (lock=$LOCK_FILE), exiting"
    exit 0
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT TERM INT

_log "started (max=${MAX_WAIT}s, poll=${POLL_INTERVAL}s)"

# ── Polling loop ──────────────────────────────────────────────────────────────
while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do

    # If heartbeat or another path already delivered, bail out
    if [ -f "$DELIVERED_MARKER" ]; then
        _log "already delivered by another path, exiting"
        exit 0
    fi

    # Sync task directory from MinIO
    mkdir -p "$TASK_DIR"
    mc mirror "hiclaw/hiclaw-storage/shared/tasks/$TASK_ID/" "$TASK_DIR/" \
        --overwrite 2>/dev/null || true

    if [ -f "$RESULT_JSON" ]; then
        _log "result.json found, forwarding to user"

        # Build summary text from result.md (first 400 chars)
        SUMMARY_TEXT="查询已完成，结果如下。"
        if [ -f "$TASK_DIR/result.md" ]; then
            MD_CONTENT=$(head -c 400 "$TASK_DIR/result.md" 2>/dev/null || true)
            [ -n "$MD_CONTENT" ] && SUMMARY_TEXT="$MD_CONTENT"
        fi

        if [ ! -f "$FWD_SCRIPT" ]; then
            _log "ERROR: forward-to-user.sh not found at $FWD_SCRIPT — will retry"
        else
            FWD_OUT=$(echo "$SUMMARY_TEXT" | bash "$FWD_SCRIPT" \
                --task-id "$TASK_ID" \
                --content - \
                --result-json "$RESULT_JSON" 2>&1) || true

            _log "forward output: $FWD_OUT"

            if echo "$FWD_OUT" | grep -q "FORWARD_OK"; then
                touch "$DELIVERED_MARKER"
                _log "DELIVERED successfully"
                exit 0
            fi
            # Forward failed (e.g., Tuwunel transient error) — retry next cycle
        fi
    fi

    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

_log "TIMEOUT after ${MAX_WAIT}s without successful delivery"
exit 1
