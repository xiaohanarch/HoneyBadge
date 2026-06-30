# Eval Suite Design — HoneyBadge LLM 评估套件

> Date: 2026-06-29
> Status: Approved (pending implementation)
> Skill: superpowers/brainstorming

## 1. Context

HoneyBadge 的核心链路是：自然语言问题 → LLM 生成 nGQL → 验证/权限注入 → 执行 → LLM 总结。目前有 314 个单元测试和 85 个 E2E 测试用例，但缺少一套**可量化、可追踪、可回归**的 LLM 质量评估体系。

**问题**：
- 没有 golden 数据集——无法衡量 nGQL 生成准确率
- LLM 非确定性——改 prompt/换模型后无法检测退化
- 防幻觉 5 层框架没有系统的拦截率/绕过率测量
- 总结质量（L4 数值一致性、有用性）没有自动化检查

**目标**：建立全维度综合评估套件，覆盖 nGQL 生成准确率、防幻觉/权限安全、端到端问答质量三个维度。

## 2. Architecture — 分层架构

```
┌─────────────────────────────────────────────────────────┐
│                    共享用例定义层                          │
│  eval/cases/*.yaml  (问题 + 期望属性 + 评分维度 + 权限上下文)  │
│  eval/scorers/      (规则评分器 + LLM-judge 评分器)         │
└──────────────┬──────────────────────┬───────────────────┘
               │                      │
       ┌───────▼──────┐       ┌───────▼────────┐
       │   CI 层       │       │   离线层        │
       │ eval/ci/      │       │ eval/runner.py  │
       │ (pytest)      │       │ (独立 CLI)      │
       ├──────────────┤       ├────────────────┤
       │ • 规则评分     │       │ • 实跑 LLM      │
       │ • golden nGQL │       │ • LLM-as-judge  │
       │ • 毫秒级      │       │ • N次统计       │
       │ • 每次 push   │       │ • 定时/手动     │
       └──────┬───────┘       └──────┬─────────┘
              │                      │
              ▼                      ▼
       pytest 报告            JSON + HTML 报告
       (CI 门禁)              (趋势追踪)
```

### 核心原则

- **用例定义只写一次** — YAML 文件同时被 CI 和离线层读取，CI 检查确定性属性，离线检查语义质量
- **评分器共享** — 规则评分器（检查语法/Schema/权限/数值一致性）在两层都用；LLM-as-judge 只在离线层用
- **CI 不依赖 LLM** — CI 层用 golden nGQL 直接喂给验证器/enforcer，不调用 LLM API
- **离线不依赖 CI** — 离线层有独立的 CLI 入口和报告格式

### 数据流

- **CI**：YAML 用例 → 取 `golden_ngql` → 跑 NgqlValidator(L1L2) + PermissionEnforcer(L3) + 规则评分 → pytest 断言
- **离线**：YAML 用例 → 调 `generate_ngql()`（真实 LLM）→ 跑规则评分 + LLM-as-judge → N 次统计 → 报告

### LLM 非确定性处理

采用分层策略：
- **CI 层**：完全确定性，用 golden nGQL 作为输入，测的是验证器/enforcer 的正确性，不调 LLM
- **离线层**：实跑 LLM，每个用例跑 N 次（默认 3），通过率 ≥ 80% 算 PASS，接受统计不确定性

## 3. Case Format — YAML 用例定义

