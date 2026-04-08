# HoneyBadge Matrix Gateway Design

**Date**: 2026-04-07 (updated 2026-04-08)
**Status**: Draft
**Type**: Architecture Refactor

## Context

Phase 1 实现发现 HoneyBadge 和 HiClaw 在编排层功能重叠。当前 `DirectPipelineOrchestrator` 是个单节点编排器，跟 HiClaw Manager-Worker 架构重复。

**目标**：将 HoneyBadge 演化为轻量级 Matrix 网关，实际查询逻辑下沉到 HiClaw Worker。

## Terminology

**HoneyBadge Server** = `honeybadge-server` = `honeybadge-gateway`

- **honeybadge-server**: 部署的 FastAPI 应用实例（物理概念）
- **honeybadge-gateway**: honeybadge-server 在 Matrix 网络中的身份/角色（功能概念）

```
honeybadge-server (FastAPI 应用)
  ├── WebSocket (:8090) — 用户连接
  ├── JWT 认证
  ├── 输入过滤
  └── Matrix 客户端 (以 @honeybadge-gateway 身份连接 Matrix)
```

两者是同一个服务，"gateway" 描述的是它的功能角色。

## Decision

### 1. HiClaw 独立部署

HiClaw 用官方 `curl | bash` 安装，独立运行在端口 18088。HoneyBadge 不管理 HiClaw 的生命周期。

**两套 Matrix 服务器：**
- HiClaw 的 Tuwunel (port 6167): HiClaw Manager/Worker 内部通信用
- HoneyBadge 的 Conduit (port 8008): 预留，未来可作为 federation 出口或 Element Web 接入

**连接策略（方案C）：**
honeybadge-server 作为 Matrix 客户端，连接到 HiClaw 的 Tuwunel (6167)，而非自己的 Conduit。

```
HiClaw (独立部署, port 18088)
  └── hiclaw-manager  (Matrix 管理器)
  └── Higress Gateway (:8080/:8001)
  └── Tuwunel/Matrix  (:6167) ◀── honeybadge-server 连接这里
  └── MinIO            (:9000)
  └── Element Web      (:8088)

HoneyBadge (独立 docker-compose, port 8090)
  └── honeybadge-server (Matrix 客户端 → 连接 HiClaw Tuwunel :6167)
  └── nebula-graphd / redis / postgres
  └── nebula-mcp / audit-mcp / cache-mcp
  └── Conduit (:8008) — 预留，不用于 Manager 通信
```

### 2. HoneyBadge 网关职责

`honeybadge-server` 从"编排服务"降级为"Matrix 网关"：

- **JWT 认证**：验证用户 token
- **输入过滤**：空问题检测、写操作关键词检测（网关层轻量检查）
- **Matrix 网关**：WebSocket ↔ Matrix 房间消息双向透传
- **Schema 缓存**：启动时从 Worker 获取并缓存，供 HiClaw Manager 后续使用（或供其他模块引用）

**不做的**：不直接调用 nebula-graph/LLM，不做 L1-L3 验证（由 Worker 负责）

### 3. L1-L3 验证位置

```
User  →  WebSocket  →  honeybadge-server (L1-L3验证)
                               ↓
                          Matrix 房间
                               ↓
                         HiClaw Manager
                               ↓
                         graph-worker
                               ↓
                     mcporter → nebula-mcp → nebula-graph
```

**L1**：Worker 侧 LLM 生成 nGQL 后执行（网关不做）
**L2**：Worker 侧 LLM 生成 nGQL 后执行（网关不做）
**L3**：Worker 侧 LLM 生成 nGQL 后执行（网关不做）

**网关层只做轻量输入过滤**：
- 空问题检测
- 写操作关键词检测（INSERT/UPDATE/DELETE/DROP/ALTER/CREATE）
- JWT 认证

**实际 Anti-Hallucination L1-L3 验证在 Worker 侧执行**，由 HiClaw Worker 的 cypher-query SKILL 负责。

### 4. Schema 缓存机制

- honeybadge-server **启动时**通过 Matrix 向 Manager 发送 "get_schema" 请求
- Manager 调度 Worker 调用 `nebula-mcp.get_schema()` 获取 schema
- Worker 返回 schema 到 Matrix 房间
- honeybadge-server 监听并缓存 schema
- L2 验证使用缓存数据

