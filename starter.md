# 企业级知识图谱智能助手项目 - 技术架构与实施全书

> 项目代号：HoneyBadge
> 文档版本：v3.0
> 最后更新：2026-04-10
> 说明：本文档整合了项目启动以来的所有技术讨论、架构决策、选型评估与实施计划，作为项目执行的唯一权威参考。v3.0 新增 Phase 1 Approach B 架构实现说明：浏览器直连 Matrix 方案，解决 HiClaw per-channel-peer 会话隔离问题。

---

## 一、项目背景与目标

### 1.1 业务场景

- 基于企业ERP系统（Oracle EBS / 自研ERP）构建智能问答与分析助手
- 利用知识图谱技术挖掘业务数据关联价值
- 支持供应链风险预警、销售订单分析、物料需求计划等场景
- **核心价值场景**：虚假交易检测、高风险交易追溯、三单匹配异常发现、断供影响链分析

### 1.2 数据规模

- 百亿级数据记录（采购订单、物料、供应商、客户等）
- 多源异构系统：EBS、WMS、MES、CRM等
- 多模态数据：结构化表格、文本合同、图纸图片等

### 1.3 业务范围决策

**决策：Phase 1-2 聚焦狭义 ERP 范围，暂不对接外围系统。**

理由：
- ERP（特别是 PTP/OTC 流程）已经是一个足够复杂的闭环，涉及 10+ 核心实体
- 先做深做透一个域，比浅做多个域价值大得多
- CRM、WMS、MES 的集成主要是数据打通问题（ID映射），可以后续按需接入
- ERP 内部的主数据通常有统一的编码体系，大幅降低 ID 映射复杂度

**Phase 1-2 范围**：
- Procure-to-Pay（PTP）：采购订单 → 收货 → 发票 → 付款
- Order-to-Cash（OTC）：销售订单 → 发货 → 开票 → 收款
- 物料主数据 + 供应商主数据 + BOM

**Phase 3 按优先级逐步接入**：
- CRM 客户行为数据
- WMS 仓储明细
- MES 生产过程数据

### 1.4 非功能要求

- 并发：百级（Phase 1: 20-50，Phase 2: 50-100，Phase 3: 100+）
- 响应时间：简单查询<5秒，复杂分析<30秒
- 安全合规：集成企业SSO、细粒度数据权限、全链路审计
- 高可用：99.9%可用性，故障自动转移
- **零幻觉要求**：财经/采购场景绝不允许查询幻觉，每笔查询必须有迹可循、可追溯，满足审计要求

---

## 二、技术架构演进四阶段

> **决策变更**：原三阶段方案调整为四阶段，将原"阶段二"拆分为 Phase 1（基础设施升级）和 Phase 2（业务能力扩展），降低同时引入太多变量的风险。

### 2.1 Phase 0：MVP验证（已完成）

**目标**：验证"自然语言→知识图谱→业务洞察"技术可行性
**数据量**：抽样百万级（约30万行）
**并发**：1-5用户
**系统**：1-2个核心系统

**技术栈**：
- 图谱库：单机Neo4j（社区版）
- Agent编排：OpenClaw + MCP Neo4j插件
- LLM：云端API（通义千问/GPT-4o mini）
- 本体定义：手动编写本体 Markdown 文件，包含 PTP 流程中的多个实体定义、实体关联、隐含关系（三单匹配、时序关系如采购数据先于付款数据产生等），每次查询时将本体 MD 文件作为 Prompt 注入 LLM
- 安全：基础只读，固定API Key

**成果**：
- 可回答"单一供应商物料"、"断供影响链"等核心问题
- 验证了LLM+提示词生成Cypher的可行性
- 在30万行数据 + 千问模型下，查询性能和回答的逻辑性、准确性表现良好
- 验证了"本体 Markdown 作为 Prompt"方案的可行性

### 2.2 Phase 1：基础设施升级（当前阶段）

**目标**：搭建生产级基础设施，完成核心技术栈切换
**数据量**：亿级
**并发**：20-50

**核心任务**：
- 编排层：OpenClaw → **HiClaw**（Manager-Worker架构）
- 图谱库：Neo4j → **NebulaGraph**（分布式，存算分离）
- AI网关：部署 **Higress**（内嵌于 HiClaw Manager）
- 可观测性：Prometheus + Grafana + Loki + Jaeger
- 前端：**matrix-js-sdk 直连聊天界面**（Approach B）
- 防幻觉框架：五层 Cypher 校验 + 全链路审计日志
- **Approach B — 每用户独立 Matrix 账号**：解决 HiClaw per-channel-peer 设计下的会话隔离问题（详见 5.3 节）

### 2.3 Phase 2：业务能力扩展

**目标**：完成业务层面的核心能力建设，可交付业务部门使用
**数据量**：十亿级（3-5个系统）
**并发**：50-100

**核心任务**：
- 权限 MCP Server 开发（封装现有 Java SDK）
- Cypher 权限注入中间件（AST 级改写）
- ERP 数据 T+1 ETL 管道（SeaTunnel + 质量校验）
- 数据质量三层校验框架
- 本体模块化 + 动态检索
- 虚假交易检测图模式
- 成本控制（配额 + 缓存）
- 高可用部署

### 2.4 Phase 3：全面生产（规划）

**目标**：支撑百亿级数据、百级并发、全系统集成
**新增能力**：
- CDC 准实时同步（Debezium + Kafka）
- 多模态数据融合（合同/图纸元数据入图）
- 外围系统 MCP 接入（CRM/WMS 联邦查询）
- 模型降级路由（大小模型分流，成本优化）
- 自动化本体演化（本体版本管理）
- 跨数据联邦查询

---

## 三、整体架构全景

### 3.1 架构图

#### Phase 1 实现架构（Approach B — 当前）

```
     ┌───────────────────┐
     │     前端 Web        │  Vue 3 + matrix-js-sdk
     └──┬─────────────┬───┘
        │             │
   POST /login    matrix-js-sdk
        │         (直连 Matrix)
        ↓             ↓
 ┌────────────┐  ┌──────────────────────────────────────────────┐
 │honeybadge  │  │      HiClaw Manager (all-in-one 容器)         │
 │  -auth     │  │                                              │
 │  :8091     │  │  Tuwunel Matrix (:6167) ← 浏览器直连          │
 │            │  │  MinIO (worker 配置)                         │
 │ 认证用户   │  │  Higress AI Gateway (:8080)                   │
 │ 创建 Matrix│  │  Element Web (:18888)                        │
 │ 账号       │  │                                              │
 │ 返回 token │  │  Manager Agent ──→ graph-worker              │
 └────────────┘  │                ──→ analytics-worker          │
                 └──────────────────────────────────────────────┘
                                       ↓ MCP
                 ┌──────────────────────────────────────────────┐
                 │  MCP Servers (nebula-mcp / audit-mcp / ...)  │
                 └──────────────────────────────────────────────┘
                                       ↓
     ┌──────────────────────────────────────────────────────────┐
     │                   基础设施层                              │
     │  NebulaGraph │ PostgreSQL │ Redis │ (Milvus — Phase 2)   │
     └──────────────────────────────────────────────────────────┘

     honeybadge-server (:8090) — 审计 REST API（不再处理聊天）
```

#### 目标架构（Phase 3+）

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

### 3.2 核心架构决策摘要

| 决策项 | 决策 | 理由 |
|--------|------|------|
| 阶段划分 | 四阶段（Phase 0/1/2/3） | 原阶段二跨度过大，拆分降低风险 |
| 语义推理 | Phase 1-2 不引入 Jena，继续增强 Prompt 方案 | POC 验证效果良好；数据量增长不等于规则增长；Jena 过重 |
| 权限服务 | 复用现有 Java SDK，封装为 MCP Server | 已有成熟权限服务，避免重复建设 |
| 消息队列 | 从一开始就使用 Kafka | 避免后期 CDC 场景迁移 |
| 数据范围 | 聚焦狭义 ERP（PTP + OTC + 主数据） | 先做深做透一个域 |
| 数据同步 | Phase 1-2 用 T+1，Phase 3 按需升级 CDC | T+1 匹配 ERP 业务节奏 |
| 前后端通信 | matrix-js-sdk 直连（Approach B） | 解决 HiClaw per-channel-peer 会话碰撞；浏览器直连 Tuwunel，无需代理层 |
| 用户 Matrix 身份 | 每用户独立 `@hb-{user}` 账号 | 共享网关账号导致 Manager 只响应第一个 DM 房间；per-user 账号彻底隔离 |
| 数据入图策略 | 交易明细必须入图（非联邦查询） | 虚假交易检测等核心场景依赖明细数据 |