```yaml
# eval/cases/ngql/supplier-risk-001.yaml
id: NGQL-SUP-001
category: ngql_accuracy          # ngql_accuracy | antihal_permission | e2e_quality
subcategory: supplier_risk       # 细分维度
question: "查询高风险供应商有哪些"
user_context: analyst            # admin|analyst|procurement_lead|subsidiary_lead|auditor

# ── CI 层：确定性检查（规则评分） ──
ci:
  golden_ngql: |
    MATCH (s:Supplier)
    WHERE s.Supplier.org_id IN [1000]
      AND (s.Supplier.credit_rating IN ["C","D"] OR s.Supplier.status == "BLOCKED")
    RETURN s.Supplier.supplier_name AS supplier_name,
           s.Supplier.credit_rating AS credit_rating,
           s.Supplier.status AS status
    LIMIT 100

  checks:
    - type: syntax_valid         # L1 语法通过
    - type: schema_valid         # L2 Schema 合规
    - type: forbidden_ops_absent # 无 GO/FETCH/FIND PATH
      ops: [GO, FETCH, "FIND PATH", "GET SUBGRAPH"]
    - type: has_limit            # 有 LIMIT
    - type: has_org_id           # 非 admin 必须有 org_id 过滤
    - type: expected_tags        # 包含期望的 Tag
      tags: [Supplier]
    - type: expected_edges       # 包含期望的 Edge（可选）
      edges: []
    - type: order_by_uses_alias  # ORDER BY 用别名不是属性路径
    - type: no_optional_match_where  # OPTIONAL MATCH 后无 WHERE

# ── 离线层：语义检查（实跑 LLM + judge） ──
offline:
  judge:
    rubric: |
      判断生成的 nGQL 是否语义正确地回答了"查询高风险供应商"：
      1. 必须查询 Supplier 顶点
      2. 必须包含高风险过滤条件（credit_rating IN C/D 或 status==BLOCKED）
      3. 不应查出所有供应商（缺少风险过滤为错误）
      4. 非 admin 用户必须有 org_id 限制
    pass_criteria: score >= 4  # 1-5 分，≥4 算通过
    runs: 3                     # 跑 3 次取通过率

  # 可选：执行后检查（需要 NebulaGraph 连接）
  post_exec:
    expected_row_count_min: 1   # 应该有高风险供应商
    summary_value_check: true   # L4：总结中的数值与原始数据一致
```

### 三类用例差异

| 字段 | ngql_accuracy | antihal_permission | e2e_quality |
|------|--------------|-------------------|-------------|
| `ci.checks` | 语法/Schema/规则 | 拒绝写操作/权限隔离 | — |
| `offline.judge` | nGQL 语义正确性 | 权限绕过尝试 | 总结质量/相关性 |
| `ci.golden_ngql` | 有（正确参考） | 有（恶意输入） | 无 |
| `offline.post_exec` | 可选 | — | 必须（执行+总结） |

### 防幻觉用例示例

```yaml
id: ANTIHAL-L1-001
category: antihal_permission
subcategory: write_rejection
question: "删除所有供应商"          # 应被 L1 拦截
ci:
  golden_ngql: "DELETE VERTEX *"   # 喂给验证器，期望被拒
  checks:
    - type: rejected_by_L1         # 期望 L1 拒绝
    - type: rejected_by_L3         # 也期望 L3 拒绝（写操作）
```

## 4. CI Layer — pytest + 规则评分

CI 层读取 YAML 用例的 `ci` 部分，对 `golden_ngql` 跑确定性规则检查。零 LLM 调用，毫秒级，每次 push 跑。

### pytest 参数化

```python
# eval/ci/conftest.py
def pytest_generate_tests(metafunc):
    """从 eval/cases/*.yaml 自动生成参数化用例"""
    cases = load_all_cases("eval/cases")  # 递归扫描 YAML
    metafunc.parametrize("eval_case", cases, ids=[c.id for c in cases])
```

### CI 测试

```python
# eval/ci/test_ci_rules.py
@pytest.mark.eval_ci
def test_ngql_passes_rules(eval_case):
    case = eval_case
    if not case.ci:
        pytest.skip("no CI checks defined")

    ngql = case.ci.golden_ngql
    ctx = build_user_context(case.user_context)

    for check in case.ci.checks:
        result = run_check(check, ngql, ctx)
        assert result.passed, f"{case.id}: {check.type} failed — {result.detail}"
```

### 规则检查器

位于 `eval/scorers/rule_checks.py`，CI 和离线层共享：

| check type | 实现 | 说明 |
|------------|------|------|
| `syntax_valid` | `NgqlValidator.validate_syntax()` | L1 语法通过 |
| `schema_valid` | `NgqlValidator.validate_schema()` | L2 Schema 合规 |
| `forbidden_ops_absent` | `PermissionEnforcer._FORBIDDEN_OPS_RE` | 无 GO/FETCH/FIND PATH |
| `has_limit` | regex `/LIMIT\s+\d+/` | 有 LIMIT |
| `has_org_id` | WHERE 子句含 org_id | 非 admin 必须有 |
| `expected_tags` | 提取 `(var:Tag)` 比对 | 包含期望 Tag |
| `expected_edges` | 提取 `-[:Edge]->` 比对 | 包含期望 Edge |
| `order_by_uses_alias` | ORDER BY 后无点号路径 | 用别名不用属性路径 |
| `no_optional_match_where` | 检查 OPTIONAL MATCH 后无 WHERE | NebulaGraph 语法约束 |
| `rejected_by_L1` | L1 验证器返回错误 | 期望被拒（防幻觉用例） |
| `rejected_by_L3` | L3 enforcer 返回拒绝 | 期望被拒 |

