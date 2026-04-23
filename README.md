# Project HoneyBadge

**企业知识图谱智能助手 — 技术架构与实施全书**

基于 ERP 系统（Oracle EBS / 定制 ERP）构建的自然语言问答系统，支持采购/供应链数据查询、欺诈检测和三单匹配异常检测。

> 文档版本：v3.3 · 最后更新：2026-04-23

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/xiaohanarch/HoneyBadge)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](LICENSE)

---

## 目录

- [项目背景与目标](#一项目背景与目标)
- [技术架构演进四阶段](#二技术架构演进四阶段)
- [整体架构全景](#三整体架构全景)
- [核心技术选型与决策](#四核心技术选型与决策)
- [关键功能实现方案](#五关键功能实现方案)
- [数据质量保障体系](#六数据质量保障体系)
- [数据规模与容量规划](#七数据规模与容量规划)
- [实施路线图](#八实施路线图)
- [团队配置](#九团队配置)
- [风险与应对](#十风险与应对)
- [业界实践对比](#十一业界实践对比)
- [Agent 框架架构深度对比](#十二agent-框架架构深度对比)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [API 文档](#api-文档)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)

---

## 一、项目背景与目标

### 1.1 业务场景

- 基于企业 ERP 系统（Oracle EBS / 自研 ERP）构建智能问答与分析助手
- 利用知识图谱技术挖掘业务数据关联价值
- 支持供应链风险预警、销售订单分析、物料需求计划等场景
- **核心价值场景**：虚假交易检测、高风险交易追溯、三单匹配异常发现、断供影响链分析

### 1.2 数据规模

- 百亿级数据记录（采购订单、物料、供应商、客户等）
- 多源异构系统：EBS、WMS、MES、CRM 等
- 多模态数据：结构化表格、文本合同、图纸图片等

### 1.3 业务范围决策

**决策：Phase 1-2 聚焦狭义 ERP 范围，暂不对接外围系统。**

- ERP（特别是 PTP/OTC 流程）已经是一个足够复杂的闭环，涉及 10+ 核心实体
- 先做深做透一个域，比浅做多个域价值大得多
- CRM、WMS、MES 的集成主要是数据打通问题（ID 映射），可以后续按需接入

**Phase 1-2 范围**：
- Procure-to-Pay（PTP）：采购订单 → 收货 → 发票 → 付款
- Order-to-Cash（OTC）：销售订单 → 发货 → 开票 → 收款
- 物料主数据 + 供应商主数据 + 客户主数据 + BOM

**Phase 3 按优先级逐步接入**：CRM 客户行为数据、WMS 仓储明细、MES 生产过程数据

### 1.4 非功能要求

- 并发：百级（Phase 1: 20-50，Phase 2: 50-100，Phase 3: 100+）
- 响应时间：简单查询 < 5 秒，复杂分析 < 30 秒
- 安全合规：集成企业 SSO、细粒度数据权限、全链路审计
- 高可用：99.9% 可用性，故障自动转移
- **零幻觉要求**：财经/采购场景绝不允许查询幻觉，每笔查询必须有迹可循、可追溯，满足审计要求

### 1.5 核心特性

**知识图谱引擎**：
- **NebulaGraph** 分布式图数据库（v3.8），存算分离
- 完整 PTP + OTC 数据模型：34 种标签（Tag）+ 38 种边类型（Edge Type）
- 测试数据集覆盖 57 种实体 + 81 种关系，含 12 种欺诈异常模式

**智能 Agent 编排**：
- **HiClaw** 阿里巴巴开源多 Agent 协作框架（v1.0.9）
- Manager-Worker 架构，任务解耦与弹性伸缩
- Matrix 协议通信，所有交互可审计
- **每个用户独立 Matrix 账号**（`@hb-{用户名}:matrix-local.hiclaw.io`），彻底隔离会话

**五层防幻觉框架**：

| 层级 | 名称 | 功能 |
|------|------|------|
| L1 | 语法校验 | nGQL 语法检查，错误拒绝并重试 |
| L2 | Schema 校验 | 验证标签/边类型/属性是否符合图谱定义 |
| L3 | 权限校验 | 注入数据范围过滤（org_id/dept_id） |
| L4 | 结果透传 | LLM 仅格式化输出，不修改数据 |
| L5 | 全链路审计 | PostgreSQL 记录 question → nGQL → result → summary |

**欺诈检测**（12 种异常模式）：
- PTP 侧 6 种：循环交易、拆单规避审批、停用供应商交易、时间线倒挂、银行账户变更、供应商集中度异常
- OTC 侧 3 种：渠道填塞/虚假发货、提前确认收入、贷方凭证欺诈
- PTP+OTC 跨流程 3 种：对倒交易（Round-Tripping）、采销价格倒挂、先发后收

**可观测性（可选）**：Prometheus + Grafana + Loki + Alertmanager

---

## 二、技术架构演进四阶段

> **决策变更**：原三阶段方案调整为四阶段，将原"阶段二"拆分为 Phase 1（基础设施升级）和 Phase 2（业务能力扩展），降低同时引入太多变量的风险。

### 2.1 Phase 0：MVP 验证（已完成）

**目标**：验证"自然语言 → 知识图谱 → 业务洞察"技术可行性

- 图谱库：单机 Neo4j（社区版）
- Agent 编排：OpenClaw + MCP Neo4j 插件
- LLM：云端 API（通义千问 / GPT-4o mini）
- 本体：手动编写 Markdown 文件，每次查询作为 Prompt 注入 LLM
- 数据量：抽样百万级（约 30 万行），并发 1-5 用户

**成果**：验证了 LLM + Prompt 生成 Cypher 的可行性，在 30 万行数据下查询性能和准确性表现良好。

### 2.2 Phase 1：基础设施升级（当前阶段）

**目标**：搭建生产级基础设施，完成核心技术栈切换 + Approach B 直连架构

| 任务 | 状态 | 说明 |
|------|------|------|
| NebulaGraph Schema | ✅ | 34 Tags, 38 Edges + 测试数据 57 实体类型 |
| HiClaw Manager-Worker | ✅ | Matrix 协议通信，Manager + graph-worker + analytics-worker |
| 五层防幻觉框架 | ✅ | L1-L3 已实现 |
| honeybadge-auth 服务 | ✅ | 每用户 Matrix 账号 + JWT |
| matrix-js-sdk 前端 | ✅ | 浏览器直连 Tuwunel |
| MCP 工具服务 | ✅ | nebula/audit/cache MCP |
| 欺诈检测测试数据 | ✅ | 12 种异常模式（PTP + OTC + 跨流程） |
| 可观测性 | ✅ | Prometheus/Grafana/Loki/Alertmanager |
| ETL Pipeline | ⏸ | ODS 层定义，Phase 2 完善 |

### 2.3 Phase 2：业务能力扩展

**目标**：完成业务层面的核心能力建设，可交付业务部门使用

- 权限 MCP Server 开发（封装现有 Java SDK）
- Cypher 权限注入中间件（AST 级改写）
- ERP 数据 T+1 ETL 管道（SeaTunnel + 质量校验）
- 数据质量三层校验框架
- 本体模块化 + Milvus 动态检索
- 成本控制（配额 + 缓存）
- 高可用部署

### 2.4 Phase 3：全面生产（规划）

- CDC 准实时同步（Debezium + Kafka）
- 多模态数据融合（合同/图纸元数据入图）
- 外围系统 MCP 接入（CRM/WMS 联邦查询）
- 模型降级路由（大小模型分流，成本优化）

---

## 三、整体架构全景

### 3.1 Phase 1 实现架构（Approach B — 当前）

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              HoneyBadge Phase 1 部署架构                             │
│                              （实际运行状态 · 2026-04-16）                          │
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
  │  │   指标采集     │  │  可视化看板    │  │   日志聚合     │  │   告警路由     │     │
  │  └───────────────┘  └───────────────┘  └───────────────┘  └───────────────┘     │
  │                    ↑                                                          │
  │                    └── honeybadge-promtail (Docker Socket 日志收集)               │
  └──────────────────────────────────────────────────────────────────────────────────┘
```

> **架构说明**：
> - 图中所有带 `:xxxx` 端口的组件名称均对应实际运行的 Docker 容器名
> - honeybadge-hiclaw-manager 为 **all-in-one 有状态容器**，内置 Tuwunel/MinIO/Higress/Element Web
> - honeybadge-graph-worker 和 honeybadge-analytics-worker 为**独立容器**，通过 Matrix 协议与 Manager 通信

**Approach B 的核心设计**：
- 每个用户登录时，`honeybadge-auth` 在 Tuwunel 中创建专属 Matrix 账号 `@hb-{username}`
- 浏览器拿到 `matrix_access_token` 后直接用 matrix-js-sdk 建立连接
- 每个用户与 Manager 的 DM 房间完全独立，符合 HiClaw per-channel-peer 设计
- `honeybadge-server` 仅提供审计 REST API，不再作为 Matrix 代理

### 3.2 目标架构（Phase 3+）

```
                        ┌─────────────┐
                        │   前端 Web    │
                        │  (matrix-sdk) │
                        └──────┬───────┘
                               ↓
                        ┌──────────────┐
                        │  Higress 网关  │ ← SSO/OAuth2 认证
                        └──────┬───────┘
                               ↓
                    ┌─────────────────────┐
                    │   HiClaw Manager     │ ← 无状态，多副本
                    │  (Matrix Protocol)   │
                    └──┬──────┬──────┬────┘
                       ↓      ↓      ↓
                   ┌──────┐┌──────┐┌──────┐
                   │Worker││Worker││Worker│  ← 按技能分组
                   │(图谱) ││(分析) ││(MCP) │
                   └──┬───┘└──┬───┘└──┬───┘
                      ↓       ↓       ↓
    ┌─────────────────────────────────────────────┐
    │              共享基础设施层                    │
    │  NebulaGraph │ Redis │ Milvus │ MinIO │ Kafka│
    └─────────────────────────────────────────────┘
    │              联邦查询层（MCP）                 │
    │  Oracle EBS │ 其他数据库 │ 文档存储            │
    └─────────────────────────────────────────────┘
```

### 3.3 核心架构决策摘要

| 决策项 | 决策 | 理由 |
|--------|------|------|
| 阶段划分 | 四阶段（Phase 0/1/2/3） | 原阶段二跨度过大，拆分降低风险 |
| 语义推理 | 继续增强 Prompt 方案，暂不引入 Jena | POC 验证效果良好；Jena 过重 |
| 权限服务 | 复用现有 Java SDK，封装为 MCP Server | 已有成熟权限服务，避免重复建设 |
| 数据范围 | 聚焦狭义 ERP（PTP + OTC + 主数据） | 先做深做透一个域 |
| 数据同步 | Phase 1-2 用 T+1，Phase 3 按需升级 CDC | T+1 匹配 ERP 业务节奏 |
| 前后端通信 | matrix-js-sdk 直连（Approach B） | 解决 per-channel-peer 会话碰撞 |
| 用户 Matrix 身份 | 每用户独立 `@hb-{user}` 账号 | 共享账号导致 Manager 只响应第一个 DM |
| 数据入图策略 | 交易明细必须入图（非联邦查询） | 虚假交易检测依赖明细数据 |

### 3.4 核心技术栈

| 组件 | 选型 | 版本 | 说明 |
|------|------|------|------|
| 图数据库 | NebulaGraph | 3.8 | 分布式，存算分离 |
| Agent 编排 | HiClaw | 1.0.6 | 阿里巴巴开源 |
| Matrix 服务器 | Tuwunel | - | 内嵌于 HiClaw Manager |
| AI 网关 | Higress | - | 内嵌于 HiClaw Manager |
| 前端框架 | Vue 3 | 3.4+ | Composition API + matrix-js-sdk |
| 后端框架 | FastAPI | 0.115+ | async/await |
| 认证服务 | honeybadge-auth | 1.0 | 专属 Matrix 账号 + JWT |
| LLM（开发） | qwen3.5-plus | - | 阿里云百炼 DashScope，OpenAI 兼容接口 |
| LLM（生产目标） | GLM-5 | 744B MoE | 华为昇腾 910B 私有部署 |
| 缓存 | Redis | 7+ | 查询缓存 |
| 审计 | PostgreSQL | 16 | 不可篡改审计日志 |

---

## 四、核心技术选型与决策

### 4.1 Agent 编排层：HiClaw

**项目地址**：https://github.com/alibaba/hiclaw

**选型理由**：
- Manager-Worker 架构实现任务解耦与弹性伸缩
- 内置 AI 网关（Higress）实现凭证零暴露
- 基于 Matrix 协议，所有 Agent 交互可审计
- 原生 MCP Server 集成
- 阿里背书 + Apache 协议 + 活跃维护（v1.0.9）

**架构**：
- **Manager Agent**（基于 OpenClaw）：接收用户任务，创建/调度 Worker，执行心跳检查
- **Worker Agent**：无状态、临时容器，启动时从 MinIO 拉取配置，通过 Matrix Room 与 Manager 通信
- **MCP 集成**：Worker 通过 mcporter CLI 调用 MCP Server 工具

**关键设计：Matrix Room ≠ Worker**

Matrix Room 是极轻量的消息通道，Worker 是重量级计算资源：
```
用户 A ←→ Matrix Room A ←→
用户 B ←→ Matrix Room B ←→  Manager → Worker Pool（3-8个Worker共享服务所有用户）
用户 C ←→ Matrix Room C ←→
```
每个用户有独立的 Room（隔离会话），但共享 Worker Pool（节省资源）。

**per-channel-peer 与 Approach B**：

HiClaw Manager 对每个 Matrix peer 只维护一个活跃 DM 会话。不能用单一共享账号代表所有用户——Approach A 失败的根本原因。Approach B 通过 `honeybadge-auth` 为每个用户创建独立 Matrix 账号解决此问题。

### 4.2 图谱存储：NebulaGraph

**选型理由**：
- 原生分布式，支持千亿节点万亿边
- 存算分离，水平扩展能力强
- 毫秒级多跳查询延迟
- 兼容 openCypher 9
- 被美团、京东、携程等大规模验证

| 维度 | Neo4j | NebulaGraph |
|------|-------|-------------|
| 架构 | 单机/集群（企业版） | 原生分布式 |
| 扩展性 | 受单机限制 | 水平线性扩展 |
| 查询性能 | 百亿级下降 | 保持毫秒级 |
| 开源协议 | GPL（社区版） | Apache 2.0 |

**注意**：openCypher 兼容性不是 100%，从 Neo4j 迁移时需逐条验证。

**实际生产案例性能参考**：

| 案例 | 数据规模 | 查询性能 | 集群配置 |
|------|---------|---------|---------|
| 携程金融 | 百亿级点边 | P95 4ms | 3 台 64 核/320GB/12TB SSD |
| 美团 | 千亿级 | 1 跳 TP99 5ms，2 跳 TP99 20ms | 多集群，在线写入 20 万/s |
| 京东 | 数十亿节点 | 数十万 QPS | 多集群按域分区 |

### 4.3 语义推理层：增强 Prompt 方案

**决策：Phase 1-2 不引入 Jena，继续增强 Prompt 方案。**

- Phase 0 的 POC 使用"本体 Markdown 作为 Prompt"方案效果良好
- 百亿级数据量增长影响的是图谱查询性能（NebulaGraph 解决），而非推理规则数量
- Jena 是重量级语义 Web 框架，引入会增加架构复杂度

**增强方案**：
- 将本体 MD 拆分为模块化片段（按业务域）
- 根据用户问题动态选择相关本体片段注入（RAG 式检索本体）
- 避免一次性注入全部本体导致 token 浪费

**未来引入规则引擎的信号**（Phase 3 评估）：规则 > 50 条、多级 BOM 展开出错、互斥约束校验失败时，优先考虑 Drools。

### 4.4 LLM 模型选型

**开发阶段（当前）**：
- 模型：qwen3.5-plus（通义千问）
- 接入方式：阿里云百炼 DashScope API（OpenAI 兼容接口）
- 端点：`https://coding.dashscope.aliyuncs.com/v1`

**生产目标：GLM-5**：
- 总参数量：744B（MoE 架构）
- 每次推理激活参数：40B
- MoE 专家数：256 个，层数：80 层
- 最大上下文窗口：200K tokens

**昇腾 910B 部署方案**：
- 单卡规格：64GB HBM2e，FP16 算力 ~320 TFLOPS，显存带宽 ~400 GB/s
- 部署方式：W4A8 混合精度量化（Attention/MLP 用 W8A8，MoE 专家用 W4A8）
- 单台 Atlas 800T A3（8 × 昇腾 910B，总显存 512GB）可部署 GLM-5
- W4A8 量化后模型约占 ~400GB 显存，剩余 ~112GB 用于 KV Cache 和推理缓冲
- 推理框架：MindIE / vLLM-Ascend / SGLang

**单台推理服务器吞吐估算**（Atlas 800T A3，8 卡 910B，保守值）：
- 单请求延迟（生成 500 tokens）：~3-5 秒
- 并发吞吐（continuous batching）：~15-25 并发请求
- 总吞吐：~800-1500 tokens/秒

**成本优化：大小模型分流**：
- 简单查询（单实体属性查询）→ GLM-4.7-Flash（30B 参数，3B 活跃）
- 复杂查询（多跳关联、分析）→ GLM-5（744B 参数，40B 活跃）
- 预计 60% 请求可走小模型，推理集群可缩减 30-40%

### 4.5 共享存储与无状态化

HiClaw 要求 Worker 完全无状态——Worker 容器可随时销毁重建而不丢失任何状态。所有持久化数据存放在共享存储层：

| 存储 | 用途 | 技术选型 | 说明 |
|------|------|----------|------|
| Agent 配置 | Worker 的 SOUL.md、SKILL.md、openclaw.json | **MinIO** | S3 兼容；Worker 启动时从 MinIO 拉取配置 |
| 会话状态 | 短期上下文（当前对话） | **Redis Cluster** | |
| 当前对话历史 | Matrix Room 消息记录 | **Tuwunel** | 天然持久化在 Matrix 服务器 |
| 长期记忆 | 向量化历史交互 | **Milvus**（Phase 2） | 按 user_id 做 partition |
| 非结构化文件 | PDF/图片/合同 | **MinIO** | 文件存对象存储，图中只存元数据节点 |
| 图谱数据 | 知识存储 | **NebulaGraph** | |
| 消息队列 | 异步任务 / CDC | **Kafka**（Phase 3） | 为 CDC 准实时同步做准备 |
| 审计日志 | 全链路审计 | **PostgreSQL** | 不可篡改，支持审计追溯 |

#### MinIO 在架构中的角色

MinIO 是 HiClaw Manager 内置的对象存储，在本项目中承担两个职责：

1. **Worker 配置分发**：Worker 的 `openclaw.json`（模型配置）、`SOUL.md`（人格定义）、`SKILL.md`（技能文件）全部存储在 MinIO 的 `hiclaw-storage` 桶中。Worker 容器启动时从 MinIO 拉取配置，因此 Worker 本身不持有任何状态。
2. **非结构化文件存储**：合同 PDF、图纸图片等文件存入 MinIO，图谱中仅存储元数据节点和关联边。

管理入口：http://localhost:19001（admin/admin1234）

#### Tuwunel（Matrix 服务器）在架构中的角色

Tuwunel 是 HiClaw Manager 内置的 Matrix 协议服务器（Conduwuit 的 fork），在本项目中承担三个职责：

1. **Agent 通信总线**：Manager 与 Worker 之间通过 Matrix Room 通信，所有消息天然持久化且可审计
2. **用户会话隔离**：每个用户拥有独立的 Matrix 账号 `@hb-{username}:matrix-local.hiclaw.io`，与 Manager 建立独立 DM 房间，完全隔离
3. **对话历史存储**：当前对话的完整上下文保存在 Matrix Room 历史中，无需额外存储

管理入口：http://localhost:18888（Element Web，任意 Matrix 用户登录）

#### Milvus 在架构中的三个用途（Phase 2 引入）

1. **语义缓存（最重要）**：用户提问向量化 → 搜索相似历史问题 → 命中则直接返回缓存结果，节省 LLM 调用
2. **本体片段检索**：根据用户问题检索最相关的本体片段，只注入相关片段到 Prompt，节省 token 提高精度
3. **用户历史记忆**：每个用户的历史查询向量化存储，新查询时检索相关历史提供上下文连续性

> 注：Phase 1 先用 Redis 做精确缓存（问题 hash → 结果），Phase 2 引入 Milvus 向量语义缓存。

### 4.6 各组件选型评估总表

| 组件 | 选型 | 备选方案 |
|------|------|----------|
| 图谱库 | NebulaGraph | TigerGraph（商业协议） |
| Agent 编排 | HiClaw | LangGraph、Dify |
| AI 网关 | Higress（基于 Envoy） | APISIX + AI 插件 |
| 向量库 | Milvus | Qdrant（更轻量） |
| 消息队列 | Kafka | - |
| 对象存储 | MinIO（S3 兼容） | - |
| 可观测性 | Prometheus + Grafana + Loki | Grafana Tempo 可替代 Jaeger |
| LLM | GLM-5 | 千问系列 |

---

## 五、关键功能实现方案

### 5.1 防幻觉架构（零幻觉要求）

**核心原则：LLM 只负责翻译（生成 nGQL），不负责回答。**

```
❌ 错误模式：用户提问 → LLM 直接回答（会产生幻觉）
✅ 正确模式：用户提问 → LLM 生成 nGQL → 执行查询 → 返回数据库结果
```

**执行流程**：

```python
def handle_query(user_question, user):
    # Step 1: LLM 生成 nGQL（仅翻译，不回答）
    ngql = llm.generate_ngql(
        question=user_question,
        schema=nebula_schema,
        ontology=get_relevant_ontology(user_question),
        instruction="只生成nGQL查询，不要回答问题"
    )
    # Step 2: 三层校验
    validate_syntax(ngql)                        # L1 语法
    validate_schema(ngql, nebula_schema)          # L2 Schema 合规
    ngql = inject_permissions(ngql, user)         # L3 权限
    # Step 3: 执行并记录
    trace_id = generate_trace_id()
    raw_result = nebula.execute(ngql)
    # Step 4: LLM 仅做自然语言包装（禁止修改数值）
    summary = llm.summarize(raw_data=raw_result,
        instruction="用自然语言总结以下查询结果，不要修改任何数值")
    # Step 5: 审计日志
    audit_log.write(trace_id, user, user_question, ngql, raw_result, summary)
    # Step 6: 返回（原始数据 + 摘要，用户可交叉验证）
    return {"summary": summary, "raw_data": raw_result, "ngql": ngql, "trace_id": trace_id}
```

**前端展示**：

```
┌─────────────────────────────────────────┐
│ 查询: 帮我找出疑似虚假交易               │
├─────────────────────────────────────────┤
│ AI 摘要:                                 │
│ 发现3笔疑似异常交易，其中PO-12345的       │
│ 采购金额与发票金额偏差达23%...            │
├─────────────────────────────────────────┤
│ 原始数据:   [展开/收起]                   │
│ ┌─────────┬──────────┬──────────┐       │
│ │ 订单号   │ 采购金额  │ 发票金额  │      │
│ │ PO-12345│ 100,000  │ 123,000  │       │
│ └─────────┴──────────┴──────────┘       │
├─────────────────────────────────────────┤
│ 执行的查询:  [展开/收起]                  │
│ MATCH (po:PurchaseOrder)-[:HAS_INVOICE]  │
│ ->(inv:Invoice) WHERE ...                │
├─────────────────────────────────────────┤
│ 审计ID: TRC-20260403-00147              │
└─────────────────────────────────────────┘
```

### 5.2 用户认证与权限隔离

**认证**：对接企业 SSO（OAuth2/OIDC），Higress 网关统一认证。

**权限服务集成：MCP Server 封装 + Higress 网关双层**

```
用户请求 → Higress 网关（SSO token 验证 + 用户身份提取）
              ↓
         HiClaw Manager
              ↓
         HiClaw Worker (Python) ──MCP──→ 权限 MCP Server (Java)
                                                   │
                                              调用 Java SDK → 权限服务
```

**备选方案**：
- 方案 B：权限服务封装为 REST API（Spring Boot 薄服务），Worker 通过 HTTP 调用
- 方案 C：Higress 网关层统一鉴权，将权限信息注入请求头

**数据权限实现**：
- 行级：在 nGQL 生成层注入过滤条件（如 `WHERE order.org_id IN [user.org_id]`）
- 列级：限制返回属性（如隐藏成本价）
- 方案：采用逻辑隔离（Tag/Property），避免多 Space 管理开销

**安全要求**：
- **绝不使用字符串拼接**注入权限条件（类似 SQL 注入风险）
- 在 nGQL 生成的 Prompt 中告诉 LLM 用户的权限范围，让 LLM 直接生成带过滤条件的 nGQL
- 在 nGQL 执行前增加校验中间件：解析生成的 nGQL AST，确认所有查询都带有权限过滤条件，否则拒绝执行
- 权限服务返回的数据范围可缓存在 Redis 中（TTL 5-15 分钟），避免每次查询都调用权限服务

### 5.3 多用户会话隔离（Approach B）

```
用户 A 登录 → honeybadge-auth:
                ├─ 创建/登录 @hb-admin:matrix-local.hiclaw.io
                └─ 服务端预创建与 @manager 的 DM 房间（Room-A）← 返回 matrix_dm_room_id
      ↓
浏览器用 @hb-admin 的 access_token + Room-A ID 直连 Tuwunel
      ↓
用户 A 直接向 Room-A 发消息（无需客户端发现房间）

用户 B 登录 → honeybadge-auth:
                ├─ 创建/登录 @hb-analyst:matrix-local.hiclaw.io
                └─ 服务端预创建与 @manager 的 DM 房间（Room-B）← 返回 matrix_dm_room_id
      ↓
Room-A 与 Room-B 完全独立，@manager 在登录时已 join 两个房间
```

**Matrix 密码派生**：`HMAC-SHA256(MATRIX_USER_SECRET, username)`

**为何服务端预创建 DM 房间（而非客户端发现）**：

客户端 `findOrCreateManagerDmRoom()` 存在竞态问题：创建新房间后立即发消息，Manager 的 join 是异步的，消息在 Manager 加入前到达导致丢失。更严重的是，每次 E2E 测试或浏览器冷启动时，初始同步超时（5s）导致 `m.direct` 账户数据无法及时读取，每次都误判为"没有已有房间"，反复创建新房间。

服务端预创建的优势：

| 维度 | 客户端发现 | 服务端预创建（当前） |
|------|-----------|-------------------|
| 房间可用性 | 发消息时才确保存在 | 登录完成时就已就绪 |
| Manager join 竞态 | 存在（新房间需等 Manager join）| 不存在（登录时 Manager 已 join）|
| 冷启动可靠性 | 依赖 5s 初始同步超时 | 直接使用 room_id，无需同步 |
| 重复房间风险 | 高（并发 init 导致双重建房）| 低（服务端检查 m.direct 复用）|

`honeybadge-auth` 的 `_provision_dm_room()` 逻辑（幂等）：
1. 查 `m.direct` 账户数据 → 若已有该 Manager 的 DM 房间则直接返回
2. 否则调用 `createRoom(is_direct=True, invite=[@manager])` 创建新房间
3. 写回 `m.direct` 账户数据供下次复用
4. 返回 `room_id` 给前端

**权限上下文传递（x-hb-auth）**：
graph-worker 从 Matrix 消息的 `x-hb-auth` 字段解码出 `{user_id, roles, org_id}`，传入 MCP 工具的 `user_context` 参数实现 L3 权限校验。

### 5.4 数据入图策略

**决策：交易明细数据必须入图**（虚假交易检测等核心场景依赖明细数据）。

| 数据类型 | 策略 | 理由 |
|----------|------|------|
| 核心实体 | 入图 | 供应商、物料、客户等主数据 |
| 交易明细 | 入图 | 采购订单、发票、付款、收货——风控基础 |
| 交易间关系 | 入图 | 三单匹配、审批链、资金流向 |
| 历史流水 | 部分入图 + 冷数据归档 | 近 12-24 月活跃数据入图 |
| 日志/操作记录 | 不入图 | 通过 MCP 按需查询 |
| 外围系统数据 | Phase 3 MCP 查询 | 阶段二不接入 |
| 非结构化数据 | 存 MinIO，元数据入图 | 文件存对象存储，图中只存元数据 |

**虚假交易检测的典型图模式**：

```cypher
-- 示例1：发现循环交易（A采购B，B采购C，C采购A）
MATCH (a:Supplier)-[:SUPPLIES_ITEM]->(:Item)<-[:ORDERS_ITEM]-(po1:PurchaseOrder)-[:PLACED_WITH]->(b:Supplier)
      -[:SUPPLIES_ITEM]->(:Item)<-[:ORDERS_ITEM]-(po2:PurchaseOrder)-[:PLACED_WITH]->(c:Supplier)
      -[:SUPPLIES_ITEM]->(:Item)<-[:ORDERS_ITEM]-(po3:PurchaseOrder)-[:PLACED_WITH]->(a)
RETURN a, b, c, po1, po2, po3

-- 示例2：三单不匹配（采购订单-收货单-发票金额异常）
MATCH (po:PurchaseOrder)-[:HAS_RECEIPT]->(r:Receipt),
      (po)-[:HAS_INVOICE]->(inv:Invoice)
WHERE abs(po.total_amount - inv.total_amount) / po.total_amount > 0.1
   OR abs(r.received_quantity - po.quantity) / po.quantity > 0.05
RETURN po, r, inv

-- 示例3：供应商和客户共享银行账户（对倒交易检测）
MATCH (s:Supplier), (c:Customer)
WHERE s.bank_account = c.bank_account AND s.bank_account IS NOT NULL
RETURN s.supplier_name, c.customer_name, s.bank_account
```

### 5.5 数据联邦查询策略（MCP）

**核心思路**：核心实体 + 交易明细入图，非核心数据通过 MCP 联邦查询。

```
              HiClaw Agent
                   ↓
  ┌──────────────────────────────────┐
  │        MCP Router / Gateway       │
  └──┬──────┬──────┬──────┬─────────┘
     ↓      ↓      ↓      ↓
  NebulaGraph  Oracle EBS  WMS DB  文档存储
  (核心图谱)   (MCP Server)(MCP)   (MCP)
```

NebulaGraph 只存高价值的实体关系网络，其余数据通过 MCP 按需查询，大幅降低数据集成和同步的复杂度。

### 5.6 前后端集成：matrix-js-sdk 直连

```
登录流程：
  浏览器 POST /login → honeybadge-auth
                         ├─ 验证用户名密码
                         ├─ 在 Tuwunel 创建/登录 @hb-{user} 账号
                         ├─ 服务端预创建与 @manager 的 DM 房间（幂等，复用已有房间）
                         └─ 返回 { matrix_access_token, matrix_homeserver,
                                   matrix_dm_room_id, roles_jwt }
                                            ↑
                                   房间 ID 直接返回，前端存入 localStorage

聊天流程：
  浏览器 matrix-js-sdk.createClient(homeserver, access_token)
    ↓
  ensureInitialized()（单例保护，防止并发二次初始化）
    ↓
  client.startClient({ initialSyncLimit: 10 })
    ↓
  dmRoomId = localStorage.matrix_dm_room_id  ← 直接使用，跳过客户端房间发现
    ↓
  sendEvent(roomId, 'm.room.message', { body, x-honeybadge, x-hb-auth })
    ↓
  监听 Room.timeline 事件 → 接收 Manager/Worker 的回复
```

**与 WebSocket 代理方案的对比**：

| 维度 | WebSocket 代理（Approach A，已废弃） | matrix-js-sdk 直连（Approach B，当前） |
|------|---------------------|--------------------------|
| 会话隔离 | 共享 Matrix 账号导致 per-channel-peer 冲突 | 每用户独立 Matrix 身份，彻底隔离 |
| 中间层 | honeybadge-server 代理 Matrix 消息 | 无中间层（浏览器直连 Tuwunel） |
| 流式输出 | WebSocket 推送 | Matrix Room 事件流 |
| 可审计性 | 代理层审计 | Matrix Room 历史天然可审计 |
| 复杂度 | 代理状态管理复杂 | 标准 Matrix SDK，无代理状态 |

**各通道职责**：

```
主通道：matrix-js-sdk（聊天 + Agent 响应流）
  - 用户发送问题 → Matrix DM 消息（x-honeybadge contract: 001）
  - 接收进度推送 → 纯文本 Matrix 事件（流式感知）
  - 接收最终结果 → Matrix 事件（x-honeybadge contract: 002）
  - 接收错误 → Matrix 事件（x-honeybadge contract: 003）

辅助通道：HTTP REST（honeybadge-auth + honeybadge-server）
  - POST /login（honeybadge-auth）：认证 + Matrix 账号创建 + DM 房间预创建
  - GET /api/health（honeybadge-server）：基础设施健康状态
  - GET /api/audit/{trace_id}（honeybadge-server）：审计查询（Phase 2）
  - GET /api/sessions（honeybadge-server）：历史会话列表（Phase 2）
```

**x-honeybadge 消息协议**：

| Contract | 方向 | 说明 |
|----------|------|------|
| 001 | 浏览器 → Manager | 用户查询请求 |
| 002 | graph-worker → 浏览器 | 查询结果（含 trace_id、raw_data） |
| 003 | graph-worker → 浏览器 | 错误响应 |
| 纯文本 | graph-worker → 浏览器 | 中间进度（思考过程、验证状态） |

### 5.7 数据同步与多源异构集成

**同步策略演进**：

```
Phase 1-2: T+1 批量同步
  - 每日凌晨从 ERP 全量/增量抽取
  - 工具：Apache SeaTunnel / DataX 批量导入
  - 简单可靠，运维成本低
  - T+1 完全匹配 ERP 业务节奏（昨天的采购订单今天分析）

Phase 3: 准实时（T+分钟级）
  - 引入 Debezium CDC → Kafka → NebulaGraph Sink
  - 仅对高优先级数据（如采购订单状态变更）做准实时
  - 其余仍保持 T+1

未来: 按业务需求决定是否需要秒级实时
  - 大多数 ERP 分析场景 T+1 已经足够
  - 只有风险预警场景可能需要更实时
```

**多源异构集成工具链**：
- 数据抽取：Apache SeaTunnel / DataX
- 增量同步：Debezium + Kafka（CDC，Phase 3）
- ID 映射：构建统一实体映射表（PostgreSQL）

**图谱构建流程**：
1. 从各系统抽取原始数据到 ODS 层
2. 清洗、归一化、ID 映射
3. 数据质量校验（Great Expectations）
4. 转换为图模型（点/边/属性）
5. 批量导入 NebulaGraph（使用 Exchange 或 Spark-Nebula）

### 5.8 可观测性体系

| 维度 | 工具 | 关键指标 |
|------|------|----------|
| 指标 | Prometheus + Grafana | LLM token 消耗、查询 P99 延迟、错误率、并发数 |
| 日志 | Loki + Grafana | 结构化日志（含 trace_id） |
| 调用链 | Jaeger / OpenTelemetry | 用户 → Manager → Worker → NebulaGraph 完整链路 |
| 告警 | Alertmanager | 错误率 > 5%、Nebula 节点 CPU > 80% |

### 5.9 成本控制与配额管理

**单次请求处理链路及耗时**：
```
用户提问 → HiClaw Manager(~50ms) → LLM 生成 nGQL(~2-5s)
  → nGQL 校验(~50ms) → NebulaGraph 查询(~100-500ms)
  → LLM 生成摘要(~1-3s) → 返回用户

单次请求的 LLM 调用：2 次（生成 nGQL + 生成摘要）
单次请求 token 消耗：输入 ~2000-4000 tokens，输出 ~500-1500 tokens
单次请求端到端耗时：简单查询 ~5s，复杂查询 ~15-30s
```

**成本控制策略**：
- 按用户/部门设置每日/月 token 配额（Redis 计数）
- 查询结果缓存：向量缓存相似问题（Milvus/FAISS）
- 限制 nGQL 遍历深度（≤ 5 跳）和返回行数（≤ 1000）
- 复杂查询转为异步任务，避免阻塞
- **大小模型分流**：简单查询用 GLM-4.7-Flash，复杂查询用 GLM-5，预计 60% 请求可走小模型

### 5.10 高可用与容灾

**部署架构**：
- HiClaw Manager：无状态，至少 2 个 Pod + 负载均衡
- NebulaGraph：3 Meta + 3 Graph + 3-6 Storage（副本数 2），Raft 自动故障转移
- Redis：Cluster 模式（3 主 3 从）
- Kafka：3 Broker 副本
- 备份：NebulaGraph 每周全量 + 每日增量备份到 MinIO
- LLM 推理：多台 Atlas 800T A3 + 负载均衡

---

## 六、数据质量保障体系

### 6.1 第一层：ETL 入图前校验

```
ERP 源数据 → 抽取(SeaTunnel) → ODS 暂存层 → 质量校验 → 图谱
                                       ↓
                                  校验失败 → 隔离区 + 告警
```

| 校验类型 | 规则示例 | 处理方式 |
|----------|---------|----------|
| 空值检查 | PO 编号、供应商 ID、金额不可为空 | 拒绝入图 |
| 类型检查 | 金额必须为正数、日期格式统一 | 自动修正或拒绝 |
| 引用完整性 | PO 关联的供应商必须已存在 | 拒绝，标记"悬挂引用" |
| 唯一性检查 | 同一 PO 编号不可重复 | 去重，保留最新版本 |
| 业务规则 | PO 金额 = SUM(行项目金额) | 标记异常 |
| 时序一致性 | PO 创建日期 ≤ 收货日期 ≤ 发票日期 ≤ 付款日期 | 标记异常 |

**工具：Great Expectations（Python）**

### 6.2 第二层：图谱一致性校验（每日巡检）

入图后定期验证图结构完整性：孤立节点检测、采购订单完整性（PO 必须关联供应商）、三单匹配完整性、环路检测、数据新鲜度。

### 6.3 第三层：数据质量看板

| 指标 | 定义 | 目标 |
|------|------|------|
| 完整率 | 关键字段非空比例 | > 98% |
| 准确率 | 数据值在合理范围内的比例 | > 99% |
| 一致率 | 跨系统数据一致的比例 | > 97% |
| 及时率 | 数据在约定时间内到达 | > 99% |
| 引用完整率 | 关系两端节点都存在的比例 | > 99.5% |

---

## 七、数据规模与容量规划

### 7.1 图数据膨胀评估

```
场景1：简单实体（如供应商主数据）
  1 行记录 → 1 个节点 + N 个属性 → 膨胀比 ~1:1

场景2：关系表（如采购订单）
  1 条 PO → 1 个节点 + 4-6 条边 → 膨胀比 ~1:4-6

场景3：BOM（物料清单）
  N 层嵌套 → 边数指数增长 → 膨胀比 1:10-50
```

百亿级关系型记录 → 约 30-50 亿节点 + 200-500 亿边。

### 7.2 容量规划：1000 人在线 / 100 并发

| 组件 | 配置 | 数量 |
|------|------|------|
| LLM 推理 | Atlas 800T A3（8 × 昇腾 910B） | 8 台 |
| NebulaGraph Meta | 16 核/64GB | 3 台 |
| NebulaGraph Graph | 32 核/128GB | 3 台 |
| NebulaGraph Storage | 64 核/256GB/8TB NVMe | 6 台 |
| HiClaw Manager | 8 核/16GB | 3 Pod |
| HiClaw Worker | 8 核/16GB | 5-8 Pod |
| Redis Cluster | 8 核/64GB | 6 台（3 主 3 从） |
| **合计** | | **约 30-35 台** |

### 7.3 容量规划：500 人在线 / 50 并发

| 组件 | 配置 | 数量 |
|------|------|------|
| LLM 推理 | Atlas 800T A3 | 4 台 |
| NebulaGraph | Meta + Graph + Storage | 9 台 |
| HiClaw + 通用服务 | 混部 | 8-10 台 |
| **合计** | | **约 21-23 台** |

**成本优化**：语义缓存命中率每提升 10%，LLM 服务器需求减少 ~1 台。目标缓存命中率 30-40%。

---

## 八、实施路线图

### 8.1 Phase 1：基础设施升级（20 周）

| 任务 | 周期 | 含学习时间 |
|------|------|-----------|
| 团队技术预研 | 4 周 | 4 周 |
| NebulaGraph 集群 + Schema | 3 周 | 含 1 周摸索 |
| Neo4j → NebulaGraph 迁移 | 3 周 | 含 1 周兼容性踩坑 |
| HiClaw 部署 + 配置 | 3 周 | 含 1.5 周学习 |
| Higress 网关 + SSO 对接 | 4 周 | 含 2 周企业协调 |
| 前端 + 防幻觉 + 可观测性 | 6 周 | |
| 集成测试 + 缓冲 | 5 周 | |

### 8.2 Phase 2：业务能力扩展（20 周）

权限 MCP Server → Cypher 权限注入 → ETL 管道 → 数据质量 → 本体模块化 → 欺诈检测 → 高可用 → 压测调优

### 8.3 Phase 3：全面生产（24 周）

CDC 准实时 → 多模态融合 → 外围系统接入 → 模型降级路由 → 本体演化 → 安全审计

### 8.4 整体时间线

```
Phase 0: MVP 验证                ✅ 已完成
Phase 1: 基础设施升级             20 周（~5 个月）
Phase 2: 业务能力扩展             20 周（~5 个月）
Phase 3: 全面生产                24 周（~6 个月）

总计：~16 个月（Phase 1 开始算起）

关键里程碑：
  M1 (第 4 周)  ：技术预研完成
  M2 (第 12 周) ：NebulaGraph + HiClaw + LLM 端到端跑通
  M3 (第 20 周) ：Phase 1 完成，内部小范围试用
  M4 (第 30 周) ：权限 + ETL 完成，可交付业务部门
  M5 (第 40 周) ：Phase 2 完成，生产级运营
  M6 (第 60 周) ：Phase 3 完成，全面生产
```

---

## 九、团队配置

### 9.1 核心团队（5-6 人）

| 角色 | 人数 | 职责 |
|------|------|------|
| 架构师/Tech Lead | 1 | 全栈架构决策，Schema 设计，HiClaw 编排设计 |
| Python 后端 | 1 | HiClaw Worker、LLM 集成、防幻觉框架、Prompt 工程 |
| Java 后端 | 1 | 权限 MCP Server、ETL 管道、ERP 系统对接 |
| 数据工程师 | 1 | NebulaGraph 运维、ETL、数据质量校验 |
| 前端工程师 | 1 | 聊天界面、数据可视化、Grafana 看板 |
| DevOps/SRE | 1（可半专职） | K8s、昇腾推理集群运维、CI/CD |

### 9.2 AI 辅助提效

**可大量借助 AI 的工作**：nGQL 编写调试、ETL 脚本、数据质量规则、前端 UI、单元测试、文档编写。

**仍需人工主导的工作**：本体建模（深度业务理解）、NebulaGraph 调优（实际压测）、企业 SSO 对接（组织协调）、欺诈检测规则设计（审计专业知识）。

---

## 十、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| NebulaGraph 学习曲线陡峭 | 高 | 中 | 前 4 周专项预研 + 外部顾问 |
| HiClaw 文档不完善 | 中 | 中 | 阿里云社区支持，备选 LangGraph |
| 昇腾 910B 部署踩坑 | 中 | 高 | 专项攻关 + 昇腾社区 |
| openCypher 兼容性问题 | 高 | 中 | 迁移时逐条验证 |
| LLM token 成本超预期 | 高 | 中 | 大小模型分流 + 语义缓存 |
| 数据质量问题 | 高 | 高 | 三层数据质量校验 |
| LLM 幻觉 | 中 | 极高 | 五层防幻觉框架 + 结果直传 |

---

## 十一、业界实践对比

### HoneyBadge 的独特定位

```
                    有 Agent 编排
                         ↑
                         │
        HoneyBadge ●─────┤
        (HiClaw+LLM+     │         SAP Joule ●
         NebulaGraph)     │         (专有封闭)
                         │
     ─────────────────────┼─────────────────────→ 有本体/语义层
                         │
        Neo4j GraphRAG ● │         metaphacts ●
        (通用，无Agent)   │         (RDF/SPARQL)
                         │
          美团/京东 ●─────┤
          (大规模，无LLM)  │         Spice.ai ●
                         │         (联邦数据层)
                         ↓
                    无 Agent 编排
```

**核心差异化**：同时具备大规模图引擎 + 多 Agent 编排 + 本体驱动的 NL 接口 + 零幻觉审计能力。

| 维度 | SAP Joule | Neo4j GraphRAG | 美团 KG | HoneyBadge |
|------|-----------|---------------|--------|------------|
| 图数据库 | HANA Graph（专有） | Neo4j（单机受限） | NebulaGraph | NebulaGraph |
| Agent | 单 Agent（专有） | 无 | 无 | HiClaw 多 Agent |
| 本体 | 封闭，不可扩展 | 通常缺失 | 隐含在 Schema | 开放，ontology-as-prompt |
| NL→查询准确率 | 隐藏 | ~60-80% | - | ~80-90%+（有本体约束） |
| 锁定风险 | 高 | 中 | 低 | 低（全开源栈） |

---

## 十二、Agent 框架架构深度对比

> 本章节对比 HoneyBadge 当前架构与四个主流 Agent 框架（OpenClaw、DeerFlow、HiClaw、HermesClaw）的设计差异，从性能、智能性、开放度、健壮性四个维度进行分析。

### 12.1 架构总览

| 维度 | HoneyBadge（当前） | OpenClaw 原生 | DeerFlow (ByteDance) | HiClaw (Alibaba) | HermesClaw/Hermes Agent |
|------|-------------------|--------------|----------------------|-------------------|------------------------|
| **定位** | 企业知识图谱助手 | 个人 AI 代理框架 | 全栈 SuperAgent 执行引擎 | 多 Agent 协作操作系统 | 自我进化 AI 代理 |
| **架构模式** | Manager-Worker + 5 层反幻觉 | 单 Gateway + Channel-Brain-Body | Lead Agent + SubAgent DAG | Manager-Worker-Matrix Room | Agent-first 学习循环 |
| **编排层** | HiClaw Manager via Matrix | 单进程 Gateway | LangGraph DAG 图调度 | Supervisord 全合一容器 | 同步对话循环 |
| **消息总线** | Matrix (Tuwunel) | 24+ 平台适配器 | HTTP SSE + REST | Matrix (Tuwunel) | 6 平台 + Matrix |
| **LLM 网关** | Higress (Envoy) | 内置 failover 链 | 直连 LLM API | Higress (Envoy) | Provider resolver |
| **执行环境** | MCP Server（无沙箱） | Shell + MCP | Docker/K8s 沙箱 | MCP via mcporter | 47 工具 + 118 技能 |
| **协议** | OpenAI 兼容 | OpenAI 兼容 | OpenAI 兼容 | OpenAI 兼容 | 3 种 API 模式 |
| **许可证** | 专有 | MIT | MIT | Apache 2.0 | MIT |

### 12.2 性能（Performance）

| 指标 | HoneyBadge | OpenClaw | DeerFlow | HiClaw | HermesClaw |
|------|-----------|----------|----------|--------|------------|
| **冷启动** | ~15-20s（Worker 从 MinIO 拉配置） | ~6s (Node.js) | ~3-5s（容器已就绪） | ~15-20s（同 HoneyBadge） | ~2s（本地进程） |
| **内存占用** | ~500MB/Worker + Manager 全合一 | ~394MB | 可配（沙箱 2GB 上限） | ~500MB/Worker | ~300MB |
| **并发模型** | maxConcurrent=8，共享 Worker 池 | 单进程，无水平扩展 | LangGraph DAG 真并行 | 同 HoneyBadge | 并行 subagent |
| **延迟开销** | **高** — User→Matrix→Manager→Worker→MCP→Higress→LLM（6 跳） | **低** — 直连 LLM | **中** — Gateway→LangGraph→沙箱 | **高** — 同 HoneyBadge | **低** — 直连 LLM |
| **扩展性** | K8s 横向扩展 Worker | ❌ 单进程 | K8s Provisioner | Docker socket 管理 Worker | ❌ 单进程 |

**HoneyBadge 性能评价：**
- **劣势**：6 跳链路带来不可避免的延迟；Manager 全合一容器（5+ 服务）资源竞争严重
- **优势**：Worker 无状态可弹性扩缩；K8s 部署已验证（ECS 15 pods running）
- **对比 DeerFlow**：DeerFlow 的 LangGraph DAG 并行调度更高效，但缺少消息持久化

### 12.3 智能性（Intelligence）

| 指标 | HoneyBadge | OpenClaw | DeerFlow | HiClaw | HermesClaw |
|------|-----------|----------|----------|--------|------------|
| **任务路由** | 关键词匹配（Manager SOUL.md） | Binding 优先级路由 | Lead Agent LLM 推理分解 | 同 OpenClaw 机制 | LLM 推理 |
| **上下文管理** | 40K token 裁剪 + ontology 动态注入 | Context Window Guard | 渐进式技能加载 + checkpoint | 同 OpenClaw | 3 层记忆系统 |
| **学习能力** | ❌ 无 | ❌ 无原生学习层 | 持久化 Memory + TIAMAT | ❌ 无 | ✅ 自我生成技能（40% 提速） |
| **反幻觉** | ✅ **5 层验证框架（最强）** | ❌ 无 | ❌ 依赖 LLM 自身 | ❌ 无 | ❌ 依赖 LLM 自身 |
| **领域知识** | ✅ 12 份 ontology 文件 + 关键词路由 | 通用 SOUL.md | 通用技能系统 | 通用 SOUL.md | 118 内置技能 |
| **多轮推理** | 单轮查询为主 | 多轮对话 | 长时任务（分钟→小时） | 多轮对话 | 多轮 + 自省 |

**HoneyBadge 智能性评价：**
- **核心优势**：5 层反幻觉框架是**所有对比方案中唯一的数据准确性保障机制**，对金融/审计场景不可替代
- **劣势**：任务路由基于关键词匹配，不如 DeerFlow/Hermes 的 LLM 推理分解灵活；无学习能力，每次查询都是"从零开始"
- **对比 Hermes**：Hermes 的自学习循环（任务→技能生成→复用）长期效率更高，但缺乏数据验证

### 12.4 开放度（Openness）

| 指标 | HoneyBadge | OpenClaw | DeerFlow | HiClaw | HermesClaw |
|------|-----------|----------|----------|--------|------------|
| **许可证** | 专有项目 | MIT | MIT | Apache 2.0 | MIT |
| **生态** | 自建 MCP Servers | 3,200+ ClawHub 技能 | ByteDance 内部验证 | OpenClaw 生态 | 118 技能 + 插件系统 |
| **LLM 支持** | MiniMax/DashScope | 任意 OpenAI 兼容 | 任意 + 中国模型优先 | 任意 OpenAI 兼容 | 200+ 模型 |
| **平台集成** | Matrix only | 24+ 平台 | Slack/Telegram/飞书/企微 | Matrix only | 6 平台 + Matrix |
| **可扩展性** | MCP Server 标准 | MCP + ClawHub | Markdown 技能 + 中间件 | MCP + ClawHub | 插件 + 自生成技能 |
| **标准协议** | Matrix + S3 + MCP | Matrix + 24 协议 | HTTP REST + SSE | Matrix + S3 + MCP | SQLite + 多协议 |

**HoneyBadge 开放度评价：**
- **劣势**：仅支持 Matrix 一个消息通道；平台集成能力远弱于 OpenClaw（24+）和 DeerFlow（4+ IM）
- **优势**：MCP 标准协议、S3 兼容存储、Matrix 开放协议——不绑定任何厂商私有 SDK
- **对比 OpenClaw**：OpenClaw 生态最丰富，但安全审计发现 20% 的 ClawHub 技能含恶意代码

### 12.5 健壮性（Robustness）

| 指标 | HoneyBadge | OpenClaw | DeerFlow | HiClaw | HermesClaw |
|------|-----------|----------|----------|--------|------------|
| **安全模型** | ✅ Higress 凭证隔离 + AST 级权限注入 | ❌ 9 个 CVE（2026.3），含 CVSS 9.9 | 中间件 Guardrail + Seccomp | ✅ 零信任凭证模型 | ✅ 硬件级沙箱（Landlock + Seccomp） |
| **审计追踪** | ✅ **全链路审计（最强）** — trace_id 从问题到结果 | ❌ JSONL 日志仅存 | ❌ token 统计级 | ✅ Matrix 聊天记录 | ❌ SQLite 会话存储 |
| **容错恢复** | Worker 无状态可重建；result-watcher 备援 | 单进程无 failover | ✅ LangGraph checkpoint 恢复 | Worker 无状态可重建 | SQLite 持久化 |
| **单点故障** | ⚠️ Manager + MinIO 双单点 | ⚠️ 单 Gateway 进程 | ⚠️ LangGraph Server | ⚠️ Manager + MinIO 双单点 | ⚠️ 单进程 |
| **权限控制** | ✅ Cypher AST 级注入（非字符串拼接） | ❌ 无 | ❌ 无 | Consumer token 隔离 | OPA 策略 |
| **数据完整性** | ✅ L4 层：LLM 不可修改原始数据 | ❌ | ❌ | ❌ | ❌ |

**HoneyBadge 健壮性评价：**
- **核心优势**：
  1. **全链路审计**——唯一能证明"每个结果来自数据而非 LLM 编造"的架构
  2. **AST 级权限注入**——防 SQL 注入级别的安全保障
  3. **L4 层原始数据透传**——LLM 输出可交叉验证
- **劣势**：Manager 和 MinIO 的单点故障未解决（Phase 2 HA 计划中）
- **对比 DeerFlow**：DeerFlow 的 checkpoint 恢复优于当前的 result-watcher 备援
- **对比 HermesClaw**：OpenShell 硬件级沙箱（Landlock LSM + Seccomp BPF）安全级别最高，但只针对执行隔离，不涉及数据验证

### 12.6 综合评价

#### 当前架构的核心优势

1. **反幻觉框架无可替代** — 5 层验证是所有方案中唯一针对"LLM 生成错误数据"的系统性解决方案，对财务审计场景是刚性需求
2. **全链路审计能力最强** — question→nGQL→raw result→summary 全程 trace_id 可追溯
3. **零信任凭证模型** — Worker 永远不持有真实 API 密钥（继承自 HiClaw）
4. **领域知识注入成熟** — 12 份 ontology 文件 + 关键词路由，精准控制上下文

#### 当前架构的关键短板

1. **链路延迟高** — 6 跳请求路径，简单查询也要经过完整的 Manager→Worker→MCP 链路
2. **Manager 全合一容器是技术债** — 5+ 服务共用进程空间，调试和独立扩缩困难
3. **任务路由"笨"** — 基于关键词匹配，不如 LLM 推理分解灵活
4. **无学习能力** — 每次查询从零开始，无法积累领域经验
5. **平台集成窄** — 仅 Matrix 一个通道，缺少企业 IM（钉钉/飞书/企微）直接对接
6. **Manager + MinIO 双单点** — 高可用方案未落地

#### 架构选型建议

| 场景 | 最佳方案 | 原因 |
|------|---------|------|
| **企业 ERP 审计（当前场景）** | **HoneyBadge（当前）** | 反幻觉 + 审计追踪不可妥协 |
| 通用个人 AI 助手 | OpenClaw | 24+ 平台、生态最丰富 |
| 长时研究/代码生成 | DeerFlow | Docker 沙箱 + checkpoint 恢复 |
| 多 Agent 团队协作 | HiClaw | Manager-Worker-Matrix 最成熟 |
| 安全敏感 + 自学习 | HermesClaw | 硬件沙箱 + 技能自生成 |

#### 可借鉴的改进方向

1. **从 DeerFlow 借鉴**：LangGraph DAG 并行调度 → 替代当前的串行 Manager→Worker 链路
2. **从 Hermes 借鉴**：持久化记忆 + 技能自生成 → 让系统积累 nGQL 模板经验
3. **从 DeerFlow 借鉴**：Checkpoint 恢复机制 → 替代 result-watcher 轮询备援
4. **从 OpenClaw 借鉴**：Binding-based 路由 → 升级当前的关键词匹配为多维度路由
5. **架构拆分**：将 Manager 全合一容器拆为独立微服务（Tuwunel、Higress、MinIO、Manager Agent 各自独立部署）

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
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env up -d
```

等待约 60 秒，HiClaw Manager 内部启动 Tuwunel + MinIO + Higress。

### 4. 初始化 NebulaGraph Schema（仅第一次）

```bash
bash deploy/docker/init-nebula.sh
```

执行 ADD HOSTS、建 Space、应用 Schema、重建索引，约 30 秒完成。

### 5. HiClaw 自动初始化（无需手动操作）

HiClaw Manager 容器在每次启动时，会通过 `entrypoint-wrapper.sh` → `manager-init-internal.sh` 自动执行完整初始化：

- 上传 Worker SOUL.md + 技能文件到 MinIO
- 注册 Workers（`create-worker.sh`）
- 修正 LLM baseUrl / model / contextPruning 配置
- 创建 Higress LLM 路由（`llm-minimax-route`）
- 注入 Manager 的 SOUL.md、AGENTS.md、HEARTBEAT.md
- **修补 Manager allowFrom 白名单**（`@hb-*` 用户列表）← 每次重启都执行，升级 HiClaw 后无需手动恢复

K8s 部署同理：`hiclaw-init-scripts` ConfigMap 将这两个脚本挂载进 Pod，`command` 覆盖默认入口，Pod 每次重启都自动运行。

`deploy/hiclaw/init-workers.sh`（仓库中保留的外部脚本）现为**可选调试工具**，正常启动无需手动执行。

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

### 9. 访问服务

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
│   ├── core/                    # 核心模块（constants, exceptions, trace）
│   ├── db/                      # 数据库客户端（nebula, postgres, redis）
│   ├── auth_service/            # Auth 微服务（POST /login → Matrix token + JWT）
│   ├── server/                  # 审计 REST API
│   └── metrics/                 # Prometheus 指标采集
│
├── hiclaw/                      # HiClaw Agent 配置
│   ├── manager/agent/
│   │   ├── SOUL.md              # Manager 人格与行为定义
│   │   ├── AGENTS.md            # Worker 注册表
│   │   └── skills/erp-query-dispatch/  # ERP 查询路由技能
│   └── workers/
│       ├── graph-worker/agent/  # 图谱查询 Worker（SOUL.md + cypher-query SKILL）
│       └── analytics-worker/agent/  # 分析 Worker（anomaly-detection + multi-step-analysis）
│
├── mcp-servers/                 # MCP 工具服务
│   ├── honeybadge-nebula-mcp/   # NebulaGraph 查询 + L3 权限校验
│   ├── honeybadge-audit-mcp/    # 审计日志读写
│   └── honeybadge-cache-mcp/    # Redis 缓存
│
├── frontend/                    # Vue 3 前端
│   └── src/
│       ├── api/matrix.ts        # matrix-js-sdk 封装
│       ├── composables/         # useAuth, useMatrixChat
│       ├── stores/auth.ts       # matrixToken / rolesJwt
│       └── views/ChatView.vue
│
├── deploy/
│   ├── docker/
│   │   ├── docker-compose.yaml  # 完整服务编排
│   │   ├── .env                 # 环境变量
│   │   ├── init-nebula.sh       # NebulaGraph Schema 初始化
│   │   ├── nebula-schema.ngql   # 34 Tags + 索引
│   │   └── nebula-edges.ngql    # 38 Edges + 索引
│   ├── hiclaw/
│   │   └── init-workers.sh      # Worker 注册脚本
│   └── test-data/csv/           # 测试数据（~228K 顶点, ~390K 边）
│
├── scripts/
│   └── generate_test_data.py    # 测试数据生成（含 12 种欺诈模式）
│
├── tests/e2e/                   # 端到端测试
├── docs/phase1/                 # Phase 1 文档
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
LLM_PROVIDER=openai-compat
LLM_ENDPOINT=https://coding.dashscope.aliyuncs.com/v1
LLM_API_KEY=your-dashscope-key
LLM_MODEL=qwen3.5-plus

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
HICLAW_AI_GATEWAY_DOMAIN=aigw-local.hiclaw.io

# ============ Auth（生产环境必须修改）============
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
  "matrix_access_token": "eksx9...",
  "matrix_homeserver": "http://localhost:6167",
  "matrix_user_id": "@hb-admin:matrix-local.hiclaw.io",
  "roles_jwt": "eyJhbGci...",
  "user": {
    "username": "admin",
    "roles": ["admin"],
    "org_id": 1
  }
}
```

首次登录会在 Tuwunel 中自动创建 `@hb-admin:matrix-local.hiclaw.io` 账号。

### 发起查询（前端通过 matrix-js-sdk）

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

Manager 路由给 graph-worker → 解析 `x-hb-auth` 权限 → 调用 MCP 执行 nGQL → Matrix 消息返回结果。

### 审计 API（`honeybadge-server`）

```bash
GET http://localhost:8090/api/health
# → {"status": "healthy", "version": "1.0.0", "services": {...}}
```

---

## 常见问题

### `honeybadge-auth` 启动失败

等待 60 秒让 HiClaw Manager 完全启动，然后：
```bash
docker compose -f deploy/docker/docker-compose.yaml --env-file deploy/docker/.env restart honeybadge-auth
```

### 登录返回 503

Tuwunel 未就绪。检查 Manager 日志：
```bash
docker logs honeybadge-hiclaw-manager | tail -20
```

### NebulaGraph 为空（SHOW TAGS 无结果）

重新运行 Schema 初始化：
```bash
bash deploy/docker/init-nebula.sh
```

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
- `feature/*`: 功能分支
- `fix/*`: 修复分支
- `ralph/*`: 开发分支

---

## 附录

### 参考资源

- [HiClaw 文档](https://github.com/alibaba/hiclaw)
- [NebulaGraph 官网](https://nebula-graph.io/)
- [NebulaGraph 资源准备文档](https://docs.nebula-graph.com.cn/3.8.0/4.deployment-and-installation/1.resource-preparations/)
- [美团图数据库平台建设](https://tech.meituan.com/2021/04/01/nebula-graph-practice-in-meituan.html)
- [携程金融 NebulaGraph 实践](https://www.cnblogs.com/nebulagraph/p/16963727.html)
- [Higress MCP Server 托管方案](https://www.alibabacloud.com/blog/higress-open-source-remote-mcp-server-hosting-solution-and-upcoming-mcp-market_602108)
- [LLM + Knowledge Graph 减少幻觉](https://arxiv.org/abs/2504.12422)
- [Great Expectations](https://greatexpectations.io/)

### 术语表

| 术语 | 说明 |
|------|------|
| PTP | Procure-to-Pay，采购到付款 |
| OTC | Order-to-Cash，订单到收款 |
| BOM | Bill of Materials，物料清单 |
| MCP | Model Context Protocol，LLM 与外部工具通信协议 |
| CDC | Change Data Capture，变更数据捕获 |
| nGQL | NebulaGraph Query Language |
| GraphRAG | Graph Retrieval-Augmented Generation |

### 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v1.0 | 2026-04-03 | 初始技术讨论纪要 |
| v2.0 | 2026-04-04 | 整合全部架构讨论：四阶段演进、防幻觉体系、容量规划、团队配置、业界对比 |
| v3.0 | 2026-04-10 | Phase 1 Approach B 实现：per-user Matrix 账号、matrix-js-sdk 直连、honeybadge-auth |
| v3.1 | 2026-04-13 | 实际部署状态说明、容器清单、10 倍流量扩容建议 |
| v3.2 | 2026-04-16 | 合并 starter.md 与 README.md；更新 Schema 计数（34 Tags + 38 Edges）；更新 LLM 配置（qwen3.5-plus via DashScope）；新增 12 种欺诈检测模式说明；更新项目结构 |
| v3.3 | 2026-04-23 | 新增第十二章「Agent 框架架构深度对比」：HoneyBadge vs OpenClaw / DeerFlow / HiClaw / HermesClaw，覆盖性能、智能性、开放度、健壮性四维度分析 |

---

## 联系与支持

- **项目主页**: https://github.com/xiaohanarch/HoneyBadge
- **问题反馈**: https://github.com/xiaohanarch/HoneyBadge/issues

---

## 许可证

本项目为专有软件，遵循内部许可证。详情请联系项目团队。