---

## 四、核心技术选型与决策

### 4.1 Agent编排层：HiClaw

**项目地址**：https://github.com/alibaba/hiclaw
**定位**：阿里巴巴开源的协作式多Agent OS，基于Matrix协议通信

**选型理由**：
- Manager-Worker架构实现任务解耦与弹性伸缩
- 内置AI网关（Higress）实现凭证零暴露
- 支持OpenClaw Skills无缝迁移
- 基于 Matrix 协议，所有 Agent 交互可审计
- 原生 MCP Server 集成
- 支持多种 Worker 运行时（OpenClaw、CoPaw、NanoClaw、ZeroClaw）
- 阿里背书 + Apache 协议 + 活跃维护（v1.0.6，2026年3月更新）

**架构详细说明**：
```
用户 → 负载均衡 → HiClaw Manager（无状态）→ 消息队列 → Worker Pool（按技能分组）
                                                            ↓
                                                    NebulaGraph / Redis / MCP Servers
```

- **Manager Agent**（基于 OpenClaw）：接收用户任务，创建/调度 Worker，执行心跳检查，自动停止闲置 Worker 容器
- **Worker Agent**：无状态、临时容器，启动时从 MinIO 拉取配置，通过 Matrix Room 与 Manager 和用户通信，可销毁重建不丢状态
- **MCP 集成**：Worker 通过 mcporter CLI 调用 MCP Server 工具，每个 Worker 可配置独立的 MCP 访问权限

**关键澄清：Matrix Room ≠ Worker**

Matrix Room 是极轻量的消息通道（创建成本几乎为零），Worker 是重量级计算资源：
```
用户 A ←→ Matrix Room A ←→
用户 B ←→ Matrix Room B ←→  Manager → Worker Pool（3-8个Worker共享服务所有用户）
用户 C ←→ Matrix Room C ←→
```
每个用户有独立的 Room（隔离会话），但共享 Worker Pool（节省资源）。

**Phase 1 关键实现细节：per-channel-peer 与用户身份**

HiClaw Manager 的 `per-channel-peer` 设计：每个通信 peer（Matrix 用户 ID）只维护一个活跃的 DM 会话。

这意味着：**不能用单一共享 Matrix 账号（如 `@honeybadge-gateway`）代表所有用户**。若这样做，所有用户的消息来源都是同一个 peer，Manager 只会响应第一个建立的 DM 房间，后续用户发起的新 DM 房间将永远超时等待响应——这正是 Phase 0 遗留架构的根本性 bug（Approach A 的失败原因）。

**Approach B 解决方案**：
- 登录时由 `honeybadge-auth` 服务在 Tuwunel 中创建用户专属账号 `@hb-{username}:matrix-local.hiclaw.io`
- 每个用户用自己的 Matrix 身份与 Manager 建立 DM，Manager 为每个不同的 peer 独立维护会话
- 浏览器通过 `matrix-js-sdk` 直接连接 Tuwunel（:6167），无需 honeybadge-server 代理
- 权限信息通过消息中的 `x-hb-auth` 字段（roles JWT）传递给 graph-worker

### 4.2 图谱存储：NebulaGraph

**选型理由**：
- 原生分布式，支持千亿节点万亿边
- 存算分离，水平扩展能力强
- 毫秒级多跳查询延迟
- 兼容Cypher（openCypher 9）
- 被美团、京东、携程等大规模验证

**与Neo4j对比**：

| 维度 | Neo4j | NebulaGraph |
|------|-------|-------------|
| 架构 | 单机/集群（企业版） | 原生分布式 |
| 扩展性 | 受单机限制 | 水平线性扩展 |
| 查询性能 | 百亿级下降 | 保持毫秒级 |
| 开源协议 | GPL（社区版） | Apache 2.0 |

**注意事项**：openCypher 兼容性不是 100%，从 Neo4j 迁移时需逐条验证 Cypher 语句。

**实际生产案例性能参考**：

| 案例 | 数据规模 | 查询性能 | 集群配置 |
|------|---------|---------|---------|
| 携程金融 | 百亿级点边 | P95 4ms（优化后） | 3台 64核/320GB/12TB SSD |
| 美团 | 千亿级（全部KG） | 1跳 TP99 5ms，2跳 TP99 20ms | 多集群，在线写入 20万/s |
| 京东 | 数十亿节点，数百亿边 | 数十万 QPS | 多集群按域分区 |

### 4.3 语义推理层决策：暂不引入 Jena，增强 Prompt 方案

**决策背景**：
- Phase 0 的 POC 中使用"本体 Markdown 作为 Prompt"方案（包含 PTP 流程实体定义、关联、隐含关系如三单匹配和时序关系），在 30 万行数据 + 千问模型下效果良好
- 百亿级数据量增长主要影响图谱查询性能（NebulaGraph 解决），而非推理规则数量
- 真正影响 Prompt 方案的瓶颈是规则数量和复杂度，而不是数据量
- Jena 是重量级语义 Web 框架，引入会增加架构复杂度和运维成本

**增强版 Prompt 方案（Phase 1-2）**：
- 将本体 MD 拆分为模块化片段（按业务域：采购、付款、库存...）
- 根据用户问题动态选择相关本体片段注入（RAG 式检索本体）
- 避免一次性注入全部本体导致 token 浪费和上下文污染

**未来引入规则引擎的信号**（Phase 3 评估）：
- 当规则 > 50 条
- LLM 在以下场景频繁出错时：
  - 多级 BOM 展开（5 层以上传递关系）
  - 互斥约束校验（供应商黑名单 × 物料认证状态）
  - 需要 100% 确定性结果且不容许 LLM 概率性"幻觉"
- 届时优先考虑 **Drools**（轻量、Java 生态友好）而非 Jena
- Jena 仅在需要 OWL 标准语义推理时才值得引入

### 4.4 LLM 模型选型：GLM-5

**GLM-5 技术参数**：
- 总参数量：744B（MoE 架构）
- 每次推理激活参数：40B
- MoE 专家数：256 个
- 层数：80 层
- 最大上下文窗口：200K tokens

**昇腾 910B 部署方案**：
- 单卡规格：64GB HBM2e，FP16 算力 ~320 TFLOPS，显存带宽 ~400 GB/s
- 部署方式：W4A8 混合精度量化（Attention/MLP 用 W8A8，MoE 专家用 W4A8）
- 单台 Atlas 800T A3（8 × 昇腾 910B，总显存 512GB）可部署 GLM-5
- W4A8 量化后模型约占 ~400GB 显存，剩余 ~112GB 用于 KV Cache 和推理缓冲
- 推理框架：MindIE / vLLM-Ascend / SGLang

**单台推理服务器吞吐估算**（保守值，Atlas 800T A3，8卡 910B）：
- 单请求延迟（生成 500 tokens）：~3-5 秒
- 并发吞吐（continuous batching）：~15-25 并发请求
- 总吞吐：~800-1500 tokens/秒

**成本优化：大小模型分流**：
- 简单查询（单实体属性查询）→ GLM-4.7-Flash（30B 参数，3B 活跃）
- 复杂查询（多跳关联、分析）→ GLM-5（744B 参数，40B 活跃）
- 预计 60% 请求可走小模型，推理集群可缩减 30-40%

### 4.5 共享存储与无状态化

| 存储 | 用途 | 技术选型 | 说明 |
|------|------|----------|------|
| 会话状态 | 短期上下文 | Redis Cluster | |
| 长期记忆 | 向量化历史交互 | Milvus | Qdrant 也可选；规模不大时可后置引入 |
| 非结构化文件 | PDF/图片 | MinIO | S3 兼容，自托管 |
| 图谱数据 | 知识存储 | NebulaGraph | |
| 消息队列 | 异步任务/CDC | Kafka | 从一开始就使用，为 Phase 3 CDC 做准备 |
| 审计日志 | 全链路审计 | PostgreSQL | 不可篡改，支持审计追溯 |

