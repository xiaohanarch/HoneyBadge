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

while [[ $# -gt 0 ]]; do
    case "$1" in
        --worker)  WORKER_NAME="$2"; shift 2 ;;
        --task-id) TASK_ID="$2"; shift 2 ;;
        --message) MESSAGE="$2"; shift 2 ;;
        *)         echo "DISPATCH_ERROR: Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$WORKER_NAME" ] || [ -z "$MESSAGE" ]; then
    echo "DISPATCH_ERROR: --worker and --message are required" >&2
    exit 1
fi

REGISTRY="$HOME/workers-registry.json"
TUWUNEL_URL="http://127.0.0.1:6167"

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

# 3. Send message to worker's room via Matrix API
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
    echo "DISPATCH_OK room_id=$ROOM_ID event_id=$EVENT_ID"
    exit 0
else
    echo "DISPATCH_ERROR: Matrix send failed: $RESULT" >&2
    exit 1
fi
