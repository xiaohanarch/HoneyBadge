# Project HoneyBadge

**企业知识图谱智能助手** — 基于 ERP 系统（Oracle EBS / 定制 ERP）构建的自然语言问答系统，支持采购/供应链数据查询、欺诈检测和三单匹配异常检测。

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/xiaohanarch/HoneyBadge)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/)
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
- [测试](#测试)
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
- **NebulaGraph** 分布式图数据库
- 完整 PTP（采购到付款）+ OTC（订单到收款）数据模型
- 34 种标签（Tag）+ 38 种边类型（Edge Type）

### 2. 智能 Agent 编排
- **HiClaw** 阿里巴巴开源的多 Agent 协作框架
- Manager-Worker 架构，任务解耦与弹性伸缩
- Matrix 协议通信，所有交互可审计

### 3. 五层防幻觉框架

| 层级 | 名称 | 功能 |
|------|------|------|
| L1 | 语法校验 | Cypher/nGQL 语法检查，错误拒绝并重试 |
| L2 | Schema 校验 | 验证标签/边类型/属性是否符合图谱定义 |
| L3 | 权限校验 | 注入数据范围过滤（org_id/dept_id） |
| L4 | 结果透传 | LLM 仅格式化输出，不修改数据 |
| L5 | 全链路审计 | PostgreSQL 记录 question → Cypher → result → summary |

### 4. AI 网关
- **Higress** 统一入口（Phase 2 完善 SSO）
- CORS、限流、请求转换
- JWT 认证与用户身份透传

### 5. 可观测性
- **Prometheus** 指标采集
- **Grafana** 可视化看板
- **Loki** 日志聚合
- **Jaeger** 链路追踪

---

## 技术架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户请求流程                                     │
└─────────────────────────────────────────────────────────────────────────────┘

     ┌───────────────┐
     │   前端 Web     │  Vue 3 + TypeScript + WebSocket
     └───────┬───────┘
             │ WebSocket / HTTP
             ↓
     ┌───────────────────┐
     │   Higress 网关     │  SSO/OAuth2 + 限流 + CORS + 请求转换
     └───────┬───────────┘
             │ HTTP/WS
             ↓
     ┌───────────────────┐
     │ HoneyBadge Server │  FastAPI + JWT 认证 + Session 管理
     │   (port 8090)     │  WebSocket 处理器 + Matrix Client
     └───────┬───────────┘
             │ Matrix Protocol (DM)
             ↓
     ┌───────────────────┐
     │  HiClaw Manager   │  Agent 编排 + 任务分发
     │  (Matrix Room)    │  多副本无状态
     └───────┬───────────┘
             │ Matrix Protocol
      ┌──────┼──────┬──────────┐
      ↓      ↓      ↓          ↓
 ┌────────┐┌────────┐┌────────┐┌────────┐
 │ Graph  ││Analytics││  MCP   ││ Nebula │
 │ Worker ││ Worker ││ Worker ││  MCP   │
 └────────┘└────────┘└────────┘└────────┘
     │        │         │         │
     └────────┼─────────┼─────────┘
              ↓         ↓
     ┌─────────────────────────┐
     │     基础设施层           │
     │ NebulaGraph │ Redis │   │
     │ PostgreSQL │ Milvus │   │
     └─────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              基础设施                                        │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
  │ NebulaGraph │  │    Redis    │  │  PostgreSQL │  │   Milvus    │
  │  图数据库    │  │  缓存/会话   │  │   审计日志   │  │  向量检索   │
  │  (9669)    │  │   (6379)    │  │   (5432)    │  │  (19530)   │
  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
```

### 核心技术栈

| 组件 | 选型 | 版本 | 说明 |
|------|------|------|------|
| 图数据库 | NebulaGraph | 3.8+ | 分布式，存算分离 |
| Agent 编排 | HiClaw | 1.0+ | 阿里巴巴开源 |
| AI 网关 | Higress | latest | 基于 Envoy |
| 前端框架 | Vue 3 | 3.4+ | Composition API |
| 后端框架 | FastAPI | 0.115+ | async/await |
| LLM | GLM-4 / Qwen | - | 昇腾 910B 适配 |
| 向量数据库 | Milvus | 2.3+ | 本体检索（Phase 2） |
| 缓存 | Redis | 7+ | Session + 查询缓存 |
| 消息队列 | Kafka | 3.6+ | CDC（Phase 3） |
| 数据质量 | Great Expectations | 0.18+ | ETL 校验 |

---

## 设计原则

### 1. LLM 仅生成和格式化，不直接回答

```
用户问题 → LLM 生成 Cypher → 执行查询 → 原始结果 → LLM 格式化 → 用户
```

LLM 永远不会直接回答数据问题，只负责：
- 生成 Cypher/nGQL 查询
- 将结构化结果格式化为自然语言

### 2. 权限在 AST 层注入，不使用字符串拼接

```python
# 错误方式（SQL 注入风险）
cypher = f"MATCH (n) WHERE n.org_id = '{user.org_id}'"

# 正确方式（AST 级别注入）
validator.inject_permission_filter(ast, user.org_id, user.roles)
```

### 3. 每个查询都有 trace_id

```
trace_id = HB-20260408-001
       = HB-{日期}-{序号}

全链路：question → Cypher → result → summary → audit_log
```

### 4. 事务明细数据必须存在于图谱中

用于欺诈检测的关联分析需要完整的交易链路数据。

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

**目标**：生产级基础设施切换

| 任务 | 状态 | 说明 |
|------|------|------|
| NebulaGraph Schema | ✅ | 34 Tags, 38 Edges |
| HiClaw Manager-Worker | ✅ | Matrix 协议通信 |
| 五层防幻觉框架 | ✅ | L1-L3 已实现 |
| Higress 网关 | ✅ | Docker Compose 集成 |
| Vue 3 前端 | 🔄 | WebSocket 聊天界面 |
| 可观测性 | 🔄 | 配置就绪，收集器开发中 |
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

- **Docker** & **Docker Compose** (v2.0+)
- **Python** 3.10+
- **Node.js** 18+ (前端开发)
- **Git**

### 1. 克隆项目

```bash
git clone https://github.com/xiaohanarch/HoneyBadge.git
cd HoneyBadge
```

### 2. 启动基础设施

```bash
cd deploy/docker

# 启动所有服务（包括 Higress、NebulaGraph、Redis、PostgreSQL、Matrix）
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看特定服务日志
docker-compose logs -f nebula-graphd
```

### 3. 配置环境变量

```bash
cd ../..

# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，配置必要的 API Key
nano .env
```

**关键配置项：**

```bash
# LLM 配置
LLM_ENDPOINT=https://your-llm-api.com/v1
LLM_API_KEY=your-api-key
LLM_MODEL=glm-4-flash

# JWT 密钥（生产环境必须修改）
JWT_SECRET=your-secure-secret-key
```

### 4. 安装后端依赖

```bash
# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -r requirements.txt
```

### 5. 初始化数据库

```bash
# 导入 NebulaGraph Schema
docker exec -it honeybadge-nebula-console \
  nebula-console -addr nebula-graphd -port 9669 -user root -password nebula \
  -e "CREATE SPACE IF NOT EXISTS honeybadge; USE honeybadge; :play nebulaGraph;"
```

### 6. 启动后端服务

```bash
# 开发模式（热重载）
uvicorn honeybadge.server.app:create_app --factory --reload --port 8090

# 或使用脚本
python -m honeybadge
```

### 7. 启动前端（可选）

```bash
cd frontend
npm install
npm run dev
```

### 8. 访问服务

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | http://localhost:5173 | Vue 3 开发服务器 |
| API 健康检查 | http://localhost:8090/api/health | 后端状态 |
| Higress 网关 | http://localhost:80 | 统一入口 |

### 停止服务

```bash
# 停止容器
cd deploy/docker
docker-compose down

# 停止并清除数据（完全重置）
docker-compose down -v
```

---

## 项目结构

```
HoneyBadge/
├── src/honeybadge/              # Python 后端源码
│   ├── core/                    # 核心模块
│   │   ├── constants.py        # 常量定义
│   │   ├── exceptions.py       # 异常类型
│   │   └── trace.py            # trace_id 生成
│   ├── db/                     # 数据库客户端
│   │   ├── nebula.py           # NebulaGraph
│   │   ├── postgres.py         # PostgreSQL
│   │   └── redis.py            # Redis
│   ├── gateway/                # 网关层
│   │   ├── matrix_client.py     # Matrix 客户端
│   │   ├── room_manager.py     # Session-Room 映射
│   │   └── schema_cache.py     # Schema 缓存
│   ├── llm/                    # LLM 适配层
│   │   ├── adapter.py          # OpenAI 兼容接口
│   │   ├── minimax_adapter.py  # 智谱 GLM
│   │   └── claude_adapter.py  # Anthropic Claude
│   ├── protocols/              # 协议定义
│   │   ├── messages.py         # 消息类型定义
│   │   └── validator.py        # L1-L5 校验器
│   ├── server/                 # FastAPI 服务
│   │   ├── app.py              # 应用入口
│   │   ├── auth.py             # JWT 认证
│   │   ├── config.py           # 配置管理
│   │   └── websocket.py        # WebSocket 处理
│   ├── etl/                    # ETL 管道
│   │   ├── quality.py          # 数据质量校验
│   │   └── transform.py        # 数据转换
│   └── metrics/                # 可观测性
│       └── collectors.py       # Prometheus 收集器
│
├── workers/                     # HiClaw Workers
│   ├── graph-worker/           # 图查询 Worker
│   ├── analytics-worker/       # 分析 Worker
│   └── mcp-worker/             # MCP 协议 Worker
│
├── mcp-servers/                # MCP Server 实现
│   ├── honeybadge-nebula-mcp/  # NebulaGraph MCP
│   ├── honeybadge-audit-mcp/   # 审计日志 MCP
│   └── honeybadge-cache-mcp/   # 缓存 MCP
│
├── frontend/                    # Vue 3 前端
│   ├── src/
│   │   ├── views/             # 页面组件
│   │   ├── stores/            # Pinia 状态管理
│   │   ├── composables/       # 组合式函数
│   │   └── api/               # API 客户端
│   └── package.json
│
├── deploy/                      # 部署配置
│   ├── docker/                 # Docker Compose
│   │   ├── docker-compose.yaml
│   │   ├── higress.conf       # Higress 配置
│   │   └── gateway/config/    # 网关路由/CORS/限流
│   ├── hiclaw/                # HiClaw Docker 配置
│   └── nebula/                # NebulaGraph Schema
│
├── tests/                       # 测试套件
│   ├── test_*.py              # 单元测试
│   └── test_integration_*.py  # 集成测试
│
├── docs/                        # 详细文档
│   ├── phase1/                # Phase 1 设计文档
│   │   ├── 00-overview.md     # 总览
│   │   ├── 01-nebula-schema.md
│   │   ├── 02-hiclaw-orchestration.md
│   │   ├── 03-anti-hallucination.md
│   │   ├── 04-llm-adapter.md
│   │   ├── 05-frontend.md
│   │   ├── 06-data-pipeline.md
│   │   ├── 07-gateway.md
│   │   ├── 08-observability.md
│   │   ├── 09-deployment.md
│   │   └── 10-ontology.md
│   └── superpowers/           # AI 辅助规划
│
├── scripts/                     # 工具脚本
│   └── generate_test_data.py  # 测试数据生成
│
├── starter.md                   # 架构文档（中文）
├── CLAUDE.md                    # Claude Code 指南
├── pyproject.toml               # Python 项目配置
├── requirements.txt             # pip 依赖
└── README.md                    # 本文档
```

---

## 配置说明

### 环境变量

完整的环境变量列表：

```bash
# ============ 数据库 ============
NEBULA_HOST=nebula-graphd
NEBULA_PORT=9669
NEBULA_USER=root
NEBULA_PASSWORD=nebula
NEBULA_SPACE=honeybadge

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=redis123

PG_HOST=postgres
PG_PORT=5432
PG_USER=honeybadge
PG_PASSWORD=honeybadge123
PG_DATABASE=honeybadge_audit

# ============ LLM ============
LLM_ENDPOINT=http://host.docker.internal:8000/v1
LLM_API_KEY=
LLM_MODEL=glm-4-flash

# ============ 认证 ============
JWT_SECRET=change-me-in-production

# ============ Matrix ============
MATRIX_HOMESERVER_URL=http://matrix:8008
MATRIX_USER_ID=@honeybadge-gateway:matrix.local
MATRIX_USER_PASSWORD=

# ============ 服务端口 ============
SERVER_PORT=8090
```

### 端口映射

| 端口 | 服务 | 说明 |
|------|------|------|
| 80 | Higress | HTTP 统一入口 |
| 443 | Higress | HTTPS（未来） |
| 8090 | HoneyBadge Server | REST/WebSocket API |
| 9669 | NebulaGraph | 图数据库 |
| 6379 | Redis | 缓存 |
| 5432 | PostgreSQL | 审计日志 |
| 8008 | Matrix | Agent 通信 |
| 19530 | Milvus | 向量检索 |

---

## API 文档

### 认证

```bash
# 登录获取 Token
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}