**Milvus 在架构中的三个用途**：

1. **语义缓存（最重要）**：用户提问向量化 → 搜索相似历史问题 → 命中则直接返回缓存结果，节省 LLM 调用
2. **本体片段检索**：根据用户问题检索最相关的本体片段，只注入相关片段到 Prompt，节省 token 提高精度
3. **用户历史记忆**：每个用户的历史查询向量化存储，新查询时检索相关历史提供上下文连续性

> 注：如果前期规模不大，可先用 Redis 做精确缓存（问题 hash → 结果），等数据量和用户量上来再引入 Milvus 向量语义缓存。

### 4.6 各组件选型评估总表

| 组件 | 选型 | 评估 | 备选方案 |
|------|------|------|----------|
| 图谱库 | NebulaGraph | 合理 — 国内大规模验证多，Apache 2.0 | TigerGraph（性能更强但商业协议） |
| Agent 编排 | HiClaw | 合理 — 阿里开源，活跃维护 | LangGraph（LangChain 官方）、Dify（国内生态好） |
| AI 网关 | Higress | 合理 — 阿里开源，基于 Envoy | APISIX + AI 插件 |
| 向量库 | Milvus | 合理 — 生态大但运维重 | Qdrant（更轻量，规模<1亿向量时推荐） |
| 消息队列 | Kafka | 合理 — 为 CDC 做准备 | - |
| 对象存储 | MinIO | 合理 — S3 兼容 | - |
| 可观测性 | Prometheus+Grafana+Loki+Jaeger | 成熟 | Grafana Tempo 可替代 Jaeger，统一 Grafana 生态 |
| LLM | GLM-5 | 合理 — 开源旗舰，昇腾适配好 | 千问系列作为备选 |

---

## 五、关键功能实现方案

### 5.1 防幻觉架构（零幻觉要求）

**核心原则：LLM 只负责翻译（生成 Cypher），不负责回答。**

```
❌ 错误模式：用户提问 → LLM 直接回答（会产生幻觉）
✅ 正确模式：用户提问 → LLM 生成 Cypher → 执行 Cypher → 返回数据库结果
```

**五层防幻觉防线**：

| 层级 | 名称 | 说明 |
|------|------|------|
| L1 | Cypher 语法校验 | LLM 生成的 Cypher 经过语法解析器校验，不合法直接拒绝要求重新生成 |
| L2 | Schema 合规校验 | 校验 Cypher 中引用的节点类型、边类型、属性名是否存在于 NebulaGraph Schema 中，防止 LLM 编造不存在的字段 |
| L3 | 权限注入校验 | 确认生成的 Cypher 包含权限过滤条件，没有权限条件的查询一律拒绝执行 |
| L4 | 结果直传，禁止 LLM 篡改 | NebulaGraph 返回的原始数据直接展示给用户，LLM 只负责格式化/自然语言包装，不允许修改数值；前端同时展示原始数据表格 + LLM 摘要 |
| L5 | 全链路审计日志 | 记录：用户问题 → 生成的 Cypher → 执行结果 → LLM 摘要，每条记录有唯一 trace_id，存储到不可篡改的审计日志（PostgreSQL） |

**执行流程伪代码**：

```python
def handle_query(user_question, user):
    # Step 1: LLM 生成 Cypher（仅翻译，不回答）
    cypher = llm.generate_cypher(
        question=user_question,
        schema=nebula_schema,                      # 传入图 Schema
        ontology=get_relevant_ontology(user_question),  # 动态选择本体片段
        instruction="只生成Cypher查询，不要回答问题"
    )

    # Step 2: 三层校验
    validate_syntax(cypher)                        # L1 语法
    validate_schema(cypher, nebula_schema)          # L2 Schema 合规
    cypher = inject_permissions(cypher, user)       # L3 权限

    # Step 3: 执行并记录
    trace_id = generate_trace_id()
    raw_result = nebula.execute(cypher)

    # Step 4: LLM 仅做自然语言包装（明确禁止修改数值）
    summary = llm.summarize(
        raw_data=raw_result,
        instruction="用自然语言总结以下查询结果，不要修改任何数值，不要补充数据库中没有的信息"
    )

    # Step 5: 审计日志
    audit_log.write(trace_id, user, user_question, cypher, raw_result, summary)

    # Step 6: 返回给用户（原始数据 + 摘要，用户可交叉验证）
    return {
        "summary": summary,
        "raw_data": raw_result,    # 同时展示原始数据
        "cypher": cypher,           # 展示执行的查询（透明）
        "trace_id": trace_id        # 审计追溯ID
    }
```

**前端展示方案**：

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
│ │ ...     │ ...      │ ...      │       │
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

#### 5.2.1 认证方案
- 对接企业SSO（OAuth2/OIDC），Higress 网关统一认证
- 用户身份透传到 Worker 层

#### 5.2.2 权限服务集成

**决策：复用现有权限服务 Java SDK，支持 RBAC、ABAC、数据范围和操作权限查询。**

权限服务虽然主要面向关系型数据库（如 GaussDB），但 RBAC/ABAC + 数据范围查询的策略层是通用的，只需在"策略→执行"层做适配（从 SQL WHERE 适配到 Cypher WHERE）。

**集成方案：MCP Server 封装 + Higress 网关双层**

```
方案架构（推荐）：

用户请求 → Higress 网关（基础认证：SSO token 验证 + 用户身份提取）
              ↓
         HiClaw Manager
              ↓
         HiClaw Worker (Python) ──MCP协议──→ 权限 MCP Server (Java 微服务)
                                                   │
                                              调用 Java SDK
                                                   │
                                              权限服务
```

- **Higress 网关**：做基础认证（SSO token 验证 + 用户身份提取）
- **权限 MCP Server**（Java 微服务）：封装现有权限 Java SDK，通过 MCP 协议供 HiClaw Worker 调用
- 可参考阿里 Spring AI Alibaba MCP 集成方案

HiClaw 基于 Python（OpenClaw 生态），而权限服务是 Java SDK，通过 MCP Server 封装实现语言无关的集成。

**备选方案**：
- 方案 B：权限服务封装为 REST API（Spring Boot 薄服务），Worker 通过 HTTP 调用
- 方案 C：Higress 网关层统一鉴权，将权限信息注入请求头

#### 5.2.3 数据权限实现

- 行级：在 Cypher 生成层注入过滤条件（如 `WHERE order.region = user.region`）
- 列级：限制返回属性（如隐藏成本价）
- 方案：采用逻辑隔离（Tag/Property），避免多 Space 管理开销

**安全要求**：
- **绝不能使用字符串拼接**方式注入权限条件（类似 SQL 注入风险）
- 应在 Cypher 生成的 Prompt 中告诉 LLM 用户的权限范围，让 LLM 直接生成带过滤条件的 Cypher
- 在 Cypher 执行前增加校验中间件：解析生成的 Cypher AST，确认所有查询都带有权限过滤条件，否则拒绝执行
- 权限服务返回的数据范围可缓存在 Redis 中（TTL 5-15 分钟），避免每次查询都调用权限服务

### 5.3 多用户会话隔离

**需求**：不同用户登录后保有自己的历史查询结果，各用户会话完全独立。

#### 5.3.1 根本性挑战：HiClaw per-channel-peer 设计

HiClaw Manager 对每个 Matrix peer（用户 ID）只维护一个活跃的 DM 房间。如果多个用户共用同一 Matrix 账号，它们的消息来源对 Manager 来说是同一个 peer，Manager 只会响应最初的那个 DM 房间，新用户建立的 DM 永远等不到响应。

这一问题在 Phase 1 实现中被彻底解决（**Approach B**）。

#### 5.3.2 Approach B：每用户独立 Matrix 身份

