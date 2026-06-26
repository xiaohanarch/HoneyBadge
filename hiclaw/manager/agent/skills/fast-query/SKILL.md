---
name: fast-query
description: Manager direct-to-MCP fast path for simple ERP data queries. Bypasses Workers entirely — calls honeybadge-nebula-mcp generate_query + validate_and_execute, then forwards results to user via contract 002.
assign_when: User asks a simple ERP data lookup (查询/搜索/列出/查找/多少/哪个/统计/报告) without complex multi-entity join indicators (关联/匹配/核对/三单).
---

# Fast Query (Manager Direct-to-MCP)

Bypasses the Worker pool entirely. The Manager calls the NebulaGraph MCP server directly via `mcporter`, gets the result, and forwards it to the user via `forward-to-user.sh` (contract 002).

Use the router script to determine if this skill applies:

```bash
ROUTE=$(bash /opt/honeybadge/config/manager/agent/skills/fast-query/router.sh "$USER_QUESTION")
```

If `ROUTE` is `fast-query`, execute:

```bash
bash /opt/honeybadge/config/manager/agent/skills/fast-query/fast-query.sh \
  --question "$USER_QUESTION" \
  --user-id "$USER_ID" \
  --task-id "$TASK_ID" \
  --forward-to-user-id "$FORWARD_USER_ID"
```

After `fast-query.sh` returns `FORWARD_OK`, **STOP**. The result has already been delivered to the user via contract 002. Do NOT call `message` or `replyMessage` — that sends a duplicate and corrupts the UI.

## When to use

- Simple single-entity lookups: "查询供应商", "列出采购订单", "统计发票数量"
- Questions with LIMIT semantics: "前5个采购订单", "最新10条发票"

## When NOT to use

- Multi-entity joins: "查询供应商及其发票"
- Analytics/fraud detection: "分析异常付款"
- Complex matching: "三单匹配异常"

These route to `graph-worker` or `analytics-worker` via `erp-query-dispatch` instead.