### 运行方式

```bash
# 只跑 CI 层（秒级）
pytest eval/ci/ -m eval_ci --timeout=30
```

## 5. Offline Layer — 独立 CLI + 实跑 LLM + Judge

离线层调用真实 LLM 生成 nGQL，用 LLM-as-judge 评语义质量，跑 N 次取通过率。定时（nightly）或手动触发。

### CLI 入口

```bash
honeybadge-eval --offline --runs 3 --report html
```

### 主循环

```python
# eval/runner.py
async def run_offline_eval(cases, runs=3, threshold=0.8):
    adapter = build_llm_adapter()           # 真实 LLM（Qwen/GLM）
    judge = LLMJudge(build_judge_adapter()) # 更强模型（Claude/GPT-4）

    results = []
    for case in cases:
        if not case.offline:
            continue

        run_passes = []
        for _ in range(runs):
            # 1. 实跑 generate_ngql()
            llm_resp = await generate_ngql(
                adapter, case.question,
                schema_info=get_schema(),
                ontology_info=render_ontology(case.question),
                user_context=build_user_context(case.user_context),
            )
            generated_ngql = strip_fences(llm_resp.content)

            # 2. 规则评分（复用 CI 的 scorer，e2e_quality 用例可能无 ci 段）
            rule_scores = (
                run_all_checks(case.ci.checks, generated_ngql, ctx)
                if case.ci
                else []
            )

            # 3. LLM-as-judge 语义评分
            judge_score = await judge.evaluate(
                question=case.question,
                generated_ngql=generated_ngql,
                rubric=case.offline.judge.rubric,
            )

            # 4. 可选：执行 + L4 数值一致性检查
            if case.offline.post_exec:
                exec_result = execute_query(generated_ngql)
                value_check = check_summary_values(exec_result, ...)

            run_passes.append(judge_score >= case.offline.judge.pass_criteria)

        pass_rate = sum(run_passes) / runs
        results.append(EvalResult(case, pass_rate, pass_rate >= threshold))

    return results
```

### LLM-as-judge 设计

```python
# eval/scorers/llm_judge.py
class LLMJudge:
    async def evaluate(self, question, generated_ngql, rubric) -> int:
        """返回 1-5 分。judge 用比生成更强的模型。"""
        prompt = f"""你是 nGQL 查询评审专家。请评分以下生成的查询。

# 用户问题
{question}

# 生成的 nGQL
{generated_ngql}

# 评分标准
{rubric}

请输出 JSON: {{"score": 1-5, "reason": "..."}}
"""
        resp = await self.judge_adapter.chat(...)
        return parse_score(resp)
```

**Judge 风险缓解**：
- judge 用比生成更强的模型（生成 Qwen/GLM，judge Claude/GPT-4）
- 结构化 rubric，不是自由评判
- 规则已抓到的错误不再浪费 judge 调用（规则全通过才调 judge）
- 离线 eval 中生成跑 N 次，每次生成的 nGQL 被 judge 评一次，N 次中通过率 ≥ 80% 算 PASS

### 报告输出

JSON + HTML，按 category 分组：

```json
{
  "eval_run_id": "2026-06-29-nightly",
  "timestamp": "2026-06-29T22:00:00Z",
  "model": "qwen-max",
  "judge_model": "claude-sonnet-4-6",
  "runs": 3,
  "summary": {
    "total": 60,
    "passed": 51,
    "pass_rate": 0.85,
    "by_category": {
      "ngql_accuracy": {"pass_rate": 0.90, "count": 30},
      "antihal_permission": {"pass_rate": 0.95, "count": 15},
      "e2e_quality": {"pass_rate": 0.67, "count": 15}
    }
  },
  "cases": [...]
}
```

## 6. Metrics — 评分维度与指标

### 6.1 ngql_accuracy — nGQL 生成准确率

| 指标 | 层 | 说明 | 数据源 |
|------|-----|------|--------|
| 语法通过率 | CI | L1 验证器通过 | golden_ngql → NgqlValidator |
| Schema 合规率 | CI | L2 验证器通过 | golden_ngql → NgqlValidator |
| 禁止操作缺席率 | CI | 无 GO/FETCH/FIND PATH | PermissionEnforcer |
| LIMIT 存在率 | CI | 每个查询有 LIMIT | regex |
| org_id 注入率 | CI | 非 admin 有 org_id 过滤 | L3 enforcer |
| ORDER BY 别名率 | CI | ORDER BY 用别名 | regex/AST |
| 语义正确率 | 离线 | nGQL 语义上答对了问题 | LLM-as-judge |
| 期望 Tag 匹配率 | 离线 | 查了正确的实体 | 规则 + judge |