```
用户 A 登录 → honeybadge-auth 创建 @hb-admin:matrix-local.hiclaw.io
      ↓
浏览器用 @hb-admin 的 access_token 连接 Tuwunel
      ↓
用户 A 与 Manager 建立独立 DM 房间（Room-A）
Manager 将 Room-A 与 @hb-admin peer 绑定

用户 B 登录 → honeybadge-auth 创建 @hb-analyst:matrix-local.hiclaw.io
      ↓
浏览器用 @hb-analyst 的 access_token 连接 Tuwunel
      ↓
用户 B 与 Manager 建立独立 DM 房间（Room-B）
Manager 将 Room-B 与 @hb-analyst peer 绑定（与 Room-A 完全独立）
```

**Matrix 密码派生**：`HMAC-SHA256(MATRIX_USER_SECRET, username)`，由 honeybadge-auth 在服务端派生，不存储在数据库中。

**会话上下文存储**（Phase 1 已实现基础，Phase 2 完善）：
- 当前对话：Matrix Room 历史（天然持久化在 Tuwunel）
- 长期历史：PostgreSQL，按 user_id 分区
- 向量记忆（Phase 2）：Milvus，按 user_id 做 partition

#### 5.3.3 x-hb-auth：权限上下文传递

用户的角色和组织权限通过 Matrix 消息中的 `x-hb-auth` 字段传递给 graph-worker：

```json
{
  "msgtype": "m.text",
  "body": "查询采购订单",
  "x-hb-auth": "<roles_jwt>",
  "x-honeybadge": { "contract": "001", "trace_id": "..." }
}
```

graph-worker 从 `x-hb-auth` 中解码出 `{user_id, roles, org_id}`，传入 `validate_and_execute` MCP 工具作为 `user_context`，实现 L3 权限校验。

### 5.4 数据入图策略

**决策变更**：交易明细数据必须入图。

原方案建议明细/流水数据不入图通过 MCP 联邦查询，但经评估，虚假交易检测、高风险交易追溯等核心价值场景必须有明细数据在图中才能执行。

**修正后的数据入图策略**：

| 数据类型 | 策略 | 理由 |
|----------|------|------|
| 核心实体 | 入图 | 供应商、物料、客户等主数据 |
| 交易明细（关键） | 入图 | 采购订单、发票、付款、收货——风控分析的基础 |
| 交易间关系 | 入图 | 三单匹配、审批链、资金流向 |
| 历史流水（海量） | 部分入图 + 冷数据归档 | 近 12-24 月活跃数据入图，超期归档到关系库/HDFS |
| 日志/操作记录 | 不入图 | 通过 MCP 按需查询 |
| 外围系统数据（CRM/MES） | Phase 3 按需 MCP 查询 | 阶段二不接入 |
| 非结构化数据（合同/图纸） | 存 MinIO，元数据入图 | 文件存对象存储，图中只存元数据节点和关联边 |

**虚假交易检测的典型图模式**：

```cypher
-- 示例1：发现循环交易（A采购B，B采购C，C采购A）
MATCH (a:Supplier)-[:SELLS_TO]->(po1:PurchaseOrder)-[:BOUGHT_BY]->(b:Supplier)
      -[:SELLS_TO]->(po2:PurchaseOrder)-[:BOUGHT_BY]->(c:Supplier)
      -[:SELLS_TO]->(po3:PurchaseOrder)-[:BOUGHT_BY]->(a)
RETURN a, b, c, po1, po2, po3

-- 示例2：三单不匹配（采购订单-收货单-发票金额异常）
MATCH (po:PurchaseOrder)-[:HAS_RECEIPT]->(r:Receipt),
      (po)-[:HAS_INVOICE]->(inv:Invoice)
WHERE abs(po.amount - inv.amount) / po.amount > 0.1
   OR abs(r.quantity - po.quantity) / po.quantity > 0.05
RETURN po, r, inv
```

### 5.5 数据联邦查询策略（MCP）

**核心思路**：核心实体+交易明细入图，非核心数据通过 MCP 联邦查询。

```
架构方案：核心图谱 + 联邦查询

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

参考：MindsDB 的 MCP 联邦数据访问模式、Spice.ai 的联邦 MCP 客户端。

### 5.6 数据同步策略

**决策：Phase 1-2 使用 T+1 批量同步，Phase 3 按需升级 CDC。**

```
演进路径：
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

### 5.7 多源异构数据集成

**工具链**：
- 数据抽取：Apache SeaTunnel / DataX
- 增量同步：Debezium + Kafka（CDC，Phase 3）
- ID映射：构建统一实体映射表（PostgreSQL）

**图谱构建流程**：
1. 从各系统抽取原始数据到 ODS 层
2. 清洗、归一化、ID映射
3. 数据质量校验（Great Expectations）
4. 转换为图模型（点/边/属性）
5. 批量导入 NebulaGraph（使用 Exchange 或 Spark-Nebula）

### 5.8 前后端集成方案

#### 5.8.1 Phase 1 实现：matrix-js-sdk 直连（Approach B）

**决策：浏览器通过 matrix-js-sdk 直接连接 Tuwunel，不再使用 WebSocket 代理。**

```
登录流程：
  浏览器 POST /login → honeybadge-auth
                         ├─ 验证用户名密码
                         ├─ 在 Tuwunel 创建/登录 @hb-{user} 账号
                         └─ 返回 { matrix_access_token, matrix_homeserver, roles_jwt }

聊天流程：
  浏览器 matrix-js-sdk.createClient(homeserver, access_token)
    ↓
  client.startClient() → 建立 Matrix 长连接（SSE/长轮询）
    ↓
  findOrCreateManagerDmRoom() → 查找/创建与 @manager 的 DM 房间
    ↓
  sendEvent(roomId, 'm.room.message', { body, x-honeybadge, x-hb-auth })
    ↓
  监听 Room.timeline 事件 → 接收 Manager/Worker 的回复
```

**与 WebSocket 代理方案的对比**：

| 维度 | WebSocket 代理（旧） | matrix-js-sdk 直连（当前） |
|------|---------------------|--------------------------|
| 会话隔离 | ❌ 共享账号导致冲突 | ✅ 每用户独立 Matrix 身份 |
| 中间层 | honeybadge-server 代理 | 无（浏览器直连） |
| 流式输出 | WebSocket 推送 | Matrix Room 事件流 |
| 可审计性 | 代理层审计 | Matrix Room 历史天然可审计 |
| 复杂度 | 代理状态管理复杂 | 标准 Matrix SDK，无代理状态 |

#### 5.8.2 各通道职责

```
主通道：matrix-js-sdk（聊天 + Agent 响应流）
  - 用户发送问题 → Matrix DM 消息（x-honeybadge contract: 001）
  - 接收进度推送 → 纯文本 Matrix 事件（流式感知）
  - 接收最终结果 → Matrix 事件（x-honeybadge contract: 002）
  - 接收错误 → Matrix 事件（x-honeybadge contract: 003）

辅助通道：HTTP REST（honeybadge-auth + honeybadge-server）
  - POST /login（honeybadge-auth）：认证 + Matrix 账号创建
  - GET /api/health（honeybadge-server）：基础设施健康状态
  - GET /api/audit/{trace_id}（honeybadge-server）：审计查询（Phase 2）
  - GET /api/sessions（honeybadge-server）：历史会话列表（Phase 2）
```

#### 5.8.3 x-honeybadge 消息协议

| Contract | 方向 | 说明 |
|----------|------|------|
| 001 | 浏览器 → Manager | 用户查询请求 |
| 002 | graph-worker → 浏览器 | 查询结果（含 trace_id、raw_data） |
| 003 | graph-worker → 浏览器 | 错误响应 |
| 纯文本 | graph-worker → 浏览器 | 中间进度（思考过程、验证状态） |

### 5.9 可观测性体系

| 维度 | 工具 | 关键指标 |
|------|------|----------|
| 指标 | Prometheus + Grafana | LLM token消耗、查询P99延迟、错误率、并发数 |
| 日志 | Loki + Grafana | 结构化日志（含trace_id） |
| 调用链 | Jaeger / OpenTelemetry | 用户→Manager→Worker→NebulaGraph完整链路 |
| 告警 | Alertmanager | 错误率>5%、Nebula节点CPU>80% |

### 5.10 成本控制与配额管理

