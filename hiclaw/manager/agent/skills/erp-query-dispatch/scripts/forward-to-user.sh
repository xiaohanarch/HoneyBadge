#!/bin/bash
# forward-to-user.sh — Forward a Worker's result summary to the user's DM room
#
# Usage:
#   bash /opt/honeybadge/config/manager/agent/skills/erp-query-dispatch/scripts/forward-to-user.sh \
#     --task-id task-20260417-213200 \
#     --content "✅ 任务完成: <summary>"
#
#   # Long content via stdin:
#   echo "$SUMMARY" | bash forward-to-user.sh --task-id task-XXX --content -
#
# Reads:
#   /root/hiclaw-fs/shared/tasks/$TASK_ID/meta.json    — user_room_id / user_mxid
#   Manager's Matrix token                             — from openclaw.json
#
# Outputs (stdout):
#   FORWARD_OK room_id=!xxx event_id=$yyy
#   or FORWARD_ERROR: <reason>
#
# Rationale:
#   OpenClaw's default `message`/`replyMessage` tool replies to the room where the
#   triggering message was received. When a Worker @mentions the Manager in its
#   worker room, the LLM's default reply lands in the worker room — NOT the user's
#   DM room. This script bypasses that by PUTting directly to the user's DM room.

set -euo pipefail

TASK_ID=""
CONTENT=""
RESULT_JSON=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --task-id)     TASK_ID="$2"; shift 2 ;;
        --content)     CONTENT="$2"; shift 2 ;;
        --result-json) RESULT_JSON="$2"; shift 2 ;;
        *)             echo "FORWARD_ERROR: Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$TASK_ID" ]; then
    echo "FORWARD_ERROR: --task-id is required" >&2
    exit 1
fi

# Allow --content - to read from stdin (for long summaries that exceed shell arg limits)
if [ "$CONTENT" = "-" ]; then
    CONTENT=$(cat)
fi

if [ -z "$CONTENT" ]; then
    echo "FORWARD_ERROR: --content is required (or pass '-' to read stdin)" >&2
    exit 1
fi

META_PATH="/root/hiclaw-fs/shared/tasks/$TASK_ID/meta.json"
# Tuwunel base URL. Honor HICLAW_MATRIX_URL when set (split topology — Tuwunel
# lives in honeybadge-hiclaw-embedded, not the Manager container). Falls back
# to the matrix-local.hiclaw.io network alias, which resolves correctly in
# both embedded and split deployments.
TUWUNEL_URL="${HICLAW_MATRIX_URL:-http://matrix-local.hiclaw.io:6167}"

# 1. Look up user_room_id (and user_mxid) from task meta.json
if [ ! -f "$META_PATH" ]; then
    echo "FORWARD_ERROR: meta.json not found at $META_PATH" >&2
    exit 1
fi

export META_PATH_ENV="$META_PATH"
META_INFO=$(python3 << 'METAEOF'
import json, os, sys
try:
    with open(os.environ["META_PATH_ENV"]) as f:
        m = json.load(f)
except Exception as e:
    print("META_ERROR " + str(e))
    sys.exit(0)
urid = m.get("user_room_id", "") or ""
umxid = m.get("user_mxid", "") or ""
print((urid or "-") + " " + (umxid or "-"))
METAEOF
)

if [[ "$META_INFO" == META_ERROR* ]]; then
    echo "FORWARD_ERROR: failed to parse meta.json: $META_INFO" >&2
    exit 1
fi

USER_ROOM_ID=$(echo "$META_INFO" | cut -d' ' -f1)
USER_MXID=$(echo "$META_INFO" | cut -d' ' -f2)

# 2. Get Manager's Matrix token (dual-path, same as dispatch-to-worker.sh)
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
    echo "FORWARD_ERROR: Manager Matrix token not found" >&2
    exit 1
fi

