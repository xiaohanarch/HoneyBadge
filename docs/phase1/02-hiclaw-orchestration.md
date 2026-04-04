# HiClaw 编排层设计

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：`01-nebula-schema.md`, `04-llm-adapter.md`

---

## 1. 架构概览

```
用户 → Higress 网关 → HiClaw Manager → 消息队列(Matrix) → Worker Pool
                                                              │
                                              ┌───────────────┼───────────────┐
                                              ▼               ▼               ▼
                                        graph-worker    analytics-worker  mcp-worker
                                              │               │               │
                                              ▼               ▼               ▼
                                        NebulaGraph      NebulaGraph      MCP Servers
                                        LLM API          LLM API          (联邦查询)
                                        Redis            Redis
```

---

## 2. Manager 配置

### 2.1 部署参数

| 参数 | 开发环境 | 生产环境 |
|------|---------|---------|
| 副本数 | 1 | 2-3 |
| CPU | 2 核 | 4 核 |
| 内存 | 4 GB | 8 GB |
| 磁盘 | 10 GB | 50 GB |
| 健康检查端点 | `/health` | `/health` |
| 健康检查间隔 | 30s | 10s |
| 就绪探针 | `/ready` | `/ready` |

### 2.2 Manager 职责

1. **接收用户请求**：通过 Matrix Room 接收前端 WebSocket 消息
2. **任务分析与路由**：判断查询类型，选择对应 Worker 组
3. **Worker 调度**：将任务分发到空闲 Worker
4. **心跳监控**：检测 Worker 存活，超时自动重启
5. **会话管理**：创建/恢复/清理 Matrix Room

### 2.3 Manager 配置文件

```yaml
# hiclaw-manager.yaml
manager:
  name: honeybadge-manager
  runtime: openclaw
  model:
    provider: openai_compatible
    endpoint: ${LLM_ENDPOINT}
    api_key: ${LLM_API_KEY}
    model: ${LLM_MODEL_NAME}

  # Worker 路由规则
  routing:
    rules:
      - pattern: "查询|查找|搜索|有哪些|列出"
        worker_group: graph-worker
      - pattern: "分析|趋势|对比|统计|异常|检测"
        worker_group: analytics-worker
      - pattern: "外部数据|EBS|Oracle|其他系统"
        worker_group: mcp-worker
      - default: graph-worker

  # 资源限制
  worker_pool:
    max_workers: 8
    idle_timeout: 300s    # 空闲 5 分钟停止 Worker
    task_timeout: 120s    # 单任务最长 2 分钟

  # Matrix 配置
  matrix:
    homeserver: ${MATRIX_HOMESERVER_URL}
    bot_user: "@honeybadge-manager:matrix.local"
    bot_token: ${MATRIX_BOT_TOKEN}
```

---

## 3. Worker 分组设计

### 3.1 graph-worker（图谱查询）

**职责**：处理标准自然语言→Cypher 查询的完整流程。

```
输入: 用户自然语言问题
流程: NL → Cypher 生成 → L1/L2 校验 → 执行 → 结果摘要
输出: AI 摘要 + 原始数据 + Cypher + trace_id
```

**Skill 定义**：

```yaml
# graph-worker-skill.yaml
worker:
  name: graph-worker
  group: graph
  runtime: openclaw
  replicas: 2

  skills:
    - name: cypher_query
      description: "将自然语言转换为 nGQL 查询并执行"
      input:
        - user_question: string
        - session_context: object  # 上下文
      output:
        - summary: string
        - raw_data: object
        - cypher: string
        - trace_id: string

  mcp_tools:
    - name: nebula-query
      description: "执行 nGQL 查询"
      server: nebula-mcp-server
    - name: llm-generate
      description: "调用 LLM 生成 Cypher / 摘要"
      server: llm-mcp-server

  resources:
    cpu: 2
    memory: 4Gi
```

**执行流程**：

```
1. 接收用户问题
2. 加载本体 Prompt 模板（Phase 1: 全量注入）
3. 调用 LLM 生成 nGQL
4. L1: 语法校验 (parser)
5. L2: Schema 合规校验
6. L3: 权限框架校验 (Phase 1 预留)
7. 执行 nGQL → NebulaGraph
8. 调用 LLM 生成自然语言摘要
9. 写入审计日志
10. 返回结果
```

