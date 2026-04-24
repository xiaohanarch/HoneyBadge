#!/usr/bin/env bash
# fast-query.sh — Manager 直通 MCP，绕过 Worker
# 用法：bash fast-query.sh --question "..." --user-id "admin" --task-id "..."
#       [--forward-to-user-id "admin"]
#
# 出口码:
#   0 — 成功。无 --forward-to-user-id 时 stdout 输出 JSON；有时由 forward-to-user.sh 发送 contract 002
#   1 — 参数错误（缺少 --question）
#   2 — nGQL 生成失败（mcporter unavailable 或解析失败）
#   3 — 查询执行失败（validate_and_execute 返回错误）
set -euo pipefail

QUESTION=""
USER_ID=""
TASK_ID="fast-$(date +%s)"
FORWARD_USER_ID=""

# mcporter config — default to /root/config/mcporter.json (absolute path so
# it works regardless of the process working directory, which supervisord sets to /)
MCPORTER_CFG="${MCPORTER_CONFIG:-/root/config/mcporter.json}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --question)            QUESTION="$2";        shift 2 ;;
    --user-id)             USER_ID="$2";         shift 2 ;;
    --task-id)             TASK_ID="$2";         shift 2 ;;
    --forward-to-user-id)  FORWARD_USER_ID="$2"; shift 2 ;;
    *) shift ;;
  esac
done

[[ -z "$QUESTION" ]] && { echo '{"error":"--question is required"}'; exit 1; }

# Step 1: 生成 nGQL
NGQL_ARGS=$(python3 -c "import json,sys; print(json.dumps({'question': sys.argv[1]}))" "$QUESTION") \
  || { echo '{"error":"nGQL generation failed"}'; exit 2; }

NGQL_RESP=$(mcporter --config "$MCPORTER_CFG" call honeybadge-nebula.generate_query \
  --args "$NGQL_ARGS") \
  || { echo '{"error":"nGQL generation failed"}'; exit 2; }

NGQL=$(echo "$NGQL_RESP" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); ngql=d.get('ngql',''); sys.exit(2) if not ngql else print(ngql)" \
  2>/dev/null) \
  || { echo '{"error":"nGQL generation failed"}'; exit 2; }

# Step 2: 带权限执行
if [[ -n "$USER_ID" ]]; then
  EXEC_ARGS=$(python3 -c "import json,sys; print(json.dumps({'ngql': sys.argv[1], 'user_context': {'user_id': sys.argv[2]}}))" "$NGQL" "$USER_ID") \
    || { echo '{"error":"query execution failed"}'; exit 3; }
else
  EXEC_ARGS=$(python3 -c "import json,sys; print(json.dumps({'ngql': sys.argv[1], 'user_context': {}}))" "$NGQL") \
    || { echo '{"error":"query execution failed"}'; exit 3; }
fi

RESULT=$(mcporter --config "$MCPORTER_CFG" call honeybadge-nebula.validate_and_execute \
  --args "$EXEC_ARGS") \
  || { echo '{"error":"query execution failed"}'; exit 3; }

# Check if validate_and_execute returned success: false (nGQL semantic/syntax error)
_SUCCESS=$(echo "$RESULT" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('ok' if d.get('success', True) else 'fail')" \
  2>/dev/null || echo "ok")
if [[ "$_SUCCESS" == "fail" ]]; then
  _ERR=$(echo "$RESULT" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); dets=d.get('details',[]); print(dets[0].get('message','unknown') if dets else 'unknown')" \
    2>/dev/null || echo "unknown")
  echo "{\"error\":\"nGQL execution failed\",\"details\":\"$_ERR\"}" >&2
  exit 3
fi

# When --forward-to-user-id is given, send structured contract 002 reply via forward-to-user.sh
if [[ -n "$FORWARD_USER_ID" ]]; then
  TASK_DIR="/root/hiclaw-fs/shared/tasks/${TASK_ID}"
  mkdir -p "$TASK_DIR"

  # Create meta.json so forward-to-user.sh can resolve the user's DM room
  MATRIX_DOMAIN="${HICLAW_MATRIX_DOMAIN:-matrix-local.hiclaw.io}"
  python3 -c "import json,sys; print(json.dumps({'user_mxid': '@hb-'+sys.argv[1]+':'+sys.argv[2]}))" \
    "$FORWARD_USER_ID" "$MATRIX_DOMAIN" > "$TASK_DIR/meta.json"

  # Transform nebula-mcp result (rows/columns) → contract 002 result.json format
  RESULT_FILE="$TASK_DIR/result.json"
  export _FAST_RESULT="$RESULT" _FAST_NGQL="$NGQL" _FAST_RESULT_FILE="$RESULT_FILE"
  python3 -c "
import json, os
raw = json.loads(os.environ['_FAST_RESULT'])
out = {
    'trace_id': raw.get('trace_id', ''),
    'raw_data': raw.get('rows', []),
    'columns': raw.get('columns', []),
    'cypher': os.environ['_FAST_NGQL'],
    'execution_time_ms': raw.get('execution_time_ms', 0),
    'row_count': raw.get('row_count', 0),
}
with open(os.environ['_FAST_RESULT_FILE'], 'w') as f:
    json.dump(out, f)
"

  ROW_COUNT=$(python3 -c "import json,os; d=json.loads(os.environ['_FAST_RESULT']); print(d.get('row_count', 0))")
  SUMMARY="查询完成，共 ${ROW_COUNT} 条结果。"

  FORWARD_SCRIPT="/opt/honeybadge/config/manager/agent/skills/erp-query-dispatch/scripts/forward-to-user.sh"
  exec bash "$FORWARD_SCRIPT" \
    --task-id "$TASK_ID" \
    --content "$SUMMARY" \
    --result-json "$RESULT_FILE"
fi

echo "$RESULT"
