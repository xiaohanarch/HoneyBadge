#!/usr/bin/env bash
# fast-query.sh — Manager 直通 MCP，绕过 Worker
# 用法：bash fast-query.sh --question "..." --user-id "admin" --task-id "..."
#
# 出口码:
#   0 — 成功，stdout 输出 JSON 查询结果
#   1 — 参数错误（缺少 --question）
#   2 — nGQL 生成失败（mcporter unavailable 或解析失败）
#   3 — 查询执行失败（validate_and_execute 返回错误）
set -euo pipefail

QUESTION=""
USER_ID=""
TASK_ID="fast-$(date +%s)"

while [[ $# -gt 0 ]]; do
  case $1 in
    --question)  QUESTION="$2";  shift 2 ;;
    --user-id)   USER_ID="$2";   shift 2 ;;
    --task-id)   TASK_ID="$2";   shift 2 ;;
    *) shift ;;
  esac
done

[[ -z "$QUESTION" ]] && { echo '{"error":"--question is required"}'; exit 1; }

# Step 1: 生成 nGQL
NGQL_ARGS=$(python3 -c "import json,sys; print(json.dumps({'question': sys.argv[1]}))" "$QUESTION") \
  || { echo '{"error":"nGQL generation failed"}'; exit 2; }

NGQL_RESP=$(mcporter call honeybadge-nebula.generate_query \
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

RESULT=$(mcporter call honeybadge-nebula.validate_and_execute \
  --args "$EXEC_ARGS") \
  || { echo '{"error":"query execution failed"}'; exit 3; }

echo "$RESULT"
