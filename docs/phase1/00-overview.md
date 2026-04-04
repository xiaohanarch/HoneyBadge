# Phase 1 总览 — 基础设施升级

> 版本：v1.0
> 创建日期：2026-04-04
> 参考文档：`starter.md` v2.0

---

## 1. Phase 1 目标与范围

### 1.1 目标

搭建生产级基础设施，完成核心技术栈从 Phase 0（Neo4j / OpenClaw / 云端 API）到 Phase 1（NebulaGraph / HiClaw / Higress）的切换。Phase 1 结束时应实现：

- NebulaGraph 集群运行，PTP+OTC 全量 Schema 就绪
- HiClaw Manager-Worker 架构可处理自然语言→Cypher 查询全流程
- Higress 网关统一入口，基础认证可用
- 五层防幻觉框架落地（L3 权限注入为预留框架）
- Vue 3 WebSocket 聊天界面可交互
- 可观测性体系（指标、日志、链路追踪）基本就绪
- Docker Compose 开发环境一键启动

### 1.2 范围内

| 模块 | 说明 |
|------|------|
| NebulaGraph Schema | 完整定义（34 Tag, 38 Edge Type），含权限预留字段 |
| HiClaw 编排 | Manager + 3 类 Worker（graph / analytics / mcp） |
| 防幻觉框架 | L1-L5 五层校验 + 审计日志 |
| LLM 适配层 | 云端 API 优先（通义千问 / GLM API），预留自部署切换 |
| 前端 | Vue 3 + TypeScript 聊天界面 |
| 网关 | Higress 基础认证 + 路由 + SSO 预留 |
| 数据管道 | ODS→质量校验→图模型转换→NebulaGraph 导入 |
| 可观测性 | Prometheus + Grafana + Loki + Jaeger |
| 部署 | Docker Compose 开发环境 |

### 1.3 范围外（明确排除）

| 项目 | 说明 |
|------|------|
| 数据同步工具 | 使用公司现有工具，不纳入设计 |
| SSO 实际对接 | 仅预留 OAuth2/OIDC 接口，等公司文档 |
| 权限实际注入 | L3 层仅建框架，预留 Schema 字段（org_id/dept_id/data_scope），等 SDK |
| Cypher AST 权限改写 | Phase 2 任务 |
| 虚假交易检测 | Phase 2 任务（依赖 ETL 完成 + 审计专家） |
| 本体动态检索（Milvus） | Phase 2 任务，Phase 1 用全量注入 |
| 成本控制/配额 | Phase 2 任务 |
| 高可用/集群部署 | Phase 2 任务，Phase 1 为 Docker Compose 单机 |
| CDC 实时同步 | Phase 3 任务 |
| 外围系统（CRM/WMS/MES）对接 | Phase 3 任务 |

---

## 2. 整体架构图

```
                          ┌──────────────────┐
                          │   Vue 3 前端      │
                          │  (WebSocket+REST) │
                          └────────┬─────────┘
                                   │
                          ┌────────▼─────────┐
                          │  Higress 网关     │  ← 基础 Token 认证
                          │  (路由/限流/CORS) │     预留 SSO/OAuth2
                          └────────┬─────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │      HiClaw Manager          │  ← 无状态, 多副本
                    │    (Matrix Protocol)          │
                    └──┬──────────┬──────────┬─────┘
                       │          │          │
                  ┌────▼───┐ ┌───▼────┐ ┌───▼────┐
                  │ graph  │ │analytic│ │  mcp   │   ← Worker Pool
                  │ worker │ │ worker │ │ worker │      按技能分组
                  └──┬─────┘ └──┬─────┘ └──┬─────┘
                     │          │          │
    ┌────────────────▼──────────▼──────────▼────────────┐
    │               共享基础设施层                         │
    │                                                    │
    │  NebulaGraph    Redis    PostgreSQL    MinIO        │
    │  (metad+graphd  (会话     (审计日志)    (文件/       │
    │   +storaged)    缓存)                  配置)       │
    │                                                    │
    │  Kafka          Prometheus  Grafana    Loki         │
    │  (消息队列)      (指标)      (看板)     (日志)       │
    │                                                    │
    │  Jaeger         Matrix Server (Conduit)             │
    │  (链路追踪)      (Agent 通信)                        │
    └────────────────────────────────────────────────────┘
```

---

## 3. 模块依赖关系

```
                    00-overview
                        │
              ┌─────────┼─────────┐
              ▼                   ▼
      01-nebula-schema      10-ontology
              │                   │
              └─────────┬─────────┘
                        │  (数据模型是其他模块的基础)
           ┌────────────┼────────────┐
           ▼            ▼            ▼
    02-hiclaw    03-anti-halluc.  04-llm-adapter
           │            │            │
           └────────────┼────────────┘
                        │
              ┌─────────┼─────────┐
              ▼                   ▼
        05-frontend         07-gateway
              │                   │
              └─────────┬─────────┘
                        │
                        ▼
               06-data-pipeline
                        │
              ┌─────────┼─────────┐
              ▼                   ▼
      08-observability     09-deployment
```

**建议实施顺序**：

1. **第一批**：`01-nebula-schema` + `10-ontology`（数据模型基础）
2. **第二批**：`02-hiclaw` + `03-anti-hallucination` + `04-llm-adapter`（核心服务层）
3. **第三批**：`05-frontend` + `07-gateway`（接入层）
4. **第四批**：`06-data-pipeline`（数据集成层）
5. **第五批**：`08-observability` + `09-deployment`（基础设施层）

---

## 4. 里程碑定义

对应 `starter.md` 9.1 节。

