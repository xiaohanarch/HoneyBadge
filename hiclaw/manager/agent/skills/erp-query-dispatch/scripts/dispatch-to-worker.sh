#!/bin/bash
# dispatch-to-worker.sh — Send task @mention to a Worker's dedicated Matrix room
#
# Usage:
#   bash /opt/honeybadge/config/manager/agent/skills/erp-query-dispatch/scripts/dispatch-to-worker.sh \
#     --worker graph-worker \
#     --task-id task-20260417-143052 \
#     --message "@graph-worker:matrix-local.hiclaw.io Task task-20260417-143052: ..."
#
# Reads:
#   ~/workers-registry.json    — worker room_id lookup
#   Manager's Matrix token     — from openclaw.json
#
# Outputs (stdout):
#   DISPATCH_OK room_id=!xxx event_id=$yyy
#   or DISPATCH_ERROR: <reason>

set -euo pipefail

WORKER_NAME=""
TASK_ID=""
MESSAGE=""
USER_MXID=""
USER_ID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --worker)     WORKER_NAME="$2"; shift 2 ;;
        --task-id)    TASK_ID="$2";     shift 2 ;;
        --message)    MESSAGE="$2";     shift 2 ;;
        --user-mxid)  USER_MXID="$2";  shift 2 ;;
        --user-id)    USER_ID="$2";    shift 2 ;;
        *)            echo "DISPATCH_ERROR: Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$WORKER_NAME" ] || [ -z "$MESSAGE" ]; then
    echo "DISPATCH_ERROR: --worker and --message are required" >&2
    exit 1
fi

REGISTRY="$HOME/workers-registry.json"
# Tuwunel base URL. Honor HICLAW_MATRIX_URL when set (split topology — Tuwunel
# lives in honeybadge-hiclaw-embedded, not the Manager container). Falls back
# to the matrix-local.hiclaw.io network alias, which resolves correctly in
# both embedded and split deployments.
TUWUNEL_URL="${HICLAW_MATRIX_URL:-http://matrix-local.hiclaw.io:6167}"

# 1. Look up worker room_id from registry
if [ ! -f "$REGISTRY" ]; then
    echo "DISPATCH_ERROR: workers-registry.json not found at $REGISTRY" >&2
    exit 1
fi

export REG_PATH="$REGISTRY"
export REG_WORKER="$WORKER_NAME"
WORKER_INFO=$(python3 << 'REGEOF'
import json, sys, os
with open(os.environ["REG_PATH"]) as f:
    reg = json.load(f)
w = reg.get('workers', {}).get(os.environ["REG_WORKER"])
if not w:
    print('NOT_FOUND')
    sys.exit(0)
print(w['room_id'] + ' ' + w['matrix_user_id'])
REGEOF
)

if [ "$WORKER_INFO" = "NOT_FOUND" ]; then
    echo "DISPATCH_ERROR: worker '$WORKER_NAME' not found in registry" >&2
    exit 1
fi

ROOM_ID=$(echo "$WORKER_INFO" | cut -d' ' -f1)
WORKER_MXID=$(echo "$WORKER_INFO" | cut -d' ' -f2)

# 2. Get Manager's Matrix token
MANAGER_TOKEN=""
for cfg_path in "$HOME/manager-workspace/openclaw.json" "$HOME/.openclaw/openclaw.json"; do
    if [ -f "$cfg_path" ]; then
        export TOKEN_CFG_PATH="$cfg_path"
        MANAGER_TOKEN=$(python3 << 'TOKEOF'
import json, os
with open(os.environ["TOKEN_CFG_PATH"]) as f:
    cfg = json.load(f)
print(cfg.get('channels',{}).get('matrix',{}).get('accessToken',''))
TOKEOF
)
        [ -n "$MANAGER_TOKEN" ] && break
    fi
done

if [ -z "$MANAGER_TOKEN" ]; then
    echo "DISPATCH_ERROR: Manager Matrix token not found" >&2
    exit 1
fi

# 3. Create task directory and meta.json so result-watcher / forward-to-user.sh
#    can resolve the user's DM room when the Worker result arrives.
#    Also write spec.md with user_id so the Worker can extract it deterministically
#    (not relying on LLM substitution for L3 permission enforcement).
if [ -n "$TASK_ID" ] && [ -n "$USER_MXID" ]; then
    TASK_META_DIR="/root/hiclaw-fs/shared/tasks/$TASK_ID"
    mkdir -p "$TASK_META_DIR"
    python3 -c "
