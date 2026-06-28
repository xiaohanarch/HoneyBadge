#!/bin/bash
# HoneyBadge Worker Entrypoint Wrapper
#
# Registers MCP servers via mcporter and copies custom SOUL.md from
# MinIO-synced hiclaw-fs to /root/ where openclaw reads it.
# Runs in background, then hands off to the real worker entrypoint as PID 1.
#
# Mounted into worker containers via docker-compose volume:
#   ../hiclaw/worker-init-wrapper.sh:/opt/honeybadge/init/worker-init-wrapper.sh:ro

set -u

WORKER_NAME="${HICLAW_WORKER_NAME:-unknown}"
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

echo "[worker-init] Starting background init for $WORKER_NAME..."

(
    # Wait for file-sync to download configs from MinIO
    # (file-sync runs after worker-entrypoint.sh starts openclaw)
    sleep 30

    # --- Copy custom SOUL.md from hiclaw-fs to /root/ where openclaw reads it ---
    HB_SOUL="/root/hiclaw-fs/agents/$WORKER_NAME/SOUL.md"
    if [ -f "$HB_SOUL" ]; then
        mkdir -p "$AGENT_HOME"
        cp "$HB_SOUL" "$AGENT_HOME/SOUL.md"
        echo "[worker-init] Copied custom SOUL.md from $HB_SOUL → $AGENT_HOME/SOUL.md"
    else
        echo "[worker-init] WARNING: Custom SOUL.md not found at $HB_SOUL"
    fi

    # --- Copy custom skills from hiclaw-fs ---
    HB_SKILLS="/root/hiclaw-fs/agents/$WORKER_NAME/skills"
    if [ -d "$HB_SKILLS" ]; then
        mkdir -p "$AGENT_HOME/skills"
        cp -r "$HB_SKILLS"/* "$AGENT_HOME/skills/" 2>/dev/null \
            && echo "[worker-init] Copied custom skills from $HB_SKILLS" \
            || echo "[worker-init] No skills to copy from $HB_SKILLS"
    fi

    # --- Register MCP servers (for CLI usage from /root) ---
    for name in honeybadge-nebula honeybadge-audit honeybadge-cache; do
        mcporter config add "$name" "http://${name}-mcp:8000/sse" --allow-http --yes 2>/dev/null \
            && echo "[worker-init] MCP server $name registered" \
            || echo "[worker-init] MCP server $name already exists or failed"
    done

    # --- Link mcporter config into the mcporter skill directory ---
    # mcporter resolves ./config/mcporter.json relative to the CWD.
    # When the mcporter skill runs from /root/skills/mcporter/, it looks for
    # /root/skills/mcporter/config/mcporter.json.  Create that path if missing.
    SKILL_DIR="$AGENT_HOME/skills/mcporter"
    MCP_CONFIG_SOURCE="/root/hiclaw-fs/config/mcporter.json"
    MCP_CONFIG_DEST="$SKILL_DIR/config/mcporter.json"
    if [ -f "$MCP_CONFIG_SOURCE" ] && [ ! -f "$MCP_CONFIG_DEST" ]; then
        mkdir -p "$SKILL_DIR/config" \
            && ln -s "$MCP_CONFIG_SOURCE" "$MCP_CONFIG_DEST" \
            && echo "[worker-init] Linked mcporter config into $SKILL_DIR/config/"
    elif [ -f "$MCP_CONFIG_SOURCE" ] && [ -L "$MCP_CONFIG_DEST" ]; then
        # Already linked — refresh symlink in case config changed
        rm "$MCP_CONFIG_DEST" && ln -s "$MCP_CONFIG_SOURCE" "$MCP_CONFIG_DEST" \
            && echo "[worker-init] Refreshed mcporter config symlink in $SKILL_DIR/config/"
    fi

    # --- Wake up Matrix room sessions to process any pending messages ---
    # After a container restart, openclaw-gateway reconnects to Matrix but does not
    # automatically poll pending messages. We fix this by triggering each Matrix
    # room session once with a nudge message.  Without this, the worker appears
    # "online" (heartbeat OK) but silently ignores incoming messages.
    if [ "$WORKER_RUNTIME" = "openclaw" ]; then
        echo "[worker-init] Checking for stale Matrix room sessions to wake up..."
        for attempt in 1 2 3 4 5; do
            if [ -f "$SESSIONS_FILE" ] && grep -q "matrix:channel" "$SESSIONS_FILE"; then
                break
            fi
            echo "[worker-init] Waiting for sessions.json... (attempt $attempt/5)"
            sleep 5
        done

        if [ -f "$SESSIONS_FILE" ]; then
            # Find all Matrix room sessions (session keys containing "matrix:channel")
            # The file is JSON with keys like "agent:main:matrix:channel:!roomId:domain"
            python3 - << 'PYEOF'
import json, subprocess, sys

sessions_file = '/root/.openclaw/agents/main/sessions/sessions.json'
try:
    with open(sessions_file) as f:
        sessions = json.load(f)
except Exception as e:
    print(f'[worker-init] Could not read sessions.json: {e}')
    sys.exit(0)

for key, session in sessions.items():
    if 'matrix:channel' not in key:
        continue
    session_id = session.get('sessionId')
    if not session_id:
        continue
    reply_target = session.get('lastTo', '')
    # lastTo format: "room:!roomId:domain" or "room:!roomId:domain"
    channel = 'matrix'
    print(f'[worker-init] Waking Matrix session {session_id} (lastTo={reply_target})...')
    try:
        cmd = [
            'openclaw', 'agent',
            '--session-id', session_id,
            '--message', '[worker-init] Worker reconnected — processing any pending messages.',
            '--deliver',
            '--reply-channel', channel,
            '--timeout', '120'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            print(f'[worker-init] Matrix session {session_id} wake-up completed.')
        else:
            print(f'[worker-init] Matrix session {session_id} wake-up failed: {result.stderr[:200]}')
    except subprocess.TimeoutExpired:
        print(f'[worker-init] Matrix session {session_id} wake-up timed out.')
    except Exception as ex:
        print(f'[worker-init] Matrix session {session_id} wake-up error: {ex}')
PYEOF
        else
            echo "[worker-init] sessions.json not found — skipping Matrix session wake-up."
        fi
    else
        echo "[worker-init] Skipping openclaw session wake-up (runtime: $WORKER_RUNTIME)"
    fi

    echo "[worker-init] Background init complete for $WORKER_NAME."
) &

# Hand off to the real worker entrypoint
exec "$WORKER_ENTRYPOINT"
