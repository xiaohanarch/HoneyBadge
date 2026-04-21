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
NGQL_RESP=$(mcporter call honeybadge-nebula.generate_query \
  --args "{\"question\":\"$QUESTION\"}") \
  || { echo '{"error":"nGQL generation failed"}'; exit 2; }

NGQL=$(echo "$NGQL_RESP" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d['ngql'])" 2>/dev/null) \
  || { echo '{"error":"nGQL generation failed"}'; exit 2; }

# Step 2: 带权限执行
USER_CTX="{}"
[[ -n "$USER_ID" ]] && USER_CTX="{\"user_id\":\"$USER_ID\"}"

RESULT=$(mcporter call honeybadge-nebula.validate_and_execute \
  --args "{\"ngql\":\"$NGQL\",\"user_context\":$USER_CTX}") \
  || { echo '{"error":"query execution failed"}'; exit 3; }

echo "$RESULT"
