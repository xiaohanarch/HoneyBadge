#!/usr/bin/env bash
# fast-forward.sh — Send fast-query result as x-honeybadge contract 002 to user's DM room
#
# Usage:
#   bash fast-forward.sh \
#     --user-id "admin" \
#     --result-json "/tmp/fast-result.json" \
#     [--ngql "MATCH (v:Supplier) RETURN v LIMIT 5"]
#
# The --result-json must be the raw validate_and_execute output:
#   {success, columns, rows, row_count, execution_time_ms, trace_id}
#
# Resolves the user's DM room from Manager's m.direct, then sends a
# structured x-honeybadge contract 002 message (not plain text).
#
# Exit codes:
#   0 — message sent successfully
#   1 — argument / config error
#   2 — Matrix send failed

set -euo pipefail

USER_ID=""
RESULT_JSON=""
NGQL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user-id)      USER_ID="$2";      shift 2 ;;
        --result-json)  RESULT_JSON="$2";  shift 2 ;;
        --ngql)         NGQL="$2";         shift 2 ;;
        *) shift ;;
    esac
done

if [[ -z "$USER_ID" ]] || [[ -z "$RESULT_JSON" ]]; then
    echo "ERROR: --user-id and --result-json are required" >&2
    exit 1
fi

TUWUNEL_URL="http://127.0.0.1:6167"
USER_MXID="@hb-${USER_ID}:matrix-local.hiclaw.io"

# Get Manager's Matrix token
MANAGER_TOKEN=""
for cfg_path in "$HOME/manager-workspace/openclaw.json" "$HOME/.openclaw/openclaw.json"; do
    if [[ -f "$cfg_path" ]]; then
        export TOKEN_CFG_PATH="$cfg_path"
        MANAGER_TOKEN=$(python3 << 'TOKEOF'
import json, os
with open(os.environ["TOKEN_CFG_PATH"]) as f:
    cfg = json.load(f)
print(cfg.get('channels', {}).get('matrix', {}).get('accessToken', ''))
TOKEOF
)
        [[ -n "$MANAGER_TOKEN" ]] && break
    fi
done

if [[ -z "$MANAGER_TOKEN" ]]; then
    echo "ERROR: Manager Matrix token not found" >&2
    exit 1
fi

export FF_TOKEN="$MANAGER_TOKEN"
export FF_TUWUNEL="$TUWUNEL_URL"
export FF_USER_MXID="$USER_MXID"
export FF_RESULT_JSON="$RESULT_JSON"
export FF_NGQL="$NGQL"

STATUS=$(python3 << 'PYEOF'
import json, urllib.request, urllib.parse, os, sys, time

token      = os.environ["FF_TOKEN"]
tuwunel    = os.environ["FF_TUWUNEL"]
user_mxid  = os.environ["FF_USER_MXID"]
result_path = os.environ["FF_RESULT_JSON"]
ngql        = os.environ.get("FF_NGQL", "")

# 1. Look up user's DM room from Manager's m.direct
mgr_uid = "@manager:matrix-local.hiclaw.io"
enc_mgr = urllib.parse.quote(mgr_uid, safe="")
url = f'{tuwunel}/_matrix/client/v3/user/{enc_mgr}/account_data/m.direct'
req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
try:
    with urllib.request.urlopen(req, timeout=5) as r:
        m_direct = json.loads(r.read())
    rooms = m_direct.get(user_mxid, [])
    if not rooms:
        print(f"ERROR no_dm_room user={user_mxid}", file=sys.stderr)
        sys.exit(1)
    room_id = rooms[0]
except Exception as e:
    print(f"ERROR mdirect_lookup: {e}", file=sys.stderr)
    sys.exit(1)

# 2. Load fast-query result JSON
# validate_and_execute returns "rows", not "raw_data"
try:
    with open(result_path) as f:
        result = json.load(f)
except Exception as e:
    print(f"ERROR result_json: {e}", file=sys.stderr)
    sys.exit(1)

raw_data        = result.get('rows', result.get('raw_data', []))
columns         = result.get('columns', [])
row_count       = result.get('row_count', len(raw_data))
execution_ms    = result.get('execution_time_ms', 0)
trace_id        = result.get('trace_id', '')

summary = f"查询完成，共 {row_count} 条结果" if row_count > 0 else "查询完成，无结果"

# 3. Send x-honeybadge contract 002 message
txn_id = f"fast-fwd-{int(time.time() * 1000)}"
enc_room = urllib.parse.quote(room_id, safe='')
enc_txn  = urllib.parse.quote(txn_id,  safe='')
send_url = f'{tuwunel}/_matrix/client/v3/rooms/{enc_room}/send/m.room.message/{enc_txn}'

body = {
    'msgtype': 'm.text',
    'body': summary,
    'x-honeybadge': {
        'v': '1',
        'contract': '002',
        'trace_id': trace_id,
        'payload': {
            'summary':          summary,
            'raw_data':         raw_data,
            'columns':          columns,
            'cypher':           ngql,
            'execution_time_ms': execution_ms,
            'row_count':        row_count,
        },
    },
}

data = json.dumps(body).encode('utf-8')
req = urllib.request.Request(send_url, data=data, method='PUT', headers={
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json',
})

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        event_id = json.loads(resp.read()).get('event_id', '')
        print(f"OK event_id={event_id}")
except urllib.error.HTTPError as e:
    err = e.read().decode()
    print(f"HTTP_ERROR {e.code}: {err[:200]}", file=sys.stderr)
    sys.exit(2)
except Exception as e:
    print(f"ERROR send: {e}", file=sys.stderr)
    sys.exit(2)
PYEOF
)

echo "$STATUS"
