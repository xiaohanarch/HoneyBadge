# Project HoneyBadge

**企业知识图谱智能助手** — 基于 ERP 系统（Oracle EBS / 定制 ERP）构建的自然语言问答系统，支持采购/供应链数据查询、欺诈检测和三单匹配异常检测。

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/xiaohanarch/HoneyBadge)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](LICENSE)

---

## 目录

- [项目目标](#项目目标)
- [核心特性](#核心特性)
- [技术架构](#技术架构)
- [设计原则](#设计原则)
- [开发阶段](#开发阶段)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [API 文档](#api-文档)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [联系与支持](#联系与支持)

---

## 项目目标

HoneyBadge 旨在为企业提供：

1. **自然语言查询** — 用户使用自然语言查询 ERP 系统中的采购/供应链数据，无需编写 SQL 或 Cypher
2. **防幻觉保障** — 五层 Cypher 校验框架，确保 LLM 生成的查询语法正确、符合 Schema、满足权限
3. **全链路审计** — 每个查询都有唯一的 `trace_id`，实现问题溯源和审计合规
4. **智能路由** — 根据查询复杂度自动选择合适的 LLM（简单查询用轻量模型，复杂分析用旗舰模型）

---

## 核心特性

### 1. 知识图谱引擎
- **NebulaGraph** 分布式图数据库（v3.8）
- 完整 PTP（采购到付款）+ OTC（订单到收款）数据模型
- 27 种标签（Tag）+ 38 种边类型（Edge Type）

### 2. 智能 Agent 编排
- **HiClaw** 阿里巴巴开源的多 Agent 协作框架（v1.0.6）
- Manager-Worker 架构，任务解耦与弹性伸缩
- Matrix 协议通信，所有交互可审计
- **每个用户独立 Matrix 账号**（`@hb-{用户名}:matrix-local.hiclaw.io`），彻底隔离会话

### 3. 五层防幻觉框架

| 层级 | 名称 | 功能 |
|------|------|------|
| L1 | 语法校验 | Cypher/nGQL 语法检查，错误拒绝并重试 |
| L2 | Schema 校验 | 验证标签/边类型/属性是否符合图谱定义 |
| L3 | 权限校验 | 注入数据范围过滤（org_id/dept_id） |
| L4 | 结果透传 | LLM 仅格式化输出，不修改数据 |
| L5 | 全链路审计 | PostgreSQL 记录 question → Cypher → result → summary |

### 4. 原生 Matrix 通信（Approach B）
- 浏览器通过 **matrix-js-sdk** 直接连接 Tuwunel Matrix 服务器
- 登录时由 `honeybadge-auth` 服务自动在 Tuwunel 中创建用户专属 Matrix 账号
- 权限 JWT（roles_jwt）随 Matrix 消息传递给 graph-worker

### 5. 可观测性（可选）
- **Prometheus** 指标采集
- **Grafana** 可视化看板（端口 3030）
- **Loki** 日志聚合
- **Alertmanager** 告警路由

> 启动方式：`docker compose --profile observability up -d`

---

## 技术架构

### Phase 1 架构图（Approach B — 当前）

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              HoneyBadge Phase 1 部署架构                             │
│                              （实际运行状态 · 2026-04-13）                          │
└─────────────────────────────────────────────────────────────────────────────────┘

  ╔═══════════════════════════════════════════════════════════════════════════════╗
  ║                           第1层：用户接入层（用户可见）                              ║
  ╠═══════════════════════════════════════════════════════════════════════════════╣
  ║                                                                               ║
  ║  ┌─────────────────────────────────────────────────────────────────────────┐ ║
  ║  │                   honeybadge-frontend (:3000)                             │ ║
  ║  │              Vue 3 + matrix-js-sdk · 第一用户可见对接组件                   │ ║
  ║  └─────────────────────────────────────────────────────────────────────────┘ ║
  ║          │                                                                  ║
  ║          ├── POST /login ──→ honeybadge-auth (:8091)                        ║
  ║          │                        认证用户 · 创建 Matrix 专属账号                ║
  ║          │                        返回 matrix_token + roles_jwt               ║
  ║          │                                                                    ║
  ║          └── matrix-js-sdk 直连 ──→ honeybadge-hiclaw-manager (:6167)        ║
  ║                                       Tuwunel Matrix Server                     ║
  ║                                                                               ║
  ╚═══════════════════════════════════════════════════════════════════════════════╝

                                              │ Matrix 协议分发任务
                                              ▼
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │                           honeybadge-hiclaw-manager (:6167等)                    │
  │  ┌────────────────────────────────────────────────────────────────────────────┐ │
  │  │ Tuwunel Matrix (:6167) · Higress AI Gateway (:8080) · MinIO (:9000)      │ │
  │  │ Element Web (:18888) · Manager Agent (OpenClaw)                             │ │
  │  │                        all-in-one 有状态容器                                │ │
  │  └────────────────────────────────────────────────────────────────────────────┘ │
  └──────────────────────────────────────────────────────────────────────────────────┘
          │                                                            │
          │                                                            │ MCP 调用
          │                                                            ▼
  ┌───────────────────────┐                              ┌─────────────────────────────────────────┐
  │honeybadge-graph-worker│                              │  honeybadge-analytics-worker            │
  │      (:8001)          │                              │       (:8001)                           │
  │   独立容器·无状态副本  │                              │    独立容器·无状态副本                    │
  └───────────┬───────────┘                              └─────────────────┬───────────────────────┘
              │                                                              │
              └────────────────────────────┼────────────────────────────────────┐
                                          ▼                                        │
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │                           Higress AI Gateway (:8080)                             │
  │                              MCP 协议路由                                         │
  └────────────────────────────────────────┬───────────────────────────────────────┘
                                           │
                 ┌─────────────────────────┼─────────────────────────┐
                 ▼                         ▼                         ▼
  ┌─────────────────────────┐ ┌─────────────────────────┐ ┌─────────────────────────┐
  │honeybadge-nebula-mcp    │ │honeybadge-audit-mcp    │ │honeybadge-cache-mcp    │
  │      (:8000)            │ │      (:8000)            │ │      (:8000)            │
  │  图谱查询 + L3权限校验   │ │    审计日志读写          │ │    Redis 缓存           │
  │         │                │ │                        │ │                        │
  └─────────┼────────────────┘ └────────────────────────┘ └─────────────────────────┘
            │ 调用权限服务
            ▼
  ┌─────────────────────────┐
  │honeybadge-permissions   │
  │      (:8092)            │
  │  权限策略查询·无状态副本  │
  └─────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │                              第3层：应用服务层                                     │
  │                                                                                  │
  │  ┌─────────────────────────────┐        ┌─────────────────────────────┐         │
  │  │   honeybadge-server (:8090)  │        │  honeybadge-postgres (:5432) │         │
  │  │      审计 REST API           │◄──────│      审计数据库存储            │         │
  │  │   历史会话查询·无状态副本     │  REST │                             │         │
  │  └─────────────────────────────┘        └─────────────────────────────┘         │
  └──────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │                              第4层：基础设施层                                     │
  │                                                                                  │
  │  ┌─────────────────────────────┐  ┌─────────────────────────────┐               │
  │  │       NebulaGraph            │  │     honeybadge-redis (:6379) │               │
  │  │ ┌───────────┐ ┌───────────┐│  │       会话/查询缓存           │               │
  │  │ │nebula-metad│ │nebula-    ││  └─────────────────────────────┘               │
  │  │ │:9559 x1    │ │storaged   ││                                              │
  │  │ ├───────────┤ │:9779 x1   ││                                              │
  │  │ │nebula-    │ └───────────┘│                                              │
  │  │ │graphd     │              │                                              │
  │  │ │:9669 x1   │              │                                              │
  │  │ └───────────┘              │                                              │
  │  └─────────────────────────────┘                                              │
  └──────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │                    可观测性层（--profile observability）                            │
  │                                                                                  │
  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐     │
  │  │  prometheus   │  │   grafana     │  │     loki      │  │ alertmanager  │     │
  │  │   (:9090)     │  │   (:3030)     │  │   (:3100)     │  │   (:9093)     │     │
  │  │   指标采集 ✅  │  │ 可视化看板 ✅ │  │   日志聚合 ✅   │  │   告警路由 ✅  │     │
  │  └───────────────┘  └───────────────┘  └───────────────┘  └───────────────┘     │
  │                    ↑                                                          │
  │                    └── honeybadge-promtail (Docker Socket 日志收集)               │
  └──────────────────────────────────────────────────────────────────────────────────┘
```

**Approach B 的核心设计：**
- 每个用户登录时，`honeybadge-auth` 在 Tuwunel 中创建专属 Matrix 账号 `@hb-{username}`
- 浏览器拿到 `matrix_access_token` 后直接用 matrix-js-sdk 建立连接
- 每个用户与 Manager 的 DM 房间完全独立，符合 HiClaw per-channel-peer 设计
- `honeybadge-server` 仅提供审计 REST API，不再作为 Matrix 代理
- honeybadge-hiclaw-manager 为 **all-in-one 有状态容器**，Worker 为**独立容器**

### 核心技术栈

| 组件 | 选型 | 版本 | 说明 |
|------|------|------|------|
| 图数据库 | NebulaGraph | 3.8 | 分布式，存算分离 |
| Agent 编排 | HiClaw | 1.0.6 | 阿里巴巴开源 |
| Matrix 服务器 | Tuwunel | - | 内嵌于 HiClaw Manager |
| AI 网关 | Higress | - | 内嵌于 HiClaw Manager |
| 前端框架 | Vue 3 | 3.4+ | Composition API + matrix-js-sdk |
| 后端框架 | FastAPI | 0.115+ | async/await |
| 认证服务 | honeybadge-auth | 1.0 | 专属 Matrix 账号 + JWT |
| LLM | MiniMax / GLM | - | OpenAI 兼容接口 |
| 缓存 | Redis | 7+ | 查询缓存 |
| 审计 | PostgreSQL | 16 | 不可篡改审计日志 |

---

## 设计原则

### 1. LLM 仅生成和格式化，不直接回答

```
用户问题 → LLM 生成 Cypher → 执行查询 → 原始结果 → LLM 格式化 → 用户
```

### 2. 权限在 AST 层注入，不使用字符串拼接

```python
# 错误方式（SQL 注入风险）
cypher = f"MATCH (n) WHERE n.org_id = '{user.org_id}'"

# 正确方式（AST 级别注入，由 validate_and_execute MCP 工具处理）
validate_and_execute(ngql=cypher, user_context={"user_id": ..., "roles": [...], "org_id": ...})
```

### 3. 每个查询都有 trace_id

```
trace_id = HB-20260408-001
全链路：question → Cypher → result → summary → audit_log
```

### 4. 每个用户有独立 Matrix 身份

HiClaw 的 per-channel-peer 设计要求每个通信对象有独立的 Matrix DM 房间。使用共享网关账号会导致所有用户的 DM 指向同一个 peer，Manager 只能响应最初建立的那个房间。Approach B 通过为每个用户创建独立的 Matrix 账号彻底解决了这一问题。

### 5. 配置与代码分离

所有配置通过环境变量或 `.env` 文件管理，支持多环境部署。

---

## 开发阶段

### Phase 0 — MVP（已完成）

单节点原型验证：
- Neo4j 单机版
- OpenClaw Agent
- 云端 LLM API

### Phase 1 — 基础设施升级（当前）

**目标**：生产级基础设施切换 + Approach B 直连架构

| 任务 | 状态 | 说明 |
|------|------|------|
| NebulaGraph Schema | ✅ | 27 Tags, 38 Edges |
| HiClaw Manager-Worker | ✅ | Matrix 协议通信 |
| 五层防幻觉框架 | ✅ | L1-L3 已实现 |
| honeybadge-auth 服务 | ✅ | 每用户 Matrix 账号 + JWT |
| matrix-js-sdk 前端 | ✅ | 浏览器直连 Tuwunel |
| MCP 工具服务 | ✅ | nebula/audit/cache MCP |
| 可观测性 | ✅ | Prometheus/Grafana/Loki/Alertmanager 已启用，Grafana 端口已修复 |
| ETL Pipeline | ⏸ | ODS 层定义，Phase 2 完善 |

### Phase 2 — 业务能力扩展（规划中）

- 权限 MCP Server（封装 Java SDK）
- Cypher AST 权限注入
- ERP 数据 T+1 ETL
- Milvus 本体动态检索
- 虚假交易检测图模式

### Phase 3 — 规模与生态（规划中）

- Kafka CDC 实时同步
- 外围系统对接（CRM/WMS/MES）
- 高可用集群部署

---

## 快速开始

### 前置要求

- **Docker** & **Docker Compose** v2.0+
- **Git**

### 1. 克隆项目

```bash
git clone https://github.com/xiaohanarch/HoneyBadge.git
cd HoneyBadge
```

### 2. 配置环境变量

`deploy/docker/.env` 已包含开发默认值，开箱即用。生产环境务必修改：

```bash
# 关键配置（生产环境必须修改）
JWT_SECRET=your-random-64-char-secret
MATRIX_USER_SECRET=your-random-secret-for-matrix-passwords
LLM_API_KEY=your-llm-api-key
```

### 3. 启动所有容器

```bash
# 从项目根目录运行
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env up -d
```

等待约 60 秒，HiClaw Manager 内部启动 Tuwunel + MinIO + Higress。

### 4. 初始化 NebulaGraph Schema（仅第一次）

```bash
bash deploy/docker/init-nebula.sh
```

执行 ADD HOSTS、建 Space、应用 Schema、重建索引，约 30 秒完成。

### 5. 注册 HiClaw Workers（仅第一次）

```bash
bash deploy/hiclaw/init-workers.sh
```

上传 Worker 的 SOUL.md + 技能文件到 MinIO，注册 MCP Server 到 Higress。

### 6. 重启 Workers

```bash
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env \
  restart hiclaw-graph-worker hiclaw-analytics-worker
```

### 7. 验证服务健康

```bash
# 所有关键服务应显示 (healthy)
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env ps

# 审计 API 健康检查
curl http://localhost:8090/api/health

# Auth 服务健康检查
curl http://localhost:8091/health

# Matrix 服务器
curl http://localhost:6167/_matrix/client/versions
```

### 8. 启动可观测性栈（可选）

```bash
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env \
  --profile observability up -d
```

| 服务 | 地址 | 说明 |
|------|------|------|
| Prometheus | http://localhost:9090 | 指标采集与查询 |
| Grafana | http://localhost:3030 | admin/admin123 |
| Loki | http://localhost:3100 | 日志聚合（Promtail 自动采集） |
| Alertmanager | http://localhost:9093 | 告警路由 |

> 所有 honeybadge-* 服务已添加 `com.honeybadge.service` label，Promtail 通过 Docker Socket 自动发现并收集日志。

### 8. 访问服务

| 服务 | 地址 | 凭证 |
|------|------|------|
| **前端（聊天界面）** | http://localhost:3000 | admin/admin123 · analyst/analyst123 · auditor/auditor123 |
| Element Web（Agent 监控） | http://localhost:18888 | 任意 Matrix 用户 |
| MinIO Console | http://localhost:19001 | admin/admin1234 |
| Higress Console | http://localhost:18001 | admin/admin1234 |

### 停止服务

```bash
# 停止，保留数据
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env down

# 停止并清除所有数据（重置后需重新执行步骤 4-7）
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env down -v
```

---

## 项目结构

```
HoneyBadge/
├── src/honeybadge/              # Python 后端源码
│   ├── core/                    # 核心模块
│   │   ├── constants.py
│   │   ├── exceptions.py
│   │   └── trace.py
│   ├── db/                      # 数据库客户端
│   │   ├── nebula.py
│   │   ├── postgres.py
│   │   └── redis.py
│   ├── auth_service/            # Auth 微服务（Approach B）
│   │   ├── main.py              # POST /login → Matrix token + roles JWT
│   │   └── Dockerfile
│   ├── server/                  # 审计 REST API（仅）
│   │   ├── app.py               # FastAPI 应用入口
│   │   ├── auth.py              # 用户表 + JWT 工具
│   │   ├── config.py
│   │   └── health.py
│   └── metrics/
│       └── collectors.py
│
├── hiclaw/workers/              # HiClaw Worker 配置
│   ├── graph-worker/
│   │   └── agent/
│   │       ├── SOUL.md          # 包含 x-hb-auth 提取逻辑
│   │       └── skills/cypher-query/SKILL.md
│   └── analytics-worker/
│       └── agent/
│           ├── SOUL.md
│           └── skills/multi-step-analysis/SKILL.md
│
├── mcp-servers/                 # MCP 工具服务
│   ├── honeybadge-nebula-mcp/   # NebulaGraph 查询工具
│   ├── honeybadge-audit-mcp/    # 审计日志读写工具
│   └── honeybadge-cache-mcp/    # Redis 缓存工具
│
├── frontend/                    # Vue 3 前端
│   └── src/
│       ├── api/
│       │   └── matrix.ts        # matrix-js-sdk 封装
│       ├── composables/
│       │   ├── useAuth.ts       # 登录 → 获取 matrix_access_token
│       │   └── useMatrixChat.ts # Matrix 聊天逻辑（替代 WebSocket）
│       ├── stores/
│       │   └── auth.ts          # 含 matrixToken / rolesJwt 字段
│       └── views/
│           └── ChatView.vue
│
├── deploy/
│   ├── docker/
│   │   ├── docker-compose.yaml  # 完整服务编排
│   │   ├── .env                 # 环境变量（含 MATRIX_USER_SECRET）
│   │   ├── Dockerfile.server    # honeybadge-server 镜像
│   │   ├── init-nebula.sh       # NebulaGraph Schema 初始化
│   │   ├── nebula-schema.ngql   # 27 Tags + 索引
│   │   └── nebula-edges.ngql    # 38 Edges + 索引
│   └── hiclaw/
│       ├── init-workers.sh      # Worker 注册脚本
│       └── mcp-honeybadge-nebula.yaml  # Higress MCP 注册配置
│
├── starter.md                   # 架构设计文档（中文）
├── CLAUDE.md                    # Claude Code 指南
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 配置说明

### 环境变量（`deploy/docker/.env`）

```bash
# ============ LLM ============
LLM_PROVIDER=minimax
LLM_ENDPOINT=https://api.minimax.chat/v1
LLM_API_KEY=your-key
LLM_MODEL=MiniMax-Text-01

# ============ 图数据库 ============
NEBULA_USER=root
NEBULA_PASSWORD=nebula
NEBULA_SPACE=honeybadge

# ============ PostgreSQL ============
PG_USER=honeybadge
PG_PASSWORD=honeybadge123
PG_DB=honeybadge_audit

# ============ Redis ============
REDIS_PASSWORD=redis123

# ============ HiClaw Manager ============
HICLAW_ADMIN_USER=admin
HICLAW_ADMIN_PASSWORD=admin1234       # MinIO 要求 >= 8 字符
HICLAW_REGISTRATION_TOKEN=honeybadge-reg-token

# ============ Auth（重要，生产环境必须修改）============
MATRIX_USER_SECRET=hb-user-secret-dev    # 用于派生用户 Matrix 密码
JWT_SECRET=change-this-to-a-random-64-char-string-in-production
```

### 端口映射

| 端口 | 服务 | 说明 |
|------|------|------|
| 3000 | 前端 | Vue 3 开发服务器 |
| 6167 | Tuwunel Matrix | 浏览器 matrix-js-sdk 直连 |
| 8090 | honeybadge-server | 审计 REST API |
| 8091 | honeybadge-auth | 登录 + Matrix 账号创建 |
| 9669 | NebulaGraph graphd | 图数据库查询端口 |
| 5432 | PostgreSQL | 审计日志 |
| 6379 | Redis | 缓存 |
| 18001 | Higress Console | AI 网关管理 |
| 18080 | Higress Gateway | 对外 AI 网关 |
| 18888 | Element Web | Matrix Agent 监控 |
| 19001 | MinIO Console | Worker 配置管理 |

---

## API 文档

### 登录（`honeybadge-auth`）

```bash
POST http://localhost:8091/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}

# 响应
{
  "matrix_access_token": "eksx9...",          # 供 matrix-js-sdk 使用
  "matrix_homeserver": "http://localhost:6167",
  "matrix_user_id": "@hb-admin:matrix-local.hiclaw.io",
  "roles_jwt": "eyJhbGci...",                 # 权限 JWT，随 Matrix 消息传递
  "user": {
    "username": "admin",
    "roles": ["admin"],
    "org_id": 1
  }
}
```

首次登录会在 Tuwunel 中自动创建 `@hb-admin:matrix-local.hiclaw.io` 账号，之后登录直接获取 token。

### 发起查询（前端通过 matrix-js-sdk）

前端调用 `useMatrixChat` composable，内部通过 matrix-js-sdk 向 `@manager:matrix-local.hiclaw.io` 发送 DM：

```json
{
  "msgtype": "m.text",
  "body": "查询最近10个采购订单",
  "x-honeybadge": {
    "v": "1",
    "contract": "001",
    "trace_id": "HB-20260410-001",
    "payload": { "question": "查询最近10个采购订单" }
  },
  "x-hb-auth": "<roles_jwt>"
}
```

Manager 将消息路由给 graph-worker，graph-worker 解析 `x-hb-auth` 获取用户权限上下文，调用 MCP 工具执行 nGQL 查询，结果通过 Matrix 消息返回。

### 审计 API（`honeybadge-server`）

```bash
# 健康检查
GET http://localhost:8090/api/health

# 响应
{
  "status": "healthy",
  "version": "1.0.0",
  "services": {
    "redis": {"status": "up"},
    "postgres": {"status": "up"},
    "nebula": {"status": "up"}
  }
}
```

---

## 常见问题

### `honeybadge-auth` 启动失败

等待 60 秒让 HiClaw Manager 完全启动，然后：
```bash
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env restart honeybadge-auth
```

### 登录返回 503

Tuwunel 未就绪。检查 Manager 健康状态：
```bash
docker logs honeybadge-hiclaw-manager | tail -20
```

### `matrix_access_token` 缺失

查看 auth 服务日志：
```bash
docker logs honeybadge-auth
```

### NebulaGraph 为空（SHOW TAGS 无结果）

重新运行 Schema 初始化：
```bash
bash deploy/docker/init-nebula.sh
```

如果 storaged 未注册（`SHOW HOSTS` 为空），脚本会自动执行 `ADD HOSTS`。

### Workers 无法连接

MinIO 配置缺失，重新运行 init-workers.sh 然后重启：
```bash
bash deploy/hiclaw/init-workers.sh
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env \
  restart hiclaw-graph-worker hiclaw-analytics-worker
```

### `honeybadge-nebula-mcp` 一直重启

重新构建镜像：
```bash
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env \
  build honeybadge-nebula-mcp && \
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env \
  up -d --force-recreate honeybadge-nebula-mcp
```

---

## 贡献指南

### 开发流程

1. **Fork** 项目仓库
2. **创建分支**：`git checkout -b feature/your-feature`
3. **开发 & 测试**
4. **提交**：`git commit -m 'feat: add your feature'`
5. **推送**：`git push origin feature/your-feature`
6. **创建 Pull Request**

### 代码规范

- Python: 使用 `ruff` 格式化
- 前端: 使用 `eslint` + `prettier`
- 提交信息: 遵循 Conventional Commits

### 分支策略

- `master`: 主分支，稳定版本
- `feature/approach-b-*`: Approach B 架构相关特性
- `feature/*`: 功能分支
- `fix/*`: 修复分支

---

## 联系与支持

- **项目主页**: https://github.com/xiaohanarch/HoneyBadge
- **问题反馈**: https://github.com/xiaohanarch/HoneyBadge/issues
- **PR #7（Approach B 实现）**: https://github.com/xiaohanarch/HoneyBadge/pull/7

### 相关文档

- [架构设计文档](./starter.md) — 详细技术架构说明（含四阶段演进、容量规划）
- [start-all-service 技能](~/.claude/skills/start-all-service/SKILL.md) — 本地部署一站式指南

---

## 许可证

本项目为专有软件，遵循内部许可证。详情请联系项目团队。

---

**Built with ❤️ by the HoneyBadge Team**