### M1 — 技术预研完成（第 4 周）

| 验收标准 | 说明 |
|---------|------|
| NebulaGraph 单机部署 | Docker Compose 运行，Studio 可连接 |
| HiClaw Hello World | Manager-Worker 端到端消息传递 |
| LLM API 调通 | 通义千问/GLM API 可调用，Prompt→Cypher 验证 |
| 全链路 Demo | 自然语言→LLM→Cypher→NebulaGraph→结果→LLM→摘要 |

### M2 — 核心链路跑通（第 12 周）

| 验收标准 | 说明 |
|---------|------|
| NebulaGraph Schema 完整 | 34 Tag, 38 Edge Type, 索引就绪 |
| HiClaw Worker 就绪 | graph-worker 完整查询流程 |
| 防幻觉 L1-L2 上线 | Cypher 语法 + Schema 合规校验 |
| 前端原型 | WebSocket 聊天界面可交互 |
| 网关就绪 | Higress 路由 + 基础认证 |

### M3 — Phase 1 完成，内部试用（第 20 周）

| 验收标准 | 说明 |
|---------|------|
| 五层防幻觉框架 | L1-L5 全部就位（L3 为预留框架） |
| 审计日志 | PostgreSQL 完整记录，trace_id 贯穿 |
| 数据管道 | ODS→Graph 导入流程可运行 |
| 可观测性 | Grafana 看板 + Loki 日志 + Jaeger 链路 |
| Docker Compose | 一键启动全部服务 |
| 内部试用 | 5-10 人试用，收集反馈 |

---

## 5. 技术栈选型总表

| 组件 | 选型 | 版本 | 用途 | 备选 |
|------|------|------|------|------|
| 图数据库 | NebulaGraph | 3.8.x | 知识图谱存储 | — |
| Agent 编排 | HiClaw | 1.0.x | Manager-Worker 多 Agent | — |
| AI 网关 | Higress | 2.x | 路由/认证/限流 | — |
| LLM（复杂） | GLM API / 通义千问 API | — | Cypher 生成、结果摘要 | GPT-4o mini |
| LLM（简单） | GLM-4.7-Flash API | — | 简单查询 | — |
| 前端框架 | Vue 3 + TypeScript | 3.5.x | 聊天界面 | — |
| 状态管理 | Pinia | 2.x | 前端状态 | — |
| UI 组件库 | Element Plus | 2.x | UI 组件 | Naive UI |
| 构建工具 | Vite | 6.x | 前端构建 | — |
| 缓存 | Redis | 7.x | 会话状态/临时缓存 | — |
| 审计数据库 | PostgreSQL | 16.x | 审计日志/历史会话 | — |
| 消息队列 | Kafka | 3.x | 异步任务（为 Phase 3 CDC 准备） | — |
| 对象存储 | MinIO | latest | 文件存储/Worker 配置 | — |
| Matrix Server | Conduit | latest | Agent 间通信 | Synapse |
| 指标监控 | Prometheus | 2.x | 指标采集 | — |
| 看板 | Grafana | 11.x | 可视化 | — |
| 日志 | Loki | 3.x | 结构化日志 | — |
| 链路追踪 | Jaeger | 1.x | OpenTelemetry 链路 | — |
| 数据质量 | Great Expectations | 1.x | ETL 校验 | — |
| 容器 | Docker Compose | 2.x | 开发环境编排 | — |

---

## 6. 开发环境要求

### 6.1 最低配置

| 资源 | 最低要求 | 说明 |
|------|---------|------|
| CPU | 8 核 | NebulaGraph + HiClaw + 监控栈 |
| 内存 | 32 GB | NebulaGraph 需要较大内存 |
| 磁盘 | 100 GB SSD | 图数据 + 日志 + Docker 镜像 |
| OS | Linux / macOS / WSL2 | Docker Compose 支持 |
| Docker | 24.x+ | Docker Compose v2 内置 |
| Node.js | 20.x LTS | 前端开发 |
| Python | 3.11+ | HiClaw Worker / ETL 脚本 |
| Java | 17+ | 权限 MCP Server（Phase 2 预留） |

### 6.2 推荐配置

| 资源 | 推荐 |
|------|------|
| CPU | 16 核 |
| 内存 | 64 GB |
| 磁盘 | 256 GB NVMe SSD |

### 6.3 网络要求

- 可访问 LLM 云端 API（通义千问 / 智谱 GLM）
- 可拉取 Docker 镜像（Docker Hub / 阿里云镜像仓库）
- 可访问 npm / PyPI 包仓库

---

## 7. 文档索引

| 文件 | 模块 | 说明 |
|------|------|------|
| `00-overview.md` | 总览 | 本文件 |
| `01-nebula-schema.md` | 数据层 | NebulaGraph Schema 完整定义 + nGQL 脚本 |
| `02-hiclaw-orchestration.md` | 编排层 | HiClaw Manager-Worker 设计 |
| `03-anti-hallucination.md` | 校验层 | 防幻觉五层框架 + 审计日志 |
| `04-llm-adapter.md` | AI 层 | LLM 适配/Prompt 管理/降级 |
| `05-frontend.md` | 前端 | Vue 3 聊天界面设计 |
| `06-data-pipeline.md` | 数据层 | ETL 数据管道 |
| `07-gateway.md` | 接入层 | Higress 网关配置 |
| `08-observability.md` | 运维层 | 可观测性体系 |
| `09-deployment.md` | 运维层 | Docker Compose 开发环境 |
| `10-ontology.md` | 业务层 | 本体模型（PTP+OTC 全流程） |
