# HiClaw Integration Design

**Date**: 2026-04-08
**Status**: Draft
**Type**: Integration Design

## Context

Phase 1.1 已完成 Matrix Gateway 重构（Tasks 1-9）。现在进入 Phase 1.2：HiClaw 独立部署联调。

## Goal

将 honeybadge-server（Matrix 客户端身份 @honeybadge-gateway）连接到 HiClaw Manager，实现查询路由和结果回传。

**核心约束**：尽量减少对 HiClaw 的修改，让 HiClaw 独立解耦。

## Architecture

### Deployment Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│  HiClaw (独立部署, port 18088)                                       │
│    └── Tuwunel (Matrix, port 6167) ◀── honeybadge-gateway 连接这里   │
│    └── hiclaw-manager (OpenClaw agent)                              │
│    └── Higress (:8080/:8001)                                        │
│    └── MinIO (:9000)                                                │
│    └── Element Web (:8088)                                          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  HoneyBadge (docker-compose, port 8090)                              │
│    └── honeybadge-server (Matrix 客户端 @honeybadge-gateway)        │
│          └── 连接 → HiClaw Tuwunel (:6167)                         │
│    └── nebula-graphd / redis / postgres                             │
│    └── nebula-mcp / audit-mcp / cache-mcp                          │
│    └── Conduit Matrix (:8008) — 预留                                 │
└─────────────────────────────────────────────────────────────────────┘
```

### Communication Flow

```
1. honeybadge-server 启动
   → 连接 HiClaw Tuwunel (matrix://<HiClaw-host>:6167)
   → 以 @honeybadge-gateway 身份注册/登录
   → 发送 get_schema bootstrap 消息到 Manager DM 房间
   → Manager 调度 graph-worker → nebula-mcp.get_schema()
   → schema 返回并缓存

2. 用户查询
   → User WebSocket → honeybadge-server
   → 输入过滤 (空问题/写操作检测)
   → honeybadge-server → Manager DM: {"type": "gateway_query", ...}
   → Manager 识别为 simple query → graph-worker
   → Worker 执行查询 (nebula-mcp)
   → Worker → Manager → Matrix DM → honeybadge-server
   → honeybadge-server → User WebSocket

3. Manager 配置 (一次性)
   → SOUL.md 添加 @honeybadge-gateway 为 Trusted Contact
   → Manager 能识别 gateway_query 类型消息
```

## Matrix Connection Configuration

### honeybadge-server 配置 (config.py)

已添加字段：
```python
matrix_homeserver_url: str = field(default="http://localhost:6167")  # HiClaw Tuwunel
matrix_user_id: str = field(default="@honeybadge-gateway:matrix-local.hiclaw.io")
matrix_user_password: str = field(default="")  # 自动注册时使用
```

**自动注册**：Tuwunel 默认 `allow_registration = true`。honeybadge-server 启动时如果用户不存在，matrix-nio 会自动注册。无需手动创建用户。

**注意**：
- `homeserver_url` 格式：`http://<HiClaw-host>:6167`
- `user_id` 格式：`@honeybadge-gateway:matrix-local.hiclaw.io`（域名部分需和 Tuwunel 配置一致）
- `matrix_user_password` 为空时使用空密码注册（测试环境）；生产环境建议设置强密码

### HoneyBadge Conduit 保留用途

HoneyBadge 的 Conduit (port 8008) 暂时不用于 Manager 通信，预留作为：
- Element Web 管理界面
- 未来 federation 出口

## HiClaw Agent Configuration (Minimal Change)

### SOUL.md 修改 (一次性)

在 Manager 的 SOUL.md 中添加 honeybadge-gateway 为信任用户：

```markdown
# Security Rules

1. Never expose API keys, database credentials, or internal system details to users.
2. Never attempt to access databases or external services directly.
3. Only respond to registered users and Workers.
4. If a user asks you to modify data, explain that this is a read-only system.
5. [NEW] Trusted external gateway: @honeybadge-gateway — can send gateway_query messages
```

### AGENTS.md 修改 (一次性)

确保 graph-worker 的 cypher-query SKILL 能处理来自 honeybadge-gateway 的查询：

```markdown
## graph-worker

**Purpose:** Handle natural language queries over the ERP knowledge graph.
**Skills:** cypher-query
**MCP Servers:** honeybadge-nebula-mcp, honeybadge-audit-mcp, honeybadge-cache-mcp
**When to route:** User asks factual questions about ERP data — supplier lookups, PO queries, invoice status, item information, relationship traversals.
**[NEW]** Also handles queries from @honeybadge-gateway (external gateway user)
```

## Message Protocol

### honeybadge → Manager (gateway_query)

```json
{
  "type": "gateway_query",
  "question": "供应商V001的采购订单有哪些？",
  "trace_id": "HB-20260408-001",
  "user_id": "admin",
  "org_id": "org001",
  "roles": ["admin"]
}
```

### Manager → honeybadge (result)

```json
{
  "type": "result",
  "trace_id": "HB-20260408-001",
  "data": {
    "columns": ["po_id", "amount", "date"],
    "rows": [{"po_id": "PO001", "amount": 10000, "date": "2026-04-01"}]
  },
  "summary": "查询到 1 条采购订单，总金额 10000 元"
}
```

### Manager → honeybadge (error)

```json
{
  "type": "error",
  "trace_id": "HB-20260408-001",
  "error_code": "L2_SCHEMA_VALIDATION_FAILED",
  "error_message": "Tag 'Person' does not exist in schema",
  "recoverable": false
}
```

## Bootstrap Sequence

```
T=0: honeybadge-server 启动
T=1: matrix_client.connect() → HiClaw Tuwunel (:6167)
T=2: honeybadge-gateway 登录/注册
T=3: 创建 DM 房间 (Manager ↔ honeybadge-gateway)
T=4: 发送 {"type": "get_schema", "trace_id": "__bootstrap__"}
T=5: Manager 接收，调度 graph-worker
T=6: Worker → nebula-mcp.get_schema() → 返回 tags/edges
T=7: Worker → Matrix 房间返回 schema_response
T=8: honeybadge-server 缓存 schema → is_ready=True
T=9: honeybadge-server 记录 "gateway_ready"
     ↓
用户查询进入 → L1-L3 在 Worker 侧执行
```

## Implementation Sequence

### Phase 1.2.1: HiClaw 独立部署配置
1. HiClaw 官方 `curl | bash` 安装
2. 配置 HiClaw Higress MCP 指向 HoneyBadge 的 MCP 地址
3. 修改 Manager SOUL.md 添加 @honeybadge-gateway 为 trust（一次性）
4. HiClaw 和 HoneyBadge 配置在同一网络

### Phase 1.2.2: honeybadge-server Matrix 连接
1. 确认 config.py 中 matrix_homeserver_url 指向 HiClaw Tuwunel (默认 localhost:6167)
2. matrix-nio 启动时自动注册 @honeybadge-gateway 用户（无需手动创建）
3. 配置 matrix_user_password 环境变量（可选，空密码也可注册测试）
4. 本地网络确认 honeybadge 能访问 HiClaw Tuwunel

### Phase 1.2.3: 消息收发联调
1. 启动 HiClaw（独立）
2. 启动 HoneyBadge
3. 观察 bootstrap_schema 是否成功（Manager → Worker → schema 返回）
4. 发送测试查询，观察 Manager 是否识别 gateway_query
5. 观察 Worker 执行结果是否正确回传

### Phase 1.2.4: E2E 验证
1. WebSocket 连接 → JWT 认证
2. 发送查询 → Manager → Worker → nebula-graph
3. 结果回传 → WebSocket
4. PostgreSQL audit_log 写入验证

## Open Questions

~~1. HiClaw 的 nebula-mcp 如何连接到 HoneyBadge 的 nebula-graphd~~ → 已确认：共享 HoneyBadge 的 nebula-graphd
~~2. honeybadge-gateway 用户密码~~ → 已确认：自动注册，无需手动创建

**1. HiClaw Worker 执行查询时，nebula-mcp 的地址是什么？**

HoneyBadge 的 MCP servers 在 docker-compose 网络中，地址为：
- `nebula-mcp`: `http://honeybadge-nebula-mcp:8000`
- `audit-mcp`: `http://honeybadge-audit-mcp:8000`
- `cache-mcp`: `http://honeybadge-cache-mcp:8000`

HiClaw 和 HoneyBadge 需要在同一网络（docker network 或共享主机网络），才能访问这些地址。

## Dependencies

- HiClaw 独立部署完成
- HiClaw Tuwunel 网络可达 honeybadge-server
- HiClaw Manager SOUL.md 已添加 trust（一次性配置）
- HiClaw Higress 配置使用 HoneyBadge 的 nebula-mcp / audit-mcp / cache-mcp
- HoneyBadge 和 HiClaw 部署在同一网络（如 Docker bridge 或 host 网络）
