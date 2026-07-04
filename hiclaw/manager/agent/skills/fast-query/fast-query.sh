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

# If --user-id was not explicitly provided but --forward-to-user-id was,
# use the forward user ID for permission checking.  The Manager LLM often
# calls fast-query.sh with only --forward-to-user-id (not --user-id).
# Without this fallback, user_context is empty and L3 permission filtering
# is silently skipped, causing all users to see the same (unfiltered) data.
if [[ -z "$USER_ID" && -n "$FORWARD_USER_ID" ]]; then
  USER_ID="$FORWARD_USER_ID"
fi

[[ -z "$QUESTION" ]] && { echo '{"error":"--question is required"}'; exit 1; }

# Step 1: 生成 nGQL
# Fetch recent Q&A history from Matrix DM for multi-turn anaphora resolution
# ("这些订单" → prior PurchaseOrder query). Graceful degradation: empty [] on
# any error, so single-turn behavior is preserved.
HISTORY=$(python3 "$(dirname "$0")/fetch-conversation-history.py" \
    --user-id "$USER_ID" --max-rounds 3 2>/dev/null || echo '[]')
NGQL_ARGS=$(python3 -c "
import json, sys
print(json.dumps({'question': sys.argv[1], 'conversation_history': json.loads(sys.argv[2])}))
" "$QUESTION" "$HISTORY") \
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
# On failure, retry once: re-generate nGQL with the error message as context,
# then re-execute. This handles the common case where the LLM generates an
# nGQL with an ORDER BY property path (SemanticError) — the error feedback
# lets it self-correct.
#
# EXCEPTION: L3_PERMISSION errors are NOT retried — the user lacks permission
# to access the data, and regenerating the nGQL won't help. We forward the
# permission error to the user's DM room and exit with code 4 so the Manager
# knows NOT to fall back to graph-worker (which would bypass permissions).
_SUCCESS=$(echo "$RESULT" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('ok' if d.get('success', True) else 'fail')" \
  2>/dev/null || echo "ok")
if [[ "$_SUCCESS" == "fail" ]]; then
  _ERR_CODE=$(echo "$RESULT" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" \
    2>/dev/null || echo "")
  _ERR=$(echo "$RESULT" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); dets=d.get('details',[]); print(dets[0].get('message','unknown') if dets else 'unknown')" \
    2>/dev/null || echo "unknown")

  # L3 permission violation — do NOT retry, forward error to user, exit 4
  if [[ "$_ERR_CODE" == "L3_PERMISSION" ]]; then
    if [[ -n "$FORWARD_USER_ID" ]]; then
      TASK_DIR="/root/hiclaw-fs/shared/tasks/${TASK_ID}"
      mkdir -p "$TASK_DIR"
      MATRIX_DOMAIN="${HICLAW_MATRIX_DOMAIN:-matrix-local.hiclaw.io}"
      FUID_CLEAN="${FORWARD_USER_ID#hb-}"
      python3 -c "import json,sys; print(json.dumps({'user_mxid': '@hb-'+sys.argv[1]+':'+sys.argv[2]}))" \
        "$FUID_CLEAN" "$MATRIX_DOMAIN" > "$TASK_DIR/meta.json"
      # Create a minimal result.json so forward-to-user.sh can process it
      python3 -c "import json; print(json.dumps({'trace_id':'','raw_data':[],'columns':[],'cypher':'','execution_time_ms':0,'row_count':0}))" > "$TASK_DIR/result.json"
      FORWARD_SCRIPT="/opt/honeybadge/config/manager/agent/skills/erp-query-dispatch/scripts/forward-to-user.sh"
      bash "$FORWARD_SCRIPT" \
        --task-id "$TASK_ID" \
        --content "权限不足：${_ERR}" \
        --result-json "$TASK_DIR/result.json" 2>/dev/null || true
    fi
    echo "{\"error\":\"L3_PERMISSION\",\"details\":\"${_ERR}\"}" >&2
    exit 4
  fi

  # Retry: re-generate nGQL with error context appended to the question
  _RETRY_Q="${QUESTION}

# 上一次生成的 nGQL 执行失败，错误信息：${_ERR}
# 请修正 nGQL 语法错误重新生成。特别注意：ORDER BY 只能使用 RETURN 中的 AS 别名，不能使用 var.Tag.property 属性路径。"

  _RETRY_ARGS=$(python3 -c "
import json, sys
print(json.dumps({'question': sys.argv[1], 'conversation_history': json.loads(sys.argv[2])}))
" "$_RETRY_Q" "$HISTORY") \
    || { echo '{"error":"nGQL retry generation failed"}'; exit 2; }
  _RETRY_RESP=$(mcporter --config "$MCPORTER_CFG" call honeybadge-nebula.generate_query \
    --args "$_RETRY_ARGS") \
    || { echo '{"error":"nGQL retry generation failed"}'; exit 2; }
  _NGQL_RETRY=$(echo "$_RETRY_RESP" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); ngql=d.get('ngql',''); sys.exit(2) if not ngql else print(ngql)" \
    2>/dev/null) \
    || { echo '{"error":"nGQL retry generation failed"}'; exit 2; }

  # Re-execute with the retried nGQL (preserve user_context for L3 permissions)
  if [[ -n "$USER_ID" ]]; then
    EXEC_ARGS=$(python3 -c "import json,sys; print(json.dumps({'ngql': sys.argv[1], 'user_context': {'user_id': sys.argv[2]}}))" "$_NGQL_RETRY" "$USER_ID") \
      || { echo '{"error":"query execution failed"}'; exit 3; }
  else
    EXEC_ARGS=$(python3 -c "import json,sys; print(json.dumps({'ngql': sys.argv[1], 'user_context': {}}))" "$_NGQL_RETRY") \
      || { echo '{"error":"query execution failed"}'; exit 3; }
  fi

  RESULT=$(mcporter --config "$MCPORTER_CFG" call honeybadge-nebula.validate_and_execute \
    --args "$EXEC_ARGS") \
    || { echo '{"error":"query execution failed"}'; exit 3; }

  # Re-check success after retry
  _SUCCESS=$(echo "$RESULT" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print('ok' if d.get('success', True) else 'fail')" \
    2>/dev/null || echo "ok")
  if [[ "$_SUCCESS" == "fail" ]]; then
    _ERR=$(echo "$RESULT" | python3 -c \
      "import sys,json; d=json.load(sys.stdin); dets=d.get('details',[]); print(dets[0].get('message','unknown') if dets else 'unknown')" \
      2>/dev/null || echo "unknown")
    echo "{\"error\":\"nGQL execution failed after retry\",\"details\":\"$_ERR\"}" >&2
    exit 3
  fi

  # Use retried nGQL for downstream result.json transformation
  NGQL="$_NGQL_RETRY"
fi

# When --forward-to-user-id is given, send structured contract 002 reply via forward-to-user.sh
if [[ -n "$FORWARD_USER_ID" ]]; then
  TASK_DIR="/root/hiclaw-fs/shared/tasks/${TASK_ID}"
  mkdir -p "$TASK_DIR"

  # Create meta.json so forward-to-user.sh can resolve the user's DM room
  MATRIX_DOMAIN="${HICLAW_MATRIX_DOMAIN:-matrix-local.hiclaw.io}"
  # Strip hb- prefix from FORWARD_USER_ID to avoid double-prefixing (@hb-hb-xxx).
  # The Manager LLM inconsistently adds hb- to --forward-to-user-id values.
  FUID_CLEAN="${FORWARD_USER_ID#hb-}"
  python3 -c "import json,sys; print(json.dumps({'user_mxid': '@hb-'+sys.argv[1]+':'+sys.argv[2]}))" \
    "$FUID_CLEAN" "$MATRIX_DOMAIN" > "$TASK_DIR/meta.json"

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
    'cypher': raw.get('ngql', os.environ['_FAST_NGQL']),
    'execution_time_ms': raw.get('execution_time_ms', 0),
    'row_count': raw.get('row_count', 0),
}
with open(os.environ['_FAST_RESULT_FILE'], 'w') as f:
    json.dump(out, f)
"

  ROW_COUNT=$(python3 -c "import json,os; d=json.loads(os.environ['_FAST_RESULT']); print(d.get('row_count', 0))")
  # For count queries (RETURN count(...) AS xxx), row_count is 1 (one row
  # containing the count value).  Extract the actual count value so the
  # summary says "共 4577 条" not "共 1 条".
  # Detect count queries by checking: single row, single column, and either
  # the column name or the nGQL contains 'count' (case-insensitive).
  DISPLAY_COUNT=$(python3 -c "
import json, os
d = json.loads(os.environ['_FAST_RESULT'])
rows = d.get('rows', [])
cols = d.get('columns', [])
ngql = d.get('ngql', '') or os.environ.get('_FAST_NGQL', '')
is_count = (
    len(rows) == 1
    and len(cols) == 1
    and ('count' in cols[0].lower() or 'count(' in ngql.lower())
)
if is_count:
    v = rows[0].get(cols[0], 0)
    print(v if v is not None else 0)
else:
    print(d.get('row_count', 0))
" 2>/dev/null || echo "$ROW_COUNT")
  SUMMARY="查询完成，共 ${DISPLAY_COUNT} 条结果。"

  FORWARD_SCRIPT="/opt/honeybadge/config/manager/agent/skills/erp-query-dispatch/scripts/forward-to-user.sh"
  exec bash "$FORWARD_SCRIPT" \
    --task-id "$TASK_ID" \
    --content "$SUMMARY" \
    --result-json "$RESULT_FILE"
fi

echo "$RESULT"