**Bootstrap 时序**：
```
T=0: honeybadge-server 启动，连接 Matrix
T=1: 发送 Matrix 消息 → Manager: {"type": "get_schema"}
T=2: Manager → graph-worker
T=3: Worker → nebula-mcp.get_schema()
T=4: Worker → Matrix 房间返回 schema
T=5: honeybadge-server 缓存 → 就绪状态
     ↓
用户 query → 输入过滤 → Matrix 房间
(L1-L3 在 Worker 侧执行)
```

**Schema 缓存用途**：供 HiClaw Manager/Worker 在生成 nGQL 时引用最新 schema。gateway 本身不做 L2 验证。

**重要**：honeybadge-server **不直接调用** nebula-mcp，所有 nebula-mcp 调用必须经过 HiClaw Worker 中转。

### 5. Matrix 通信协议

**Matrix 用户身份**：
- honeybadge-server 以 `@honeybadge-gateway:matrix.local` 身份运行
- 向 Manager (@hiclaw-manager:matrix.local) 建立 DM 连接

**消息格式（honeybadge → Manager）**：
```json
{
  "type": "gateway_query",
  "question": "供应商V001的采购订单有哪些？",
  "trace_id": "HB-20260407-001",
  "user_id": "admin",
  "org_id": "org001",
  "roles": ["admin"]
}
```

**消息格式（Manager/Worker → honeybadge）**：
```json
{
  "type": "result",
  "trace_id": "HB-20260407-001",
  "data": { ... },
  "summary": "查询到3条采购订单..."
}
```

```json
{
  "type": "error",
  "trace_id": "HB-20260407-001",
  "error_code": "L2_SCHEMA_VALIDATION_FAILED",
  "error_message": "Tag 'Person' does not exist",
  "recoverable": false
}
```

**事件监听**：matrix-nio auto-sync 模式，后台 WebSocket 同步

**Session-Room 映射**：
```
session_id → Matrix room_id
session_123 → !abc123:matrix.local (DM with Manager)
session_456 → !def456:matrix.local (DM with Manager)
```

### 6. HiClaw Manager 任务流转

```
1. honeybadge-server → Matrix 房间发送：{"type": "question", "question": "...", "trace_id": "..."}
2. Manager 收到消息，识别为 "simple query"
3. Manager → 创建/复用 graph-worker
4. Worker 通过 mcporter → nebula-mcp → nebula-graph 执行查询
5. Worker → Matrix 房间返回结果
6. honeybadge-server 监听并透传给用户 WebSocket
```