**策略**：
- 按用户/部门设置每日/月 token 配额（Redis计数）
- 查询结果缓存：向量缓存相似问题（Milvus/FAISS）
- 限制 Cypher 遍历深度（≤5跳）和返回行数（≤1000）
- 复杂查询转为异步任务，避免阻塞
- **大小模型分流**：简单查询用 GLM-4.7-Flash，复杂查询用 GLM-5，预计 60% 请求可走小模型

### 5.11 高可用与容灾

**部署架构**：
- HiClaw Manager：无状态，至少2个Pod + 负载均衡
- NebulaGraph：3 Meta + 3 Graph + 3-6 Storage（副本数2），Raft自动故障转移
- Redis：Cluster 模式
- Kafka：3 Broker 副本
- 备份：NebulaGraph每周全量+每日增量备份到MinIO
- LLM 推理：多台 Atlas 800T A3 + 负载均衡

---

## 六、数据质量保障体系

### 6.1 第一层：ETL 入图前校验（必做）

```
ERP 源数据 → 抽取(SeaTunnel) → ODS 暂存层 → 质量校验 → 图谱
                                       ↓
                                  校验失败 → 隔离区 + 告警
```

**具体校验规则（以 PTP 流程为例）**：

| 校验类型 | 规则示例 | 处理方式 |
|----------|---------|----------|
| 空值检查 | PO编号、供应商ID、金额不可为空 | 拒绝入图，写入隔离表 |
| 类型检查 | 金额必须为正数、日期格式统一（ISO 8601） | 自动修正或拒绝 |
| 引用完整性 | PO关联的供应商必须已存在于供应商主数据中 | 拒绝入图，标记为"悬挂引用" |
| 唯一性检查 | 同一PO编号不可重复入图 | 去重，保留最新版本 |
| 业务规则 | PO金额 = SUM(PO行项目金额) | 标记异常，人工审核 |
| 时序一致性 | PO创建日期 ≤ 收货日期 ≤ 发票日期 ≤ 付款日期 | 标记异常 |
| 值域校验 | 币种必须在标准币种列表内，税率在合理范围 | 拒绝入图 |

**推荐工具：Great Expectations（Python）**

```python
# 示例：PurchaseOrder 数据质量校验
import great_expectations as gx

validator.expect_column_values_to_not_be_null("po_number")
validator.expect_column_values_to_not_be_null("supplier_id")
validator.expect_column_values_to_be_between("amount", min_value=0)
validator.expect_column_values_to_be_in_set("currency", ["CNY", "USD", "EUR", "JPY"])
validator.expect_column_values_to_match_regex("po_number", r"^PO-\d{8,}$")

# 时序校验
validator.expect_column_pair_values_A_to_be_greater_than_B(
    "receipt_date", "po_create_date", or_equal=True
)

# 引用完整性（供应商必须存在）
validator.expect_column_values_to_be_in_set(
    "supplier_id",
    existing_supplier_ids  # 从供应商主数据加载
)
```

### 6.2 第二层：图谱一致性校验（每日巡检）

入图后定期验证图的结构完整性：

```cypher
-- 1. 孤立节点检测（无任何边的节点）
MATCH (n) WHERE NOT (n)--() RETURN labels(n), count(n)

-- 2. 采购订单完整性（每个PO必须关联供应商）
MATCH (po:PurchaseOrder)
WHERE NOT (po)-[:PLACED_WITH]->(:Supplier)
RETURN po.po_number AS orphan_po

-- 3. 三单匹配完整性（PO应有对应的Receipt和Invoice）
MATCH (po:PurchaseOrder)
WHERE NOT (po)-[:HAS_RECEIPT]->(:Receipt)
   OR NOT (po)-[:HAS_INVOICE]->(:Invoice)
RETURN po.po_number, po.status

-- 4. 环路检测（不应出现的循环关系）
MATCH path = (s:Supplier)-[:SELLS_TO*3..6]->(s)
RETURN path

-- 5. 数据新鲜度（检查最近一次更新时间）
MATCH (po:PurchaseOrder)
RETURN max(po.update_time) AS latest_update
-- 如果 latest_update 超过 2 天，说明 ETL 管道可能故障
```

### 6.3 第三层：数据质量看板（持续运营）

```
┌─────────────────────────────────────────────────────────┐
│                  数据质量 Grafana 看板                     │
├─────────────────────────────────────────────────────────┤
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│  │ 完整率 98.5% │ │ 准确率 99.2% │ │ 一致率 97.8% │     │
│  │  ▲ +0.3%    │ │  ▼ -0.1%    │ │  ▲ +0.5%    │     │
│  └──────────────┘ └──────────────┘ └──────────────┘     │
│                                                          │
│  各实体类型质量趋势（近30天）                              │
│   供应商: 99.5%  物料: 98.2%  PO: 97.8%                 │
│   发票: 96.5% ← 需要关注                                 │
│                                                          │
│  今日异常                                                 │
│   ⚠ 23 条 PO 缺少供应商引用                              │
│   ⚠ 5 条发票金额与 PO 偏差 >10%                          │
│   ⚠ 12 个孤立供应商节点                                   │
│                                                          │
│  告警规则：                                               │
│   • 完整率 < 95% → P1 告警                               │
│   • 孤立节点 > 100 → P2 告警                             │
│   • ETL 超过 26 小时未执行 → P1 告警                      │
└─────────────────────────────────────────────────────────┘
```

**核心指标定义**：

| 指标 | 定义 | 计算方式 | 目标 |
|------|------|----------|------|
| 完整率 | 关键字段非空比例 | 非空记录数 / 总记录数 | >98% |
| 准确率 | 数据值在合理范围内的比例 | 通过规则校验记录数 / 总记录数 | >99% |
| 一致率 | 跨系统数据一致的比例 | 图中数据与源系统一致的记录数 / 抽检总数 | >97% |
| 及时率 | 数据在约定时间内到达 | T+1 按时到达天数 / 总天数 | >99% |
| 引用完整率 | 关系两端节点都存在的比例 | 有效边数 / 总边数 | >99.5% |

---

## 七、NebulaGraph 数据规模与膨胀评估

### 7.1 关系型数据 → 图数据的膨胀比例

```
场景1：简单实体（如供应商主数据）
  1 行记录 → 1 个节点 + N 个属性
  膨胀比：~1:1（几乎不膨胀）

场景2：关系表（如采购订单）
  1 条 PO 记录 → 1 个 PO 节点
                + 1 条 PLACED_WITH 边（→ 供应商）
                + 1 条 ORDERED_BY 边（→ 采购员）
                + 1 条 CONTAINS 边 × N（→ 行项目）
                + 1 条 BELONGS_TO 边（→ 组织/工厂）
  膨胀比：~1:4-6（一条记录变成 1 个节点 + 4-6 条边）

场景3：多对多关系表（如物料-供应商认证）
  1 条认证记录 → 1 条边（物料→供应商）+ 边属性
  膨胀比：~1:1

场景4：BOM（物料清单）
  1 条 BOM 父子关系 → 1 条边
  BOM 展开后 N 层嵌套 → 边数指数增长
  膨胀比：依层数而定，可能 1:10-50
```

### 7.2 本项目数据规模估算

```
假设关系型数据库中：百亿级记录（100 亿条）

转换到图数据库后：
  - 节点数：约 30-50 亿（很多记录共享实体，如同一个供应商被多个 PO 引用）
  - 边数：约 200-500 亿（每条交易记录平均产生 2-5 条关系边）
  总规模：约 200-550 亿点边

NebulaGraph 边存储特点：
  - 每条逻辑边 = 2 个 KV 对（正向 + 反向索引）
  - 边的存储膨胀系数 ≈ 2x

存储空间估算：
  参考携程金融配置（3 台 64核/320GB/12TB SSD 支撑百亿级）
  本项目可能需要 6-12 台同等配置的机器
```

---

## 八、基础设施容量规划

### 8.1 请求处理链路分析

```
单次请求处理链路及耗时：
  用户提问 → HiClaw Manager(~50ms) → LLM 生成 Cypher(~2-5s)
  → Cypher 校验(~50ms) → NebulaGraph 查询(~100-500ms)
  → LLM 生成摘要(~1-3s) → 返回用户

单次请求的 LLM 调用：2 次（生成 Cypher + 生成摘要）
单次请求 token 消耗：输入~2000-4000 tokens，输出~500-1500 tokens
单次请求端到端耗时：简单查询 ~5s，复杂查询 ~15-30s
```