### 3.2 analytics-worker（复杂分析）

**职责**：处理需要多步推理的复杂分析查询。

```
输入: 复杂分析问题（如"找出虚假交易嫌疑"）
流程: 问题分解 → 多步 Cypher → 中间结果整合 → 分析结论
输出: 分析报告 + 中间步骤 + 原始数据
```

**Skill 定义**：

```yaml
worker:
  name: analytics-worker
  group: analytics
  runtime: openclaw
  replicas: 1

  skills:
    - name: multi_step_analysis
      description: "多步推理分析，支持问题分解和中间结果整合"
      input:
        - user_question: string
        - analysis_type: string  # anomaly_detection / trend / comparison
      output:
        - report: string
        - steps: list[object]    # 每步的 Cypher + 结果
        - trace_id: string

  mcp_tools:
    - name: nebula-query
      server: nebula-mcp-server
    - name: llm-generate
      server: llm-mcp-server
    - name: redis-cache
      server: redis-mcp-server

  resources:
    cpu: 4
    memory: 8Gi
```

### 3.3 mcp-worker（MCP 联邦查询）

**职责**：处理需要访问外部系统的查询（Phase 1 为预留，Phase 3 扩展）。

```yaml
worker:
  name: mcp-worker
  group: mcp
  runtime: openclaw
  replicas: 1

  skills:
    - name: federated_query
      description: "跨系统联邦查询"
      input:
        - user_question: string
        - target_systems: list[string]
      output:
        - result: object
        - source_systems: list[string]
        - trace_id: string

  mcp_tools:
    - name: nebula-query
      server: nebula-mcp-server
    - name: llm-generate
      server: llm-mcp-server
    # Phase 3 扩展
    # - name: oracle-ebs
    #   server: ebs-mcp-server
    # - name: crm-query
    #   server: crm-mcp-server

  resources:
    cpu: 2
    memory: 4Gi
```

---

## 4. Matrix Room 生命周期管理

### 4.1 Room 创建

```
用户首次登录:
  1. Manager 检查 Redis 中是否有该用户的活跃 Room
  2. 若无，创建新 Matrix Room: !room_{user_id}_{session_id}:matrix.local
  3. 邀请 Manager Bot 和相关 Worker Bot 加入
  4. 在 Redis 记录 Room 映射: session:{user_id}:{session_id} → room_id
```

### 4.2 Room 恢复

```
用户再次访问已有会话:
  1. 前端发送 session_id
  2. Manager 从 Redis 获取 room_id
  3. 恢复 Room 上下文（最近 N 条消息）
  4. 继续对话
```

### 4.3 超时清理

```
清理策略:
  - 空闲 Room（30 分钟无消息）: 保留 Room 元数据，释放 Worker 资源
  - 过期 Room（7 天无活动）: 归档到 PostgreSQL，从 Matrix 删除
  - 手动清理: 用户删除会话时，同步删除 Room

定时任务 (Cron):
  - 每 5 分钟: 检查空闲 Room，释放关联 Worker
  - 每天凌晨: 归档过期 Room
```

---

## 5. 会话状态设计

### 5.1 短期状态（Redis）

```
Key: session:{user_id}:{session_id}
Type: Hash
TTL: 30 minutes (sliding)

Fields:
  room_id          - Matrix Room ID
  created_at       - 会话创建时间
  last_active      - 最后活跃时间
  message_count    - 消息数
  context_summary  - LLM 上下文摘要 (最近对话的压缩版)
  active_worker    - 当前分配的 Worker ID
```

```
Key: user_sessions:{user_id}
Type: Sorted Set (score = last_active timestamp)
TTL: none

Members: session_id 列表，按最后活跃时间排序
```

### 5.2 长期状态（PostgreSQL）