Manager 的 SOUL.md / AGENTS.md 定义路由策略，HoneyBadge 不需要修改 HiClaw 的 agent 定义。

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  User WebSocket                                                      │
│    │                                                                 │
│    │ {"type": "query", "question": "供应商V001的采购订单有哪些？"}     │
│    ▼                                                                 │
│  honeybadge-server (Gateway)                                         │
│    │                                                                 │
│    ├── JWT 认证 (验证 token)                                         │
│    ├── 输入过滤 (空问题/写操作检测)                                    │
│    │                                                                 │
│    └── 通过 matrix-nio 发送 DM 到 Manager                              │
│           │                                                          │
│           ▼                                                          │
│    Matrix DM 房间 (honeybadge-gateway ↔ Manager)                    │
│           │                                                          │
│           ▼                                                          │
│    HiClaw Manager (OpenClaw)                                         │
│           │                                                          │
│           ├── 意图识别：simple query → graph-worker                  │
│           │                                                          │
│           ▼                                                          │
│    graph-worker                                                      │
│           │                                                          │
│           ├── get_schema()                                           │
│           ├── generate_ngql() → LLM (via Higress)                  │
│           ├── L1 语法验证 ← (anti-hallucination)                     │
│           ├── L2 Schema 验证 ← (anti-hallucination)                  │
│           ├── L3 权限验证 ← (anti-hallucination)                     │
│           │      ↓                                                  │
│           │   nebula-mcp → nebula-graph                             │
│           │                                                         │
│           └── 结果/错误 → Matrix DM 房间                              │
│                  │                                                   │
│                  ▼                                                   │
│    honeybadge-server (监听 Matrix 事件)                              │
│           │                                                          │
│           ▼                                                          │
│    User WebSocket ← 实时推送结果/错误                                 │
└─────────────────────────────────────────────────────────────────────┘
```

**关键约束**：honeybadge-server **不直接调用** nebula-mcp，所有 MCP 调用必须经由 Worker。

## Components

### honeybadge-server (重构)

**新增**：
- `src/honeybadge/gateway/matrix_client.py` — Matrix SDK 客户端封装
- `src/honeybadge/gateway/schema_cache.py` — L2 schema 缓存管理
- `src/honeybadge/gateway/room_manager.py` — Matrix 房间映射管理

**移除**：
- `DirectPipelineOrchestrator`（L1-L5 编排逻辑迁移到 Worker）
- `LLMAdapter` 直接调用（Worker 侧通过 Higress 调用 LLM）
- 直连 nebula-mcp 的调用（所有 MCP 调用必须经由 Worker）

**保留/修改**：
- JWT auth（保留）
- L1-L3 validator（保留，但 schema 从 Worker 经 Matrix 返回后缓存）
- WebSocket handler（改为透传 Matrix 消息）
- PostgreSQL audit log（保留，写入 L5 审计）
- Redis cache（MCP 共享）

### nebula-mcp

**仅 HiClaw Worker 可访问**：nebula-mcp 只被 Worker 通过 mcporter 调用，honeybadge-server 不直接访问。

- Worker 调用 `get_schema()` / `generate_ngql()` / `validate_and_execute()`
- honeybadge-server 通过 Matrix 消息获取 schema（不上手直接调）

### HiClaw Worker (graph-worker)

**使用现有的** cypher-query SKILL.md 逻辑，无需修改 HoneyBadge 代码侧。

## Implementation Sequence

### Phase 1.1: Matrix Gateway基础 (本次实现)
1. 新增 `MatrixClient` 类（基于 matrix-nio SDK）
2. 实现 schema_cache 模块
3. 在 honeybadge-server 启动时通过 Matrix DM 向 Manager 请求 schema 并缓存
4. 修改 WebSocket handler 为透传模式
5. 添加 Matrix 房间管理（session → room_id 映射）

### Phase 1.2: HiClaw 集成
1. HiClaw 独立部署配置（docker-compose 外运行）
2. honeybadge-server 作为 Matrix 用户加入 DM
3. 消息收发联调

### Phase 1.3: Bug 修复
1. 修复 PostgreSQL `chat_sessions` 和 `chat_messages` 表未初始化问题
2. 确保 `NgqlValidator.load_schema()` 在 schema_cache 就绪后被调用

## Verification

- 单元测试：L1-L3 validator（已有，覆盖）
- 集成测试：Matrix 消息收发
- E2E 测试：User → WebSocket → Matrix → Worker → nebula-graph → 结果回传

## Resolved Questions

### 1. Matrix 事件监听方式
**决定**：WebSocket（matrix-nio auto-sync）

理由：honeybadge-server 已有 WebSocket 基础设施，matrix-nio 的 auto-sync 模式是官方推荐后台同步方式，开销低、延迟小。

### 2. Manager 如何识别 honeybadge-server 发来的消息
**决定**：honeybadge-gateway 作为专用 Matrix 用户，向 Manager 发 DM

honeybadge-server 以 `@honeybadge-gateway:matrix.local` 身份向 Manager (@hiclaw-manager:matrix.local) 发送 DM：
```json
{
  "type": "gateway_query",
  "question": "...",
  "trace_id": "...",
  "user_id": "...",
  "org_id": "..."
}
```

### 3. Worker 查询失败时错误透传
**决定**：Worker 把错误发送到同一 DM 房间，honeybadge-server 监听并转发

```json
{
  "type": "error",
  "trace_id": "HB-20260407-xxx",
  "error_code": "L2_SCHEMA_VALIDATION_FAILED",
  "error_message": "Tag 'Person' does not exist in schema",
  "recoverable": false
}
```

honeybadge-server 收到后根据 `trace_id` 找到对应 WebSocket 推送 `ErrorMessage`。

### 4. 多用户并发时 Matrix 房间隔离策略
**决定**：每个用户会话一个 Matrix DM 房间（与 Manager 一对一）

```
用户A (session_123) → WebSocket → honeybadge-server → Matrix DM → Manager
用户B (session_456) → WebSocket → honeybadge-server → Matrix DM → Manager
                                                          ↑
                                               两个独立的 DM 房间
```

honeybadge-server 维护 `session_id → DM room_id` 映射表。

## References

- HiClaw: http://github.com/alibaba/hiClaw
- HiClaw Manager SOUL.md / AGENTS.md
- HoneyBadge validator.py (L1-L3 实现)
- HoneyBadge docker-compose.yaml (当前基础设施定义)