import json, sys
meta = {'user_mxid': sys.argv[1]}
with open(sys.argv[2], 'w') as f:
    json.dump(meta, f)
" "$USER_MXID" "$TASK_META_DIR/meta.json" \
        && echo "META_CREATED $TASK_META_DIR/meta.json" >&2 \
        || echo "META_CREATE_FAILED (continuing)" >&2

    # Write spec.md with user_id for L3 permission enforcement.
    # The Worker reads this to extract user_id for mcporter validate_and_execute.
    if [ -n "$USER_ID" ]; then
        cat > "$TASK_META_DIR/spec.md" << SPECEOF
# Task: $TASK_ID
user_id: $USER_ID
question: $MESSAGE
## Expected Output
Query results with L3 permission filtering applied for user "$USER_ID".
SPECEOF
        echo "SPEC_CREATED $TASK_META_DIR/spec.md (user_id=$USER_ID)" >&2

        # Sync spec.md to MinIO so the Worker can pull it
        mc cp "$TASK_META_DIR/spec.md" \
            "hiclaw/hiclaw-storage/shared/tasks/$TASK_ID/spec.md" 2>/dev/null \
            || echo "SPEC_MINIO_SYNC_FAILED (continuing)" >&2
    fi
fi

# 4. Send message to worker's room via Matrix API
TXN_ID="dispatch-${TASK_ID:-$(date +%s%N)}"

export DISPATCH_ROOM_ID="$ROOM_ID"
export DISPATCH_TOKEN="$MANAGER_TOKEN"
export DISPATCH_TUWUNEL_URL="$TUWUNEL_URL"
export DISPATCH_WORKER_MXID="$WORKER_MXID"
export DISPATCH_TXN_ID="$TXN_ID"
export DISPATCH_MESSAGE="$MESSAGE"

RESULT=$(python3 << 'PYEOF'
import json, urllib.request, urllib.parse, sys, os

room_id = os.environ["DISPATCH_ROOM_ID"]
token = os.environ["DISPATCH_TOKEN"]
tuwunel = os.environ["DISPATCH_TUWUNEL_URL"]
worker_mxid = os.environ["DISPATCH_WORKER_MXID"]
txn_id = os.environ["DISPATCH_TXN_ID"]
message = os.environ["DISPATCH_MESSAGE"]

encoded_room = urllib.parse.quote(room_id, safe='')
encoded_txn = urllib.parse.quote(txn_id, safe='')
url = f'{tuwunel}/_matrix/client/v3/rooms/{encoded_room}/send/m.room.message/{encoded_txn}'

body = {
    'msgtype': 'm.text',
    'body': message,
    'm.mentions': {'user_ids': [worker_mxid]},
}

data = json.dumps(body).encode('utf-8')
req = urllib.request.Request(url, data=data, method='PUT', headers={
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json',
})

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
        print('OK ' + result.get('event_id', ''))
except urllib.error.HTTPError as e:
    err_body = e.read().decode()
    print(f'HTTP_ERROR {e.code} {err_body[:200]}')
except Exception as e:
    print(f'ERROR {e}')
PYEOF
)

STATUS=$(echo "$RESULT" | cut -d' ' -f1)
EVENT_ID=$(echo "$RESULT" | cut -d' ' -f2-)

if [ "$STATUS" = "OK" ]; then
    # Launch background result-watcher to deliver the task result deterministically
    if [ -n "$TASK_ID" ]; then
        WATCHER_SCRIPT="$(cd "$(dirname "$0")" && pwd)/result-watcher.sh"
        if [ -f "$WATCHER_SCRIPT" ]; then
            nohup bash "$WATCHER_SCRIPT" "$TASK_ID" \
                >> "/tmp/watcher-${TASK_ID}.log" 2>&1 &
            echo "WATCHER_STARTED pid=$! task=$TASK_ID" >&2
        else
            echo "WATCHER_MISSING: $WATCHER_SCRIPT not found, watcher not launched" >&2
        fi
    fi
    echo "DISPATCH_OK room_id=$ROOM_ID event_id=$EVENT_ID"
    exit 0
else
    echo "DISPATCH_ERROR: Matrix send failed: $RESULT" >&2
    exit 1
fi
