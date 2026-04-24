#!/usr/bin/env bash
# router.sh — Deterministic routing for ERP user queries
#
# Outputs one of: fast-query | graph-worker | analytics-worker
# Usage: bash router.sh "$USER_QUESTION"
#
# Rules (in priority order):
#   1. Analytics keywords → analytics-worker
#   2. Simple lookup + no complex join indicators → fast-query
#   3. Everything else → graph-worker

QUESTION="${1:-}"

if [[ -z "$QUESTION" ]]; then
    echo "graph-worker"
    exit 0
fi

# Priority 1: Analytics / complex analysis → analytics-worker
if echo "$QUESTION" | grep -qEi \
    "分析|趋势|异常|欺诈|三单|匹配|检测|对比|审计|风险|预测|fraud|anomal|detect|duplicate|trend"; then
    echo "analytics-worker"
    exit 0
fi

# Priority 2: Simple single-entity lookup → fast-query
# Condition A: contains a lookup verb
LOOKUP_VERBS="查询|搜索|列出|查找|一共|总数|数量|多少|哪个|哪些|显示|获取|show|list|find|count"
# Condition B: does NOT contain complex multi-entity join indicators
COMPLEX_INDICATORS="关联|匹配|对应|核对|对账|关系|是否.*关联|三单|供应商.*订单.*发票|发票.*订单|交叉|join"

if echo "$QUESTION" | grep -qEi "$LOOKUP_VERBS"; then
    if ! echo "$QUESTION" | grep -qEi "$COMPLEX_INDICATORS"; then
        echo "fast-query"
        exit 0
    fi
fi

# Default: graph-worker
echo "graph-worker"