# 响应
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

### WebSocket 查询

```bash
# 连接 WebSocket
ws://localhost:8090/ws?token={access_token}

# 发送查询消息
{
  "type": "query",
  "question": "查询供应商 V001 的所有订单",
  "trace_id": "HB-20260408-001"
}

# 接收响应（流式）
{
  "type": "progress",
  "phase": "validating",
  "message": "L1 语法校验通过"
}
{
  "type": "result",
  "trace_id": "HB-20260408-001",
  "data": {
    "rows": [...],
    "columns": [...]
  },
  "summary": "查询到 5 条订单记录"
}
```

### 健康检查

```bash
GET /api/health
GET /api/version
```

完整 API 文档：https://honeybadge-api-docs.example.com

---

## 测试

### 运行所有测试

```bash
# 使用 uv
uv run pytest

# 或使用 pip
pytest
```

### 运行特定测试

```bash
# 单元测试
pytest tests/test_validator.py -v

# 集成测试
pytest tests/test_integration_e2e.py -v

# HiClaw 集成测试
pytest tests/test_matrix_hiclaw_integration.py -v
```

### 测试覆盖率

```bash
pytest --cov=src/honeybadge --cov-report=html
# 查看 htmlcov/index.html
```

### Docker 内测试

```bash
# 在容器中运行测试
docker exec -it honeybadge-server pytest
```