### 8.2 场景一：1000 人在线，100 并发

| 组件 | 配置 | 数量 | 说明 |
|------|------|------|------|
| **LLM 推理** | Atlas 800T A3（8×昇腾910B） | **8 台** | 有效LLM并发≈140，单台支撑~20并发，含1台冗余 |
| NebulaGraph Meta | 16核/64GB/500GB SSD | 3 台 | 轻量级，可混部 |
| NebulaGraph Graph | 32核/128GB/1TB NVMe SSD | 3 台 | 计算节点 |
| NebulaGraph Storage | 64核/256GB/8TB NVMe SSD | 6 台 | 百亿级数据，副本数2 |
| HiClaw Manager | 8核/16GB/100GB SSD | 3 Pod | 无状态 |
| HiClaw Worker | 8核/16GB/100GB SSD | 5-8 Pod | 按技能分组 |
| Matrix Server | 8核/32GB/500GB SSD | 2 Pod | |
| Redis Cluster | 8核/64GB/200GB SSD | 6 台 | 3主3从 |
| Kafka | 8核/32GB/1TB SSD | 3 台 | 3 Broker |
| Milvus | 16核/64GB/500GB SSD | 3 台 | 可选，后期引入 |
| Higress 网关 | 8核/16GB | 3 Pod | |
| Prometheus+Grafana+Loki | 16核/32GB/500GB SSD | 2 台 | |
| Jaeger | 16核/32GB/500GB SSD | 1 台 | |
| MinIO | 8核/32GB/4TB HDD | 3 台 | |
| ETL (SeaTunnel) | 16核/64GB/500GB SSD | 2 台 | |
| **合计** | | **约 30-35 台** | **64 张昇腾 910B** |

### 8.3 场景二：500 人在线，50 并发

| 组件 | 配置 | 数量 | 说明 |
|------|------|------|------|
| **LLM 推理** | Atlas 800T A3（8×昇腾910B） | **4 台** | 有效LLM并发≈70，含1台冗余 |
| NebulaGraph Meta | 16核/64GB/500GB SSD | 3 台 | |
| NebulaGraph Graph | 32核/128GB/1TB NVMe SSD | 3 台 | |
| NebulaGraph Storage | 64核/256GB/8TB NVMe SSD | 3 台 | 副本数2 |
| HiClaw + Matrix | 混部通用服务器 | 2-3 台 | Manager 2 Pod + Worker 3-5 Pod |
| Redis | 3主0从 | 混部 | |
| Kafka | 3 Broker | 混部 | |
| 网关+监控+ETL+MinIO | 混部通用服务器 | 2-3 台 | |
| **合计** | | **约 21-23 台** | **32 张昇腾 910B** |

### 8.4 两场景对比与优化

| 维度 | 500在线/50并发 | 1000在线/100并发 |
|------|---------------|-----------------|
| Atlas 800T A3 | 4 台 | 8 台 |
| 昇腾 910B | 32 张 | 64 张 |
| NebulaGraph 节点 | 9 台 | 12 台 |
| 通用服务器 | 8-10 台 | 15-18 台 |
| **总服务器** | **21-23 台** | **30-35 台** |
| LLM 推理成本占比 | ~65-70% | ~65-70% |

**成本优化建议**：

1. **缓存是最有效的降本手段**：语义缓存命中率每提升 10%，LLM 服务器需求减少 ~1 台。目标：缓存命中率达 30-40%（ERP 查询重复度高）
2. **大小模型分流**：简单查询用 GLM-4.7-Flash，复杂查询用 GLM-5，预计 60% 请求可走小模型
3. **优化后估算**：
   - 场景二：2 台 GLM-5 + 1 台 GLM-4.7-Flash ≈ 3 台 Atlas 800T A3
   - 场景一：4 台 GLM-5 + 2 台 GLM-4.7-Flash ≈ 6 台 Atlas 800T A3

---

## 九、实施路线图（含学习曲线）

> **重要说明**：本计划充分考虑了团队刚接触知识图谱、分布式图数据库、Agent 编排等技术领域的学习曲线。每个阶段都将学习时间显式纳入。

### 9.1 Phase 1：基础设施升级（20 周，约 5 个月）

#### 9.1.1 前 4 周：团队技术预研（最关键的投入）

```
第 1 周：NebulaGraph 深度学习
  - 全员完成官方教程（Studio 使用、nGQL 语法）
  - 在单机版上练习 CRUD 和多跳查询
  - 用现有 POC 数据做迁移试验
  - 重点理解 Space/Tag/Edge Type/Index 概念
  - 理解存算分离架构：Meta/Graph/Storage 角色

第 2 周：HiClaw + Higress 学习
  - 搭建 HiClaw 开发环境（Docker Compose）
  - 完成官方 Quick Start
  - 理解 Manager-Worker-Matrix Room 交互流程
  - 尝试写一个简单的 Worker Skill
  - 理解 MCP Server 集成方式

第 3 周：LLM 推理部署学习
  - 在昇腾 910B 上部署 GLM-5（W4A8 量化）
  - 学习 MindIE / vLLM-Ascend 推理框架
  - 做基础的吞吐量和延迟测试
  - 理解 continuous batching、KV Cache 等关键概念

第 4 周：集成试验
  - 把上述三个组件串联起来做一个端到端 Demo
  - 发现集成中的问题，调整后续计划
  - 形成团队的技术文档和最佳实践
```

#### 9.1.2 Phase 1 完整任务表

| 任务 | 周期 | 含学习时间 | 依赖 |
|------|------|-----------|------|
| 团队技术预研与学习 | 4 周 | 4 周 | - |
| NebulaGraph 集群搭建 + Schema 设计 | 3 周 | 含 1 周摸索 | 预研完成 |
| Neo4j → NebulaGraph 数据迁移 | 3 周 | 含 1 周兼容性踩坑 | NebulaGraph 就绪 |
| HiClaw 部署 + Manager/Worker 配置 | 3 周 | 含 1.5 周学习 | 预研完成 |
| Higress 网关 + SSO 对接 | 4 周 | 含 1 周学习 + 2 周企业协调 | - |
| 可观测性体系 | 2 周 | 含 0.5 周学习 | - |
| 前端 WebSocket 基础界面 | 3 周 | 含 1 周学习 HiClaw API | HiClaw 就绪 |
| 防幻觉框架（五层 Cypher 校验 + 审计日志） | 3 周 | 含 1 周设计 | NebulaGraph 就绪 |
| 集成测试 + 修复 | 3 周 | - | 以上全部 |
| 缓冲 | 2 周 | - | |
| **合计** | **~20 周** | **~10 周** | |

### 9.2 Phase 2：业务能力扩展（20 周，约 5 个月）

| 任务 | 周期 | 含学习时间 | 依赖 |
|------|------|-----------|------|
| 权限 MCP Server 开发 | 3 周 | 含 1 周 MCP 协议学习 | Phase 1 完成 |
| Cypher 权限注入中间件（AST 级改写） | 3 周 | 含 1 周 Cypher AST 学习 | Phase 1 完成 |
| ERP 数据 ETL 管道（T+1，PTP 全流程） | 5 周 | 含 2 周 SeaTunnel 学习 | NebulaGraph 就绪 |
| 数据质量校验框架（三层） | 3 周 | 含 1 周 Great Expectations 学习 | ETL 管道就绪 |
| 本体模块化 + 动态检索 | 3 周 | 含 1 周向量检索学习 | Phase 1 完成 |
| 虚假交易检测图模式开发 | 4 周 | 含 2 周业务学习 | ETL 完成，需审计专家 |
| 成本控制（配额 + 缓存） | 2 周 | - | - |
| 高可用部署 + 备份 + 故障演练 | 2 周 | 含 1 周 NebulaGraph 运维学习 | - |
| 压力测试与调优 | 3 周 | - | 以上全部 |
| 缓冲 | 2 周 | - | |
| **合计** | **~20 周** | **~8 周** | |

### 9.3 Phase 3：全面生产（24 周，约 6 个月）