```sql
CREATE TABLE chat_sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         VARCHAR(64) NOT NULL,
  session_id      VARCHAR(64) NOT NULL UNIQUE,
  title           VARCHAR(256),       -- 会话标题（第一个问题或 LLM 生成）
  room_id         VARCHAR(256),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  archived_at     TIMESTAMPTZ,
  message_count   INT DEFAULT 0,
  status          VARCHAR(20) DEFAULT 'active'  -- active / archived / deleted
);

CREATE INDEX idx_sessions_user ON chat_sessions(user_id, status);
CREATE INDEX idx_sessions_updated ON chat_sessions(updated_at DESC);

CREATE TABLE chat_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      VARCHAR(64) NOT NULL REFERENCES chat_sessions(session_id),
  role            VARCHAR(20) NOT NULL,  -- user / assistant / system
  content         TEXT NOT NULL,
  message_type    VARCHAR(20) DEFAULT 'text',  -- text / cypher / data / error
  metadata        JSONB,               -- trace_id, cypher, raw_data 等
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_session ON chat_messages(session_id, created_at);
```

---

## 6. MCP Server 集成方式

### 6.1 mcporter CLI 配置

```yaml
# mcp-servers.yaml
servers:
  nebula-mcp-server:
    command: "python"
    args: ["-m", "honeybadge.mcp.nebula_server"]
    env:
      NEBULA_HOST: ${NEBULA_GRAPHD_HOST}
      NEBULA_PORT: ${NEBULA_GRAPHD_PORT}
      NEBULA_USER: ${NEBULA_USER}
      NEBULA_PASSWORD: ${NEBULA_PASSWORD}
      NEBULA_SPACE: honeybadge
    tools:
      - execute_ngql        # 执行 nGQL 查询
      - get_schema          # 获取当前 Schema
      - validate_ngql       # 校验 nGQL 语法

  llm-mcp-server:
    command: "python"
    args: ["-m", "honeybadge.mcp.llm_server"]
    env:
      LLM_ENDPOINT: ${LLM_ENDPOINT}
      LLM_API_KEY: ${LLM_API_KEY}
    tools:
      - generate_cypher     # 生成 nGQL
      - summarize_result    # 摘要结果
      - classify_query      # 查询分类

  redis-mcp-server:
    command: "python"
    args: ["-m", "honeybadge.mcp.redis_server"]
    env:
      REDIS_URL: ${REDIS_URL}
    tools:
      - get_session         # 获取会话状态
      - set_session         # 设置会话状态
      - cache_result        # 缓存查询结果
```

### 6.2 Worker 中引用 MCP Server

```yaml
# 在 Worker Skill 中引用
skills:
  - name: cypher_query
    tools:
      - server: nebula-mcp-server
        tools: [execute_ngql, get_schema, validate_ngql]
      - server: llm-mcp-server
        tools: [generate_cypher, summarize_result]
      - server: redis-mcp-server
        tools: [cache_result]
```

---

## 7. 与 Phase 0 OpenClaw 的迁移路径

### 7.1 迁移策略：渐进式

```
Phase 0 (当前):
  OpenClaw Agent → Neo4j MCP → 云端 LLM

Phase 1 迁移步骤:
  Step 1: 部署 HiClaw + Matrix Server
  Step 2: 将 OpenClaw Agent 逻辑迁移为 HiClaw Worker Skill
          (HiClaw Worker 运行时支持 OpenClaw Skills)
  Step 3: 替换 Neo4j MCP → NebulaGraph MCP
  Step 4: 接入 Higress 网关
  Step 5: 添加前端 WebSocket 连接
```

### 7.2 Skill 迁移对照

| Phase 0 (OpenClaw) | Phase 1 (HiClaw Worker) | 变化 |
|---------------------|------------------------|------|
| `neo4j_query` tool | `nebula-mcp-server.execute_ngql` | Neo4j→NebulaGraph |
| Cypher 生成 Prompt | nGQL 生成 Prompt（加 Tag 前缀规则） | Prompt 模板更新 |
| 直接 LLM 调用 | `llm-mcp-server.generate_cypher` | 封装为 MCP Server |
| 无会话管理 | Redis + PostgreSQL 会话状态 | 新增 |
| 无审计 | L5 审计日志 | 新增 |
| 无 Schema 校验 | L1+L2 校验 | 新增 |

### 7.3 并行运行期

建议 Phase 1 初期（2-4 周）保持 Phase 0 系统并行运行：
- 新查询同时发送到 Phase 0 和 Phase 1
- 对比结果一致性
- 确认 nGQL 生成质量达标后，切换到 Phase 1