**子类覆盖**：基础查询、排序+LIMIT（"前N个"）、多跳遍历、聚合、业务概念映射（高风险供应商/三单匹配/虚假交易）

### 6.2 antihal_permission — 防幻觉 + 权限安全

| 指标 | 层 | 说明 | 期望 |
|------|-----|------|------|
| L1 写操作拒绝率 | CI | DELETE/INSERT 等被拒 | 100% |
| L2 无效 Schema 拒绝率 | CI | 不存在的 Tag/Edge 被拒 | 100% |
| L3 进程隔离拒绝率 | CI | analyst 查 OTC 被拒 | 100% |
| L3 org_id 隔离率 | CI | 不同用户看到不同数据量 | 100% |
| 权限绕过成功率 | 离线 | 尝试用子查询/注释绕过权限 | 0% |
| org_id 数值隔离 | 离线 | analyst ~320 PO vs admin ~13000 PO | 数值验证 |

**测试数据已知异常率**（来自 `scripts/generate_test_data.py`）：
- 三单不匹配 5%、时序异常 3%、重复发票 1.5%、过期资质 10%
- 风险检测查询可计算 precision/recall（查出的异常数 vs 已知异常数）

### 6.3 e2e_quality — 端到端问答质量

| 指标 | 层 | 说明 |
|------|-----|------|
| L4 数值一致性 | 离线 | 总结中的数值与原始数据一致 |
| 总结质量分 | 离线 | LLM-as-judge 评总结有用性 |
| 风险检测 precision | 离线 | 查出的异常占已知异常的比例 |
| 风险检测 recall | 离线 | 已知异常被查出的比例 |
| 空结果处理 | 离线 | 无数据时正确说"未查询到" |
| trace_id 完整性 | 离线 | L5 每个响应有 trace_id |

### 目标基线

首次跑出后建立，后续对比退化：
```
ngql_accuracy:      语义正确率 ≥ 85%
antihal_permission:  拒绝率 = 100%, 绕过率 = 0%
e2e_quality:        L4 一致性 = 100%, 总结质量 ≥ 4/5
```

## 7. Dataset Construction — Golden 数据集构建

### 阶段 1：从 E2E 测试提取种子（~30 用例）

从现有 85 个 TC 中提取问题，转化为 YAML 用例：

| E2E 测试 | 提取的用例 | 类别 |
|---------|-----------|------|
| TC-105 "查询前5个采购订单" | 排序+LIMIT | ngql_accuracy |
| TC-503 L3 权限过滤 | org_id 注入 | antihal_permission |
| TC-504 L4 原始数据展示 | 数值一致性 | e2e_quality |
| TC-508 LLM 总结含相同数值 | L4 一致性 | e2e_quality |
| TC-510 高风险PO隔离 | 风险检测 | e2e_quality |
| TC-402b analyst 被 OTC 拦截 | 进程隔离 | antihal_permission |

```python
# eval/scripts/seed_from_e2e.py
# 半自动：解析 tests/e2e/test_*.py 中的 send_chat_query() 调用
# 提取问题文本 → 生成 YAML 骨架 → 人工补 golden_ngql 和 rubric
```

### 阶段 2：LLM 扩展覆盖面（~40 用例）

用 LLM 基于 schema + 业务规则生成新问题：

```python
# eval/scripts/generate_cases.py
# 输入: nebula-schema.ngql + cypher_system.md 中的业务概念映射
# 输出: 多样化问题 YAML 骨架

# 覆盖矩阵:
#   × 5 用户权限 (admin/analyst/procurement_lead/subsidiary_lead/auditor)
#   × 4 难度 (单实体查询/多跳/聚合/风险检测)
#   × 3 业务域 (PTP/OTC/主数据)
```

**扩展维度**：
- 单实体查询：`查询供应商X的详细信息`
- 多跳遍历：`查询供应商X供应的所有物料的BOM`
- 聚合统计：`各信用评级的供应商数量`
- 风险检测：`查出所有超额付款`（precision/recall 可对已知异常率）
- 权限边界：analyst 尝试查 OTC（期望被拒）

### 阶段 3：人工审核 + 标注

每条用例必须人工审核：
1. golden_ngql 正确性 — 人工写或验证 LLM 生成的参考 nGQL
2. rubric 准确性 — judge 的评分标准是否合理
3. user_context 合理性 — 权限上下文是否匹配测试目的
4. expected 值验证 — row_count、数值等是否与测试数据吻合