| 任务 | 周期 | 说明 |
|------|------|------|
| CDC 准实时同步（Debezium + Kafka） | 5 周 | 重点数据的分钟级同步 |
| 多模态数据融合 | 5 周 | 合同/图纸的元数据入图 |
| 外围系统 MCP 接入（CRM/WMS） | 4 周 | 联邦查询 |
| 模型降级路由（大小模型分流） | 3 周 | 成本优化关键 |
| 自动化本体演化 | 4 周 | 本体版本管理 |
| 全面压测 + 安全审计 | 3 周 | |
| 缓冲 | 2 周 | |
| **合计** | **~24 周** | |

### 9.4 整体时间线与关键里程碑

```
Phase 0: MVP 验证                ✅ 已完成
Phase 1: 基础设施升级             20 周（~5 个月）
Phase 2: 业务能力扩展             20 周（~5 个月）
Phase 3: 全面生产                24 周（~6 个月）

总计：~16 个月（Phase 1 开始算起）

关键里程碑：
  M1 (第 4 周)  ：技术预研完成，团队具备基本技能
  M2 (第 12 周) ：NebulaGraph + HiClaw + LLM 端到端跑通
  M3 (第 20 周) ：Phase 1 完成，内部小范围试用
  M4 (第 30 周) ：权限 + ETL 完成，可以给业务部门用
  M5 (第 40 周) ：Phase 2 完成，进入生产级运营
  M6 (第 60 周) ：Phase 3 完成，全面生产
```

---

## 十、团队配置

### 10.1 核心团队（5-6 人）

| 角色 | 人数 | 职责 | 技能要求 |
|------|------|------|----------|
| 架构师/Tech Lead | 1 | 全栈架构决策，NebulaGraph Schema 设计，HiClaw 编排设计 | 分布式系统经验，最好有图数据库基础 |
| Python 后端工程师 | 1 | HiClaw Worker 开发、LLM 集成、防幻觉框架、Prompt 工程 | Python 熟练，有 AI/NLP 兴趣 |
| Java 后端工程师 | 1 | 权限 MCP Server、ETL 管道、ERP 系统对接 | Java 熟练，有企业应用开发经验 |
| 数据工程师 | 1 | NebulaGraph 运维、ETL（SeaTunnel）、数据质量校验 | 强 SQL 基础，ETL 经验 |
| 前端工程师 | 1 | WebSocket 聊天界面、数据可视化（图谱可视化）、Grafana 看板 | React/Vue，可视化经验 |
| DevOps/SRE | 1（可半专职） | K8s 集群、昇腾推理集群运维、CI/CD | K8s 经验，需学习昇腾 CANN |

### 10.2 兼职/顾问角色

| 角色 | 参与方式 | 职责 |
|------|----------|------|
| 业务分析师 | Phase 2 兼职或全职 | PTP/OTC 流程专家，虚假交易检测规则，本体定义和维护 |
| 安全专家 | 兼职 | 权限模型审核，安全测试 |
| NebulaGraph 外部顾问 | Phase 1 初期 | 培训 + 架构评审（1-2 天培训比自学 2 周高效） |

### 10.3 每个角色的学习重点

| 角色 | 需要学习的技术 | 预计学习时间 | 建议学习资源 |
|------|--------------|-------------|-------------|
| 架构师 | NebulaGraph 架构 + HiClaw + LLM 推理原理 | 3-4 周 | 官方文档 + 美团/携程案例 |
| Python 后端 | HiClaw Worker 开发 + MCP 协议 + Prompt 工程 | 3 周 | HiClaw 官方示例 |
| Java 后端 | MCP Server 开发 + Spring AI Alibaba | 2 周 | 阿里云 MCP 文档 |
| 数据工程 | NebulaGraph nGQL + SeaTunnel + Great Expectations | 3 周 | NebulaGraph Academy |
| 前端 | Matrix Client API + WebSocket + 图可视化 | 2 周 | Element Web 源码 |
| DevOps | 昇腾 CANN + MindIE/vLLM-Ascend + K8s | 3 周 | 昇腾社区文档 |

### 10.4 AI 辅助提效分析

**可大量借助 AI 的工作（节省 50%+ 时间）**：
- Cypher 查询编写和调试
- ETL 脚本开发
- 数据质量校验规则编写
- 前端 UI 组件开发
- 单元测试编写
- Grafana 看板 JSON 配置
- 文档编写

**仍需人工主导的工作（AI 辅助有限）**：
- 本体建模（需要深度业务理解）
- NebulaGraph 集群调优（需要实际压测经验）
- 企业 SSO 对接（涉及组织协调）
- 虚假交易检测规则设计（需要审计专业知识）
- 权限模型设计（安全要求高）

### 10.5 降低学习风险的建议

1. **请外部顾问**：NebulaGraph 有官方技术支持和培训服务，1-2 天的专项培训比自学 2 周高效得多
2. **分阶段验证**：先用 Docker Compose 在单机跑通全链路，再逐步切换到分布式集群；先用云端 API（千问/GLM API）验证，再切换到自部署模型
3. **建立内部知识库**：从 Phase 1 开始，每个人把踩过的坑记录下来，形成团队 Runbook
4. **善用 AI 辅助学习**：用 AI 帮助理解技术文档，生成示例代码并在开发环境中验证

### 10.6 工作量估算

```
Phase 1 (20周): 5 人 × 20 周 = 100 人周
Phase 2 (20周): 5-6 人 × 20 周 = 100-120 人周
Phase 3 (24周): 7-8 人 × 24 周 = 168-192 人周

总计 Phase 1+2: 约 200-220 人周（~10 个月，5-6 人团队）
总计全部: 约 370-410 人周（~16 个月）
```

---

## 十一、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| NebulaGraph 学习曲线陡峭 | 高 | 中 | Phase 1 前 4 周专项预研 + 请外部顾问培训 |
| HiClaw 文档不完善 / 社区支持有限 | 中 | 中 | 提前在阿里云社区建立联系，备选 LangGraph/Dify |
| 昇腾 910B 部署 GLM-5 踩坑 | 中 | 高 | Phase 1 第 3 周专项攻关 + 昇腾社区支持 |
| Cypher 兼容性问题（Neo4j → NebulaGraph） | 高 | 中 | 迁移时逐条验证，预留 1 周缓冲 |
| 权限注入导致 Cypher 生成错误 | 中 | 高 | AST 级校验 + 单元测试 + 灰度发布 |
| LLM token 成本超预期 | 高 | 中 | 大小模型分流 + 语义缓存 + 配额管理 |
| 企业 SSO 对接协调困难 | 高 | 中 | 预留 4 周（含 2 周协调），提前与 IT 部门沟通 |
| 数据质量问题（源系统数据不干净） | 高 | 高 | 三层数据质量校验 + 隔离区 + 质量看板 |
| LLM 幻觉导致查询结果不准确 | 中 | 极高 | 五层防幻觉框架 + 原始数据直传 + 全链路审计 |
| 团队学习周期超预期 | 高 | 中 | 已在计划中预留约 50% 学习时间，必要时延长 Phase 1 |

---

## 十二、业界实践对比分析

### 12.1 SAP Knowledge Graph + Joule Agent

**架构**：SAP BTP 平台上的语义知识图谱（SKG），基于 OWL/RDFS 本体，覆盖 S/4HANA、Ariba、Concur 等产品。Joule 从 2023 年 Copilot 演进到 2025 年自主 Agent，采用 plan-execute-reflect 循环。

| 维度 | SAP KG + Joule | HoneyBadge |
|------|---------------|------------|
| 图数据库 | HANA Graph（专有） | NebulaGraph（开源分布式） |
| 本体 | 封闭，SAP 定义，客户不可扩展 | 开放，自定义，ontology-as-prompt |
| 查询语言 | SPARQL/CDS（隐藏） | Cypher/nGQL（可审计，对 LLM 更友好） |
| Agent | Joule（单Agent，专有） | HiClaw（多Agent，开源） |
| ERP 语义 | 深度 SAP 原生理解 | 需手动建模（PTP/OTC），但完全可定制 |
| NL→查询 | NL→CDS/OData | NL→Cypher + 本体约束，准确率更高 |
| 扩展性 | 低（SAP 控制） | 高（全开源栈） |
| 锁定风险 | 高 | 低 |