---

## 8. 错误处理与重试

### 8.1 Worker 级错误处理

| 错误类型 | 处理方式 |
|---------|---------|
| LLM 调用超时 | 重试 1 次，失败则降级到备选模型 |
| nGQL 语法错误 | 反馈给 LLM 重新生成（最多 3 次） |
| Schema 校验失败 | 反馈具体错误给 LLM 重新生成 |
| NebulaGraph 连接失败 | 重试 2 次（间隔 1s/2s），失败则报错 |
| Worker 崩溃 | Manager 检测心跳失败，重新分配任务到新 Worker |

### 8.2 Manager 级错误处理

| 错误类型 | 处理方式 |
|---------|---------|
| 所有同组 Worker 不可用 | 返回"服务繁忙"消息 |
| Matrix Room 创建失败 | 重试 1 次，失败则报错 |
| Redis 不可用 | 降级为内存会话（不持久化） |

---

## 9. WebSocket 消息协议

Manager 通过 WebSocket 与前端通信，使用以下 JSON 消息类型。

### 9.1 客户端 → 服务端

| type | 说明 | payload |
|------|------|---------|
| `query` | 用户提交问题 | `{question: string, session_id: string}` |
| `heartbeat` | 心跳保活 | `{}` |

### 9.2 服务端 → 客户端

| type | 说明 | payload |
|------|------|---------|
| `progress` | 执行步骤更新 | `{step: string, step_number: int, total_steps: int, detail?: string}` |
| `stream` | 流式文本输出 | `{content: string, phase: string, done: boolean}` |
| `response` | 最终完整结果 | `{summary: string, raw_data: list, columns: list, cypher: string, trace_id: string, execution_time_ms: int, row_count: int}` |
| `error` | 错误消息 | `{code: string, message: string, trace_id?: string}` |
| `heartbeat` | 心跳响应 | `{}` |

### 9.3 stream.phase 取值

| phase | 说明 | 触发时机 |
|-------|------|---------|
| `thinking` | 理解问题 | Manager 分析用户问题时 |
| `cypher` | 生成查询 | Worker 调用 LLM 生成 nGQL 时 |
| `executing` | 执行查询 | Worker 向 NebulaGraph 发起查询时 |
| `summarizing` | 生成摘要 | Worker 调用 LLM 生成结果摘要时 |

### 9.4 error.code 错误码

| code | 说明 |
|------|------|
| `VALIDATION_FAILED` | nGQL 校验失败（重试耗尽） |
| `EXECUTION_ERROR` | NebulaGraph 执行错误 |
| `LLM_ERROR` | LLM 调用失败 |
| `TIMEOUT` | 请求超时 |
| `RATE_LIMIT` | 超出限流/配额 |
| `SERVICE_UNAVAILABLE` | 服务不可用 |
| `INTERNAL_ERROR` | 内部错误 |

### 9.5 消息示例

```json
// 客户端发送查询
{"type": "query", "payload": {"question": "帮我找出疑似虚假交易", "session_id": "sess_abc123"}, "timestamp": 1712188800000}

// 服务端推送进度
{"type": "progress", "payload": {"step": "正在理解您的问题", "step_number": 1, "total_steps": 5}, "trace_id": "TRC-20260404-00147", "timestamp": 1712188800100}

// 服务端流式输出摘要
{"type": "stream", "payload": {"content": "发现", "phase": "summarizing", "done": false}, "trace_id": "TRC-20260404-00147", "timestamp": 1712188805000}
{"type": "stream", "payload": {"content": "3笔疑似异常交易", "phase": "summarizing", "done": false}, "trace_id": "TRC-20260404-00147", "timestamp": 1712188805100}
{"type": "stream", "payload": {"content": "", "phase": "summarizing", "done": true}, "trace_id": "TRC-20260404-00147", "timestamp": 1712188805200}

// 服务端返回完整结果
{"type": "response", "payload": {"summary": "发现3笔疑似异常交易...", "raw_data": [...], "columns": ["po_number", "po_amount", "inv_amount"], "cypher": "MATCH ...", "trace_id": "TRC-20260404-00147", "execution_time_ms": 4850, "row_count": 3}, "timestamp": 1712188805300}
```
