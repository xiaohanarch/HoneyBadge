---
marp: true
theme: default
paginate: true
size: 16:9
header: 'Project HoneyBadge'
footer: 'GitHub · xiaohanarch/HoneyBadge'
style: |
  section { font-size: 26px; }
  h1 { color: #1f2a44; }
  h2 { color: #1f2a44; border-bottom: 2px solid #f5b400; padding-bottom: 4px; }
  table { font-size: 22px; }
  code { background: #f3f4f6; padding: 1px 6px; border-radius: 4px; }
  blockquote { border-left: 4px solid #f5b400; color: #444; }
---

<!-- _class: lead -->

# Project HoneyBadge
## 企业知识图谱智能助手 · 一个 AI 原生的 ERP 审计大脑

让每一次查询都有迹可循 —— **零幻觉、可审计、可追溯**

v1.0.0 · Apache 2.0 全栈 · GitHub: xiaohanarch/HoneyBadge

---

## 一、Why · 真实痛点

- 大型企业 ERP（Oracle EBS / 自研）沉淀了 **百亿级** 采购、销售、付款、收货数据
- 业务人员问一个问题，需要跨 **5+ 张表 + PTP/OTC 双流程** 手写 SQL
- 风控/审计做 **虚假交易检测** 只能靠经验抽查，覆盖率 < 1%
- 主流 LLM 直接接 ERP = **幻觉灾难**：在财务场景，编造一个金额就是合规事故

> 我们要的不是"更聪明的 ChatGPT"，而是**一个可被审计部门作为证据采纳的 AI**

---

## 二、Why · 要解决的问题

| 问题 | 现状 | HoneyBadge 目标 |
|---|---|---|
| 自然语言问 ERP | 不可能 | 中文一问即答 |
| 跨流程关联分析 | 手写 SQL 数小时 | nGQL 多跳查询数秒 |
| 虚假交易检测 | 抽查 1% | 12 种异常模式全量扫描 |
| 审计追溯 | 翻日志 | trace_id 到字节级溯源 |
| LLM 幻觉 | 不可控 | **5 层防幻觉框架** |

**核心场景**：循环交易 · 拆单规避审批 · 对倒交易（Round-Tripping）· 三单不匹配 · 断供影响链分析

---

## 三、What · 一句话定义 + 系统全景

**HoneyBadge = NebulaGraph（图谱）+ HiClaw（多 Agent）+ 5 层防幻觉框架 + 全链路审计 + 12 类欺诈检测本体**

```text
Vue3 + matrix-js-sdk
  → honeybadge-auth      (每用户独立 Matrix 账号)
  → Tuwunel Matrix       (浏览器直连,零中间代理)
  → HiClaw Manager       (Higress + MinIO 一体)
  → graph/analytics worker  (无状态,可弹性扩缩)
  → MCP Servers          (nebula / audit / cache)
  → NebulaGraph 3.8 / PostgreSQL / Redis
```

---

## 四、What · 与主流 Agent 框架的差异

| 维度 | **HoneyBadge** | OpenClaw | DeerFlow | HiClaw 原版 | HermesClaw |
|---|---|---|---|---|---|
| 反幻觉 | ✅ **5 层(唯一)** | ❌ | ❌ | ❌ | ❌ |
| 全链路审计 | ✅ trace_id 到结果 | ❌ JSONL | token 级 | Matrix 历史 | SQLite |
| AST 级权限注入 | ✅ | ❌ | ❌ | Consumer token | OPA |
| L4 原始数据透传 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 领域知识 | ✅ 12 份本体 + 关键词路由 | 通用 | 通用 | 通用 | 118 通用技能 |

> 唯一同时具备 **大规模图引擎 + 多 Agent 编排 + 本体驱动 NL 接口 + 零幻觉审计** 的方案

---

## 五、How · 五大技术难题概览

1. **LLM 幻觉** — 模型可能编造一个不存在的金额
2. **多用户会话碰撞** — HiClaw per-channel-peer 假设让共享账号失效
3. **图谱权限注入** — 字符串拼接 = SQL 注入级别风险
4. **本体爆炸** — 12 个业务域全注入会撑爆 token
5. **CRLF 静默杀手** — 一个 `\r` 让 ConfigMap 在生产里悄无声息地崩

> 接下来逐个说明我们怎么解的

---

## 六、How · 难题 1：五层防幻觉框架

```text
用户问题
  │
  ├─ L1  nGQL 语法校验    (parser 级,错误重生成)
  ├─ L2  Schema 校验      (Tag/Edge/属性必须真实存在)
  ├─ L3  权限注入         (AST 级改写,注入 org_id 过滤)
  ├─ 执行 NebulaGraph
  ├─ L4  原始结果透传     (LLM 只能包装,不能改数)
  └─ L5  PostgreSQL 审计  (question→nGQL→raw→summary)
```

**核心原则**：**LLM 只翻译,不回答**
前端永远展示「AI 摘要 + 原始数据 + 执行的 nGQL + 审计 ID」四件套,用户可肉眼交叉验证

---

## 七、How · 难题 2：多用户隔离 Approach B

**根因**：HiClaw Manager 对每个 Matrix peer 只维护一个活跃 DM。共享 `@gateway` 账号 → 第二个用户的消息直接被丢弃

**解法**：登录时 `honeybadge-auth` 在 Tuwunel 为每个用户创建专属账号 `@hb-{username}`,浏览器拿 `matrix_access_token` **直连** Tuwunel,绕开所有中间代理

| 维度 | 旧方案 (WebSocket 代理) | Approach B (当前) |
|---|---|---|
| 会话隔离 | per-channel-peer 冲突 | 每用户独立身份 |
| 中间层 | server 代理 | **零代理** |
| 可审计性 | 代理层手写 | Matrix Room 天然历史 |

附加创新：**服务端预创建 DM 房间**(写入 `m.direct`),消除客户端房间发现竞态

---

## 八、How · 难题 3 + 4：权限注入 & 本体路由

**AST 级权限注入**

```text
错误:  query + " WHERE org_id = " + user.org_id   ← 注入风险
正确:  parse → AST → 注入过滤 → 序列化  (无过滤即拒绝执行)
```

权限服务(已有 Java SDK)封装为 **MCP Server**,零业务代码改动复用

**本体路由 — 给 LLM 读的 markdown**

- 12 份本体文件,每份头部 `> **Keywords**: 供应商,supplier,vendor,...`
- 路由算法:`overview` 必选 → 关键词 Top 3 → 风险词触发 `constraints` → fallback `master-data`
- 单次 Prompt 仅注入 ~3-4 份本体,**token 节省 60%+**

---

## 九、How · 工程亮点速览

- **零信任凭证**:Worker 永远不持有真实 LLM API Key(继承自 HiClaw + Higress)
- **Worker 完全无状态**:配置全部从 MinIO 拉,可任意销毁重建
- **CRLF 三层防御**:`.gitattributes` → `.editorconfig` → `.githooks/pre-commit` 阻断 `*.sh|.py|.yaml|.ngql`
- **K8s 已落地**:单节点 k3s + 15 pods Running 在 ECS 公网验证通过
- **E2E 测试矩阵**:auth / chat / session / isolation / permission / antihal / mcp / infra / observability 共 9 大类标记

---

## 十、当前的诚实短板

| 短板 | 现状 | 影响 |
|---|---|---|
| 链路 6 跳 | User→Matrix→Manager→Worker→MCP→Higress→LLM | 简单查询也要 ~5s |
| Manager 全合一容器 | Tuwunel+MinIO+Higress+Element 共进程 | 调试与独立扩缩困难 |
| 任务路由"笨" | 关键词匹配 | 不如 LLM 推理分解灵活 |
| 无学习能力 | 每次查询从零开始 | 不会积累 nGQL 模板 |
| 单通道集成 | 仅 Matrix | 钉钉 / 飞书 / 企微未对接 |
| 双单点 | Manager + MinIO | HA 方案 Phase 2 才落地 |

---

## 十一、Phase 2 + Phase 3 路线

**Phase 2 业务能力扩展(~5 个月)**
- 权限 MCP Server 落地 + Cypher AST 权限注入中间件
- ERP T+1 ETL 管道(SeaTunnel + Great Expectations 三层校验)
- Milvus 引入:语义缓存 / 本体检索 / 用户长期记忆
- 大小模型分流:60% 简单查询走 GLM-4.7-Flash,集群缩 30-40%
- HA:Manager 多副本 + MinIO 多节点

**Phase 3 全面生产(~6 个月)**
- CDC 准实时(Debezium + Kafka),秒级风险预警
- 多模态融合:合同 PDF / 图纸 OCR 元数据入图
- 联邦查询:CRM / WMS / MES 走 MCP,不入图谱
- 国产化生产:GLM-5 744B MoE 私有部署在华为昇腾 910B(W4A8 量化)

---

## 十二、AI 原生研发 · AI 原生 ≠ AI 辅助

**AI 辅助** = 程序员是主角,AI 是工具
**AI 原生** = AI 是协作者,工程师是 Tech Lead,**整个仓库的形态是为 AI 协作优化的**

HoneyBadge 是后者 —— 从 Day 1 就是这么搭的

| 仓库里看得见的 AI 痕迹 | 作用 |
|---|---|
| `CLAUDE.md` | 项目级 Claude Code 指令(架构 + 命令 + Git 规则) |
| `prompts/ontology/*.md` | 12 份本体,**给 LLM 读** 而不是给人读 |
| `scripts/ralph/` | Ralph 自治循环:prompt.md + progress.txt + ralph.sh |
| `memory/MEMORY.md` | 跨会话长期记忆(HiClaw 陷阱、nGQL v3 语法、ECS 流程) |
| `openspec/changes/` | RFC 驱动的变更规格 |

---

## 十三、AI 原生研发 · 谁干了什么

**AI 主导(占工作量 70%+)**
nGQL 编写调试 · ETL 脚本 · 数据质量规则 · Vue 前端 · 单元/E2E 测试 · Dockerfile / k8s manifests · 文档 · bug 定位

**人主导(必须 Tech Lead 拍板)**
本体建模(深度业务理解) · NebulaGraph 调优(实际压测) · 企业 SSO 协调 · 欺诈规则设计(审计专业知识) · **架构选型**(Approach A → B 的弃用)

```text
Tech Lead: 拍板架构(Approach B、5 层框架、AST 注入)
        ↓
Claude/Ralph: 实现 80% 代码 + 写测试 + 写文档
        ↓
人类: review、踩坑、把陷阱写回 MEMORY.md
        ↓
下次会话 AI 自动避坑 → 复利效应
```

---

## 十四、AI 原生研发 · 六条心得

1. **写指令的能力 = 新生产力**:CLAUDE.md / SOUL.md / SKILL.md 是新的"代码"
2. **记忆系统是必须的**:没有 MEMORY.md,AI 每次会话都要重新踩同一个坑(HiClaw `aigw-local` blackhole 我们踩了 4 次)
3. **本体即 Prompt**:把领域知识做成 LLM 可索引的 markdown,是比 RAG 简单一个数量级的解
4. **强制 PR 工作流**:禁止 push master + 强制 feature 分支 + CRLF 钩子,AI 才不会把 master 搞炸
5. **三层防御 = AI 协作的护栏**:editor → editorconfig → pre-commit hook,每层都假定上一层失败
6. **5 层防幻觉 ≈ 给 AI 戴枷锁**:让 LLM 在你能控制的边界里发挥,而不是放任"创造"

> **一个人 + 一群 Claude,做到过去 5-6 人小队的工作量**

---

<!-- _class: lead -->

## 结语 · HoneyBadge 想证明三件事

1. **金融级 LLM 应用是可能的** —— 只要把"翻译"和"回答"分开
2. **企业知识图谱不需要重新发明轮子** —— NebulaGraph + HiClaw + MCP 已经够用
3. **AI 原生研发不是口号** —— 本仓库的每一行代码都在实践这件事

GitHub: **xiaohanarch/HoneyBadge** · Apache 2.0 全栈
等你来用 · 来挑战 · 来 PR