---

## 常见问题

### Q: NebulaGraph 连接失败？

```bash
# 检查 NebulaGraph 是否就绪
docker-compose logs nebula-graphd | grep "Storage service is ready"

# 确认端口
docker exec -it honeybadge-nebula-console \
  nebula-console -addr localhost -port 9669 -user root -password nebula
```

### Q: Matrix 无法连接？

```bash
# 检查 Matrix 服务
docker-compose logs matrix-conduit

# 确认 Matrix 服务健康
curl http://localhost:8008/health
```

### Q: LLM API 调用失败？

1. 确认 `LLM_ENDPOINT` 和 `LLM_API_KEY` 配置正确
2. 检查 LLM 服务是否可访问
3. 查看服务日志：`docker-compose logs honeybadge-server`

### Q: WebSocket 连接被拒绝？

1. 确认 Token 未过期
2. 检查 `JWT_SECRET` 配置一致
3. 确认 Higress 端口 80 未被占用

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

```bash
# 格式化代码
uv run ruff format .

# 类型检查
uv run mypy src/
```

### 分支策略

- `master`: 主分支，稳定版本
- `phase1-implementation`: Phase 1 开发分支
- `feature/*`: 功能分支
- `fix/*`: 修复分支

---

## 联系与支持

- **项目主页**: https://github.com/xiaohanarch/HoneyBadge
- **问题反馈**: https://github.com/xiaohanarch/HoneyBadge/issues
- **讨论组**: https://github.com/xiaohanarch/HoneyBadge/discussions

### 相关文档

- [架构设计文档](./starter.md) - 详细技术架构说明
- [Phase 1 设计](./docs/phase1/00-overview.md) - Phase 1 详细设计
- [NebulaGraph Schema](./docs/phase1/01-nebula-schema.md) - 图谱模型定义
- [HiClaw 编排](./docs/phase1/02-hiclaw-orchestration.md) - Agent 编排设计
- [防幻觉框架](./docs/phase1/03-anti-hallucination.md) - 五层校验设计

---

## 许可证

本项目为专有软件，遵循内部许可证。详情请联系项目团队。

---

**Built with ❤️ by the HoneyBadge Team**