**可借鉴**：
- PO 生命周期状态机建模（Created → Approved → GR → IV → Payment）
- plan-execute-reflect Agent 循环
- 跨模块图遍历能力（财务凭证→采购单→供应商）

### 12.2 metaphacts 企业知识图谱平台

**架构**：基于 RDF/SPARQL 标准，支持物化和虚拟知识图谱，服务西门子、博世等制造企业。

| 维度 | metaphacts | HoneyBadge |
|------|-----------|------------|
| 图模型 | RDF（三元组） | Property Graph |
| 虚拟图谱 | 支持（R2RML） | 通过 MCP 弥补 |
| 本体角色 | 核心（SHACL 校验） | 核心（Prompt 注入） |
| LLM 友好度 | SPARQL（LLM 难生成） | Cypher（LLM 友好） |
| Agent | 无（需外部集成） | HiClaw 多Agent |

**可借鉴**：
- 虚拟知识图谱思路（不搬数据，查询源系统）——与 MCP 联邦查询方向一致
- SHACL 数据校验——在图入库前做 Schema 校验

### 12.3 Neo4j + LangChain GraphRAG

**架构**：LLM 提取实体关系构图 → Cypher 查询 → 向量+图混合检索 → LLM 生成答案。

| 维度 | Neo4j GraphRAG | HoneyBadge |
|------|---------------|------------|
| 构图方式 | LLM 抽取（有噪声） | Schema 驱动（ERP 结构化数据，干净） |
| 本体 | 通常缺失 | 核心（ontology-as-prompt） |
| NL→查询准确率 | ~60-80%（无 Schema 约束） | 预计 ~80-90%+（有本体约束） |
| 分布式 | Neo4j 单机受限 | NebulaGraph 原生分布式 |

**可借鉴**：
- 混合检索（Graph + Vector）——图结构查询 + 向量相似度搜索结合
- 社区摘要（Microsoft GraphRAG）——预计算社区摘要支持全局/聚合查询
- 三阶段 Cypher 校验（语法→Schema→逻辑）——已纳入防幻觉体系

### 12.4 美团 NebulaGraph 供应链知识图谱

**实际数据**：近10个领域知识图谱，数据量千亿级；智能助理百亿级点边，13类实体、22类关系；一跳 TP99 5ms，两跳 TP99 20ms；在线写入 20万/s。

| 维度 | 美团 KG | HoneyBadge |
|------|--------|------------|
| 图数据库 | NebulaGraph（相同） | NebulaGraph（相同） |
| LLM 集成 | 无 | 核心 |
| 本体 | 隐含在 Schema | 显式，作为 Prompt |
| 欺诈检测 | 有（环检测） | 需要（虚假交易检测） |

**可借鉴**：
- 欺诈检测图模式匹配（环检测、异常社区发现）
- 写入性能基准（20万/秒）作为 T+1 批量导入参考
- 集群配置参考（3台 64核/320GB/12TB SSD 支撑百亿级）

### 12.5 京东 NebulaGraph 商品知识图谱

**实际数据**：数十亿产品节点，数百亿边，数十万 QPS。

| 维度 | 京东 KG | HoneyBadge |
|------|--------|------------|
| 增量更新 | Flink 实时流处理 | Phase 1-2: T+1，Phase 3: CDC |
| 实体解析 | NLP 抽取 + 去重 | ERP 结构化数据（更简单） |

**可借鉴**：
- Flink 增量更新管道（Phase 3 CDC 参考）
- 多集群按域分区策略

### 12.6 Spice.ai 联邦 MCP 客户端

**架构**：Rust 编写的联邦查询引擎，通过 MCP 协议连接多数据源。

| 维度 | Spice.ai | HoneyBadge |
|------|---------|------------|
| 数据模型 | 关系型（SQL 联邦） | 图（NebulaGraph） |
| 联邦查询 | 核心能力 | 通过 MCP 补充 |
| 图能力 | 无 | 全图遍历、算法 |

**可借鉴**：
- MCP 联邦查询模式——将 NebulaGraph 封装为 MCP Server
- 加速层（本地缓存）——对频繁查询的外围数据做本地加速

### 12.7 HoneyBadge 的独特定位

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

**核心差异化**：同时具备大规模图引擎 + 多Agent编排 + 本体驱动的NL接口 + 零幻觉审计能力。LLM Agent + 知识图谱 + 企业 ERP 这个组合在国内属于前沿实践。

---

## 十三、后续可扩展方向

- 引入 RAG 检索增强（结合向量数据库，Graph + Vector 混合检索）
- 支持自然语言生成图表（如订单趋势分析）
- 主动风险预警（基于规则引擎推送，图模式定期扫描）
- 与业务流程集成（如自动创建采购申请）
- 社区摘要（Microsoft GraphRAG 模式，支持聚合类问题）
- 将 NebulaGraph 封装为 MCP Server，未来可接入任何 MCP 兼容的 Agent

---

## 附录

### A. 参考资源

- [HiClaw 文档](https://github.com/alibaba/hiclaw)
- [NebulaGraph 官网](https://nebula-graph.io/)
- [NebulaGraph 资源准备文档](https://docs.nebula-graph.com.cn/3.8.0/4.deployment-and-installation/1.resource-preparations/)
- [昇腾 910B 部署 GLM-5](https://www.hiascend.com/activities/dynamic-news/648)
- [GLM-5 技术细节](https://www.cnblogs.com/Yanjy-OnlyOne/p/19633185)
- [Spring AI Alibaba MCP 集成](https://www.alibabacloud.com/blog/java-development-with-mcp-from-claude-automation-to-spring-ai-alibaba-ecosystem-integration_602189)
- [Higress MCP Server 托管方案](https://www.alibabacloud.com/blog/higress-open-source-remote-mcp-server-hosting-solution-and-upcoming-mcp-market_602108)
- [美团图数据库平台建设](https://tech.meituan.com/2021/04/01/nebula-graph-practice-in-meituan.html)
- [携程金融 NebulaGraph 实践](https://www.cnblogs.com/nebulagraph/p/16963727.html)
- [MindsDB MCP 联邦数据访问](https://mindsdb.com/unified-model-context-protocol-mcp-server-for-databases)
- [Spice.ai 联邦 MCP 客户端](https://spiceai.org/docs/use-cases/ai/federated-mcp-server)
- [LLM + Knowledge Graph 减少幻觉](https://arxiv.org/abs/2504.12422)
- [metaphacts 企业知识图谱](https://blog.metaphacts.com/from-data-to-decisions-how-enterprise-ai-powered-by-knowledge-graphs-is-redefining-business-intelligence)
- [OpenTelemetry](https://opentelemetry.io/)
- [Apache Jena](https://jena.apache.org/)
- [Great Expectations](https://greatexpectations.io/)

### B. 术语表

| 术语 | 说明 |
|------|------|
| PTP | Procure-to-Pay，从采购到付款的完整业务流程 |
| OTC | Order-to-Cash，从订单到收款的完整业务流程 |
| BOM | Bill of Materials，物料清单 |
| MCP | Model Context Protocol，Anthropic 提出的 LLM 与外部工具通信协议 |
| CDC | Change Data Capture，变更数据捕获 |
| MoE | Mixture of Experts，混合专家模型架构 |
| nGQL | NebulaGraph Query Language |
| W4A8 | Weight 4-bit, Activation 8-bit 混合精度量化 |
| GraphRAG | Graph Retrieval-Augmented Generation，图增强检索生成 |

### C. 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v1.0 | 2026-04-03 | 初始技术讨论纪要 |
| v2.0 | 2026-04-04 | 整合全部架构讨论：四阶段演进、防幻觉体系、数据入图策略修正、权限集成方案、容量规划（两场景）、团队配置、学习曲线计划、业界实践对比分析 |
| v3.0 | 2026-04-10 | Phase 1 Approach B 实现说明：（1）5.3 节—多用户会话隔离根因分析与 per-user Matrix 账号方案；（2）5.8 节—前后端通信从 WebSocket 代理改为 matrix-js-sdk 直连；（3）4.1 节—HiClaw per-channel-peer 机制与 Approach B 关系说明；（4）3.1 节—更新 Phase 1 实际架构图；（5）新增 honeybadge-auth 微服务说明 |