# 3. Fallback: if meta.json lacks user_room_id, resolve via Manager's m.direct using user_mxid
if [ "$USER_ROOM_ID" = "-" ] || [ -z "$USER_ROOM_ID" ]; then
    if [ "$USER_MXID" = "-" ] || [ -z "$USER_MXID" ]; then
        echo "FORWARD_ERROR: meta.json has neither user_room_id nor user_mxid" >&2
        exit 1
    fi
    export FB_TOKEN="$MANAGER_TOKEN"
    export FB_TUWUNEL="$TUWUNEL_URL"
    export FB_USER_MXID="$USER_MXID"
    USER_ROOM_ID=$(python3 << 'FBEOF'
import json, urllib.request, urllib.parse, os, sys
mgr_uid = "@manager:matrix-local.hiclaw.io"
enc_mgr = urllib.parse.quote(mgr_uid, safe="")
url = f'{os.environ["FB_TUWUNEL"]}/_matrix/client/v3/user/{enc_mgr}/account_data/m.direct'
req = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ["FB_TOKEN"]})
try:
    with urllib.request.urlopen(req, timeout=5) as r:
        m_direct = json.loads(r.read())
    rooms = m_direct.get(os.environ["FB_USER_MXID"], [])
    print(rooms[0] if rooms else "")
except Exception:
    print("")
FBEOF
)
    if [ -z "$USER_ROOM_ID" ]; then
        echo "FORWARD_ERROR: could not resolve user DM room for $USER_MXID" >&2
        exit 1
    fi
fi

# 4. PUT message to user's DM room (no m.mentions — user is DM peer, no notification mention needed)
TXN_ID="forward-${TASK_ID}-$(date +%s%N)"

export FWD_ROOM_ID="$USER_ROOM_ID"
export FWD_TOKEN="$MANAGER_TOKEN"
export FWD_TUWUNEL_URL="$TUWUNEL_URL"
export FWD_TXN_ID="$TXN_ID"
export FWD_CONTENT="$CONTENT"
export FWD_RESULT_JSON="$RESULT_JSON"

RESULT=$(python3 << 'PYEOF'
import json, math, urllib.request, urllib.parse, os

room_id = os.environ["FWD_ROOM_ID"]
token = os.environ["FWD_TOKEN"]
tuwunel = os.environ["FWD_TUWUNEL_URL"]
txn_id = os.environ["FWD_TXN_ID"]
content = os.environ["FWD_CONTENT"]
result_json_path = os.environ.get("FWD_RESULT_JSON", "")

encoded_room = urllib.parse.quote(room_id, safe='')
encoded_txn = urllib.parse.quote(txn_id, safe='')
url = f'{tuwunel}/_matrix/client/v3/rooms/{encoded_room}/send/m.room.message/{encoded_txn}'

# Matrix canonical JSON (spec.matrix.org/latest/appendices/#canonical-json):
#   - Integers MUST fit in js_int::Int range [-2^53+1, 2^53-1]
#   - Floats (numbers with fractions/exponents) are FORBIDDEN entirely
#     → out-of-range ints and any non-integer floats must be coerced to strings
#     → NaN/Inf → None
_JS_INT_MAX = 9007199254740991  # 2^53 - 1

def safe_for_matrix(obj):
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return str(obj) if abs(obj) > _JS_INT_MAX else obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        # Whole-valued floats → int (still subject to js_int range).
        if obj.is_integer() and abs(obj) <= _JS_INT_MAX:
            return int(obj)
        # Fractional floats are invalid in Matrix canonical JSON → stringify.
        return repr(obj)
    if isinstance(obj, dict):
        return {k: safe_for_matrix(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [safe_for_matrix(v) for v in obj]
    return obj

body = {
    'msgtype': 'm.text',
    'body': content,
}

# Attach x-honeybadge structured payload when result.json is available
if result_json_path and os.path.isfile(result_json_path):
    try:
        with open(result_json_path) as f:
            result = json.load(f)
        body['x-honeybadge'] = {
            'v': '1',
            'contract': '002',
            'trace_id': result.get('trace_id', ''),
            'payload': {
                'summary': result.get('summary', content),
                'raw_data': result.get('raw_data', []),
                'columns': result.get('columns', []),
                'cypher': result.get('cypher', ''),
                'execution_time_ms': result.get('execution_time_ms', 0),
                'row_count': result.get('row_count', 0),
            },
        }
    except Exception:
        pass  # fall through to plain text if result.json is unreadable

data = json.dumps(safe_for_matrix(body)).encode('utf-8')
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
    echo "FORWARD_OK room_id=$USER_ROOM_ID event_id=$EVENT_ID"
    exit 0
else
    echo "FORWARD_ERROR: Matrix send failed: $RESULT" >&2
    exit 1
fi