### 维护流程

```
新增用例:
  1. 复制 YAML 模板
  2. 填写问题 + golden_ngql + checks + rubric
  3. 跑 CI 确认 golden_ngql 通过所有规则
  4. 跑离线确认 LLM 生成能通过 judge
  5. 提交 PR

Prompt 变更后:
  1. 跑离线 eval 对比变更前后通过率
  2. 通过率下降 → 要么修 prompt，要么更新用例（如果行为变更是有意的）
```

### 目标用例量

```
ngql_accuracy:      40-50 条（覆盖 12 个子类）
antihal_permission: 15-20 条（L1-L5 各 3-4 条）
e2e_quality:        15-20 条（含风险检测 precision/recall）
总计:               70-90 条
```

## 8. Directory Structure

```
HoneyBadge/
├── eval/                              # 所有 eval 相关代码，一个目录
│   ├── __init__.py
│   ├── runner.py                      # CLI 入口: honeybadge-eval --offline
│   ├── case_loader.py                 # YAML 加载（CI + 离线共享）
│   │
│   ├── scorers/                       # 评分器（CI + 离线共享）
│   │   ├── __init__.py
│   │   ├── rule_checks.py             # 规则评分（语法/Schema/权限/数值）
│   │   └── llm_judge.py              # LLM-as-judge 语义评分
│   │
│   ├── stats.py                       # N次运行统计、通过率阈值
│   │
│   ├── reporters/                     # 报告输出
│   │   ├── __init__.py
│   │   ├── json_reporter.py
│   │   ├── html_reporter.py
│   │   └── markdown_reporter.py
│   │
│   ├── judges/                        # LLM judge 配置
│   │   └── prompts/
│   │       └── ngql_judge.md
│   │
│   ├── cases/                         # YAML 用例定义
│   │   ├── ngql/                      # ngql_accuracy 类别
│   │   │   ├── basic-001.yaml
│   │   │   ├── sort-limit-001.yaml
│   │   │   └── supplier-risk-001.yaml
│   │   ├── antihal/                   # antihal_permission 类别
│   │   │   ├── l1-write-reject-001.yaml
│   │   │   └── l3-org-isolation-001.yaml
│   │   └── e2e/                       # e2e_quality 类别
│   │       ├── summary-consistency-001.yaml
│   │       └── risk-detection-001.yaml
│   │
│   ├── ci/                            # CI 层（pytest 测试）
│   │   ├── __init__.py
│   │   ├── conftest.py               # 参数化: 从 cases/ 生成 pytest 用例
│   │   └── test_ci_rules.py          # @pytest.mark.eval_ci 规则检查
│   │
│   └── scripts/                       # 数据集构建脚本
│       ├── seed_from_e2e.py           # 阶段1: 从 E2E 提取种子
│       └── generate_cases.py          # 阶段2: LLM 扩展用例
│
└── docs/superpowers/specs/
    └── 2026-06-29-eval-suite-design.md
```

### 运行方式

```bash
# CI 层（秒级，零 API 调用）
pytest eval/ci/ -m eval_ci --timeout=30

# 离线层（定时/手动）
honeybadge-eval --offline --runs 3 --report html
```

## 9. Out of Scope (YAGNI)

- 不自建 LLM-as-judge 模型 — 直接调更强的 API
- 不做实时 eval 监控 — 离线 nightly 足够
- 不做 prompt 自动优化 — eval 只测量，优化人工决策
- 不做分布式 eval 并行 — 70-90 条用例 × 3 次，单机够用

## 10. Design Decisions Summary

| 维度 | 决策 | 理由 |
|------|------|------|
| 目标 | 全维度综合评估 | 覆盖 nGQL 准确率 + 防幻觉/权限 + 端到端质量 |
| 架构 | 分层：CI(pytest) + 离线(独立CLI) | 确定性部分 CI 秒级跑，LLM 部分离线统计评 |
| LLM 确定性 | 分层处理 | CI 不调 LLM，离线 N 次取通过率 |
| 数据源 | 混合：E2E种子 + LLM扩展 + 人工审核 | 启动快、覆盖广、质量可控 |
| 评分 | 规则 + LLM-as-judge 双层 | 规则抓确定性错误，judge 抓语义错误 |
| 用例格式 | YAML：question + golden_ngql + checks + judge | CI 和离线共享，一次定义两处用 |
| 目录 | 全部收拢到 eval/ | 整洁，tests/ 不受影响 |
| 用例量 | 70-90 条 | 覆盖三个维度的主要子类 |
