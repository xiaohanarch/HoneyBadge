# 防幻觉框架 + 审计日志

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：`01-nebula-schema.md`, `02-hiclaw-orchestration.md`, `04-llm-adapter.md`

---

## 1. 核心原则

**LLM 只负责翻译（生成 nGQL），不负责回答。**

```
❌ 用户提问 → LLM 直接回答（会产生幻觉）
✅ 用户提问 → LLM 生成 nGQL → 执行 nGQL → 返回数据库真实结果
```

---

## 2. 五层防线详细实现

### 2.1 L1：nGQL 语法校验

**目标**：确保 LLM 生成的 nGQL 是合法语句。

**实现方案**：

```python
# 方案 A（推荐）：使用 NebulaGraph 的 EXPLAIN 语句
def validate_syntax(ngql: str) -> ValidationResult:
    """
    利用 NebulaGraph 的 EXPLAIN 做语法检查（不实际执行）。
    EXPLAIN 只做语法解析和计划生成，不访问数据。
    """
    try:
        result = nebula_client.execute(f"EXPLAIN {ngql}")
        if result.is_succeeded():
            return ValidationResult(valid=True)
        else:
            return ValidationResult(
                valid=False,
                error=result.error_msg(),
                layer="L1"
            )
    except Exception as e:
        return ValidationResult(valid=False, error=str(e), layer="L1")

# 方案 B（补充）：基础正则预检
def pre_validate(ngql: str) -> ValidationResult:
    """在发送到 NebulaGraph 前做快速预检。"""
    # 禁止写操作
    write_patterns = [
        r'\bINSERT\b', r'\bUPDATE\b', r'\bUPSERT\b',
        r'\bDELETE\b', r'\bDROP\b', r'\bCREATE\b', r'\bALTER\b'
    ]
    for pattern in write_patterns:
        if re.search(pattern, ngql, re.IGNORECASE):
            return ValidationResult(
                valid=False,
                error=f"Write operation detected: {pattern}",
                layer="L1"
            )

    # 限制遍历深度（防止全图扫描）
    depth_match = re.search(r'\*(\d+)\.\.(\d+)', ngql)
    if depth_match and int(depth_match.group(2)) > 5:
        return ValidationResult(
            valid=False,
            error="Traversal depth exceeds 5 hops",
            layer="L1"
        )

    # 必须有 LIMIT（防止返回过多数据）
    if 'LIMIT' not in ngql.upper() and 'COUNT' not in ngql.upper():
        return ValidationResult(
            valid=False,
            error="Query must include LIMIT clause",
            layer="L1"
        )

    return ValidationResult(valid=True)
```

### 2.2 L2：Schema 合规校验

**目标**：确保 nGQL 中引用的 Tag、Edge Type、Property 都真实存在于 NebulaGraph Schema 中。

**实现方案**：

```python
class SchemaValidator:
    def __init__(self, nebula_client):
        self.schema_cache = {}
        self.cache_ttl = 300  # 5 分钟缓存

    def load_schema(self) -> dict:
        """从 NebulaGraph Meta 动态获取 Schema。"""
        schema = {}

        # 获取所有 Tag
        tags_result = nebula_client.execute("SHOW TAGS")
        for tag_name in tags_result:
            props = nebula_client.execute(f"DESCRIBE TAG {tag_name}")
            schema[f"tag:{tag_name}"] = {
                "properties": [p.name for p in props]
            }

        # 获取所有 Edge Type
        edges_result = nebula_client.execute("SHOW EDGES")
        for edge_name in edges_result:
            props = nebula_client.execute(f"DESCRIBE EDGE {edge_name}")
            schema[f"edge:{edge_name}"] = {
                "properties": [p.name for p in props]
            }

        self.schema_cache = schema
        return schema

    def validate(self, ngql: str) -> ValidationResult:
        """
        解析 nGQL 中引用的 Tag/Edge/Property，
        与 Schema 缓存比对。
        """
        schema = self.load_schema_if_stale()
        errors = []

        # 提取 Tag 引用: (n:TagName) 或 vertex.TagName.property
        tag_refs = re.findall(r':(\w+)\b', ngql)
        for tag in tag_refs:
            if f"tag:{tag}" not in schema and f"edge:{tag}" not in schema:
                errors.append(f"Unknown Tag/Edge: {tag}")

        # 提取属性引用: n.TagName.property_name
        prop_refs = re.findall(r'\.(\w+)\.(\w+)', ngql)
        for tag, prop in prop_refs:
            key = f"tag:{tag}"
            if key in schema and prop not in schema[key]["properties"]:
                errors.append(f"Unknown property: {tag}.{prop}")

        if errors:
            return ValidationResult(
                valid=False,
                error="; ".join(errors),
                layer="L2"
            )
        return ValidationResult(valid=True)
```

### 2.3 L3：权限注入校验（Phase 1 预留）

**Phase 1 实现**：仅建立框架骨架，不实际注入权限条件。

```python
class PermissionValidator:
    """
    Phase 1: 校验框架就绪，但 check 方法始终返回 True。
    Phase 2: 对接权限 MCP Server，实际校验和注入。
    """

    def validate(self, ngql: str, user_context: dict) -> ValidationResult:
        # Phase 1: 预留框架，记录日志但不阻断
        if self._has_permission_filter(ngql):
            return ValidationResult(valid=True)

        # Phase 1: 仅记录 warning，不拒绝
        logger.warning(
            f"Query lacks permission filter. "
            f"User: {user_context.get('user_id')}, "
            f"Query: {ngql[:200]}"
        )
        return ValidationResult(valid=True, warnings=["No permission filter detected"])

        # Phase 2 将改为:
        # return ValidationResult(
        #     valid=False,
        #     error="Query must include org_id/dept_id filter",
        #     layer="L3"
        # )

    def _has_permission_filter(self, ngql: str) -> bool:
        """检查 nGQL 是否包含权限过滤条件。"""
        permission_fields = ['org_id', 'dept_id', 'data_scope']
        return any(field in ngql for field in permission_fields)

    def inject_permissions(self, ngql: str, user_context: dict) -> str:
        """
        Phase 2: AST 级权限注入。
        Phase 1: 直接返回原始 nGQL（不注入）。
        """
        # Phase 1: passthrough
        return ngql

        # Phase 2 将实现:
        # ast = parse_ngql(ngql)
        # for match_clause in ast.match_clauses:
        #     inject_where(match_clause, f"n.Tag.org_id == {user_context['org_id']}")
        # return ast.to_ngql()
```

### 2.4 L4：结果直传

**目标**：NebulaGraph 返回的原始数据直接展示给用户，LLM 只负责格式化/摘要。

**Prompt 约束**：

```
在调用 LLM 生成摘要时，Prompt 中明确指令：

---
请用自然语言总结以下查询结果。

严格要求：
1. 不要修改任何数值（金额、数量、日期等）
2. 不要补充数据库中没有的信息
3. 不要推测或猜测任何结论
4. 如果数据为空，直接说明"未查询到符合条件的数据"
5. 所有数字必须与原始数据完全一致

原始查询结果：
{raw_data_json}
---
```

**前端双展示**：

```
前端同时展示：
  1. AI 摘要（LLM 生成的自然语言总结）
  2. 原始数据表格（NebulaGraph 返回的 raw data）
  3. 执行的 nGQL 查询（透明可审计）
  4. trace_id（审计追溯 ID）

用户可交叉验证 AI 摘要与原始数据是否一致。
```

### 2.5 L5：全链路审计日志

**目标**：记录从用户提问到最终返回的完整链路，支持事后审计。

---

## 3. 执行流程时序图

```
用户         前端        Higress      Manager     Worker      LLM         NebulaGraph   PostgreSQL
 │            │            │            │           │           │              │             │
 │──问题──────>│            │            │           │           │              │             │
 │            │──WS消息────>│            │           │           │              │             │
 │            │            │──认证转发──>│           │           │              │             │
 │            │            │            │──分配任务─>│           │              │             │
 │            │            │            │           │           │              │             │
 │            │            │            │           │──生成trace_id            │             │
 │            │            │            │           │           │              │             │
 │            │  <───────── "正在生成查询..." ────────│           │              │             │
 │            │            │            │           │           │              │             │
 │            │            │            │           │──生成nGQL─>│              │             │
 │            │            │            │           │<──nGQL────│              │             │
 │            │            │            │           │           │              │             │
 │            │            │            │           │──L1:语法校验              │             │
 │            │            │            │           │──L2:Schema校验            │             │
 │            │            │            │           │──L3:权限校验(预留)        │             │
 │            │            │            │           │           │              │             │
 │            │            │            │           │  [校验失败? → 重试,最多3次]│             │
 │            │            │            │           │           │              │             │
 │            │            │            │           │──执行nGQL───────────────>│             │
 │            │            │            │           │<──原始结果──────────────│             │
 │            │            │            │           │           │              │             │
 │            │            │            │           │──生成摘要─>│              │             │
 │            │            │            │           │<──摘要────│              │             │
 │            │            │            │           │           │              │             │
 │            │            │            │           │──写审计日志───────────────────────────>│
 │            │            │            │           │           │              │             │
 │            │  <─────── {summary, raw_data, cypher, trace_id} │              │             │
 │<──────────│            │            │           │           │              │             │
```

---

## 4. Cypher 重试策略

```python
MAX_RETRIES = 3

async def generate_and_validate_ngql(question: str, context: dict) -> str:
    """生成 nGQL 并校验，失败重试。"""
    errors_history = []

    for attempt in range(1, MAX_RETRIES + 1):
        # 生成 nGQL（带历史错误反馈）
        ngql = await llm.generate_cypher(
            question=question,
            schema=schema_info,
            ontology=ontology_info,
            previous_errors=errors_history if errors_history else None
        )

        # L1: 预检
        result = pre_validate(ngql)
        if not result.valid:
            errors_history.append({"attempt": attempt, "error": result.error, "layer": "L1"})
            continue

        # L1: 语法校验
        result = validate_syntax(ngql)
        if not result.valid:
            errors_history.append({"attempt": attempt, "error": result.error, "layer": "L1"})
            continue

        # L2: Schema 校验
        result = schema_validator.validate(ngql)
        if not result.valid:
            errors_history.append({"attempt": attempt, "error": result.error, "layer": "L2"})
            continue

        # L3: 权限校验
        result = permission_validator.validate(ngql, context)
        if not result.valid:
            errors_history.append({"attempt": attempt, "error": result.error, "layer": "L3"})
            continue

        return ngql

    # 所有重试失败
    raise CypherGenerationError(
        f"Failed to generate valid nGQL after {MAX_RETRIES} attempts",
        errors=errors_history
    )
```

**重试时的 Prompt 增强**：

```
当校验失败需要重试时，将错误信息追加到 Prompt：

---
你之前生成的 nGQL 有以下错误，请修正后重新生成：

第 1 次尝试错误 (L2-Schema校验失败):
  Unknown property: PurchaseOrder.supplier_name
  说明: PurchaseOrder 没有 supplier_name 属性，供应商名称在 Supplier Tag 上。
  请通过 PLACED_WITH 边关联 Supplier 来获取。

请重新生成正确的 nGQL：
---
```

---

## 5. 审计日志 PostgreSQL 表设计

### 5.1 主审计表

```sql
CREATE TABLE audit_query_log (
  id              BIGSERIAL PRIMARY KEY,
  trace_id        VARCHAR(64) NOT NULL UNIQUE,
  user_id         VARCHAR(64) NOT NULL,
  session_id      VARCHAR(64),
  -- 输入
  user_question   TEXT NOT NULL,
  -- 生成
  generated_ngql  TEXT,
  ngql_attempts   INT DEFAULT 1,         -- 重试次数
  validation_errors JSONB,               -- 校验失败历史
  -- 执行
  execution_time_ms INT,                 -- nGQL 执行耗时
  result_row_count  INT,                 -- 返回行数
  raw_result      JSONB,                 -- 原始查询结果
  -- 摘要
  llm_summary     TEXT,
  -- 元数据
  llm_model       VARCHAR(64),           -- 使用的模型
  total_tokens    INT,                   -- 总 token 消耗
  prompt_tokens   INT,
  completion_tokens INT,
  total_time_ms   INT,                   -- 端到端耗时
  -- 状态
  status          VARCHAR(20) NOT NULL,  -- success / validation_failed / execution_error / timeout
  error_message   TEXT,
  -- 权限（Phase 2）
  org_id          BIGINT,
  dept_id         BIGINT,
  -- 时间戳
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_audit_trace ON audit_query_log(trace_id);
CREATE INDEX idx_audit_user ON audit_query_log(user_id, created_at DESC);
CREATE INDEX idx_audit_created ON audit_query_log(created_at DESC);
CREATE INDEX idx_audit_status ON audit_query_log(status, created_at DESC);
```

### 5.2 trace_id 生成规则

```
格式: TRC-{YYYYMMDD}-{序列号}
示例: TRC-20260404-00147

生成方式:
  日期部分: 当天日期
  序列号: Redis INCR 计数器 trace_seq:{date}，TTL 48 小时

Python 实现:
  def generate_trace_id() -> str:
      date_str = datetime.now().strftime("%Y%m%d")
      seq = redis.incr(f"trace_seq:{date_str}")
      redis.expire(f"trace_seq:{date_str}", 172800)  # 48h
      return f"TRC-{date_str}-{seq:05d}"
```

### 5.3 数据保留策略

| 数据类型 | 保留期 | 处理方式 |
|---------|--------|---------|
| 审计日志完整记录 | 36 个月 | 保留在 PostgreSQL |
| raw_result（原始数据） | 6 个月 | 6 个月后置空（保留其他字段） |
| 归档记录 | 36 个月后 | 导出到冷存储（MinIO/S3），从 PG 删除 |

```sql
-- 每月 1 日执行：清理 raw_result
UPDATE audit_query_log
SET raw_result = NULL
WHERE created_at < NOW() - INTERVAL '6 months'
  AND raw_result IS NOT NULL;

-- 每季度执行：归档超期数据
-- (通过 ETL 脚本导出到 MinIO 后删除)
```

---

## 6. 校验指标监控

```python
# Prometheus 指标
from prometheus_client import Counter, Histogram

validation_total = Counter(
    'honeybadge_validation_total',
    'Total validation attempts',
    ['layer', 'result']  # layer: L1/L2/L3, result: pass/fail
)

validation_retry_total = Counter(
    'honeybadge_validation_retry_total',
    'Total nGQL generation retries',
    ['final_result']  # success / exhausted
)

query_duration = Histogram(
    'honeybadge_query_duration_seconds',
    'End-to-end query duration',
    ['status'],  # success / error
    buckets=[1, 2, 5, 10, 15, 30, 60]
)
```

---

## 6. 防幻觉框架的自动化评估（Eval Suite）

防幻觉框架的正确性本身需要被验证。Eval Suite（`eval/` 目录）对 L1-L3 各层提供自动化测试：

| 评估层 | 运行时机 | 验证内容 | 对应防线 |
|--------|---------|---------|---------|
| CI 层 | 每次 PR | 黄金 nGQL 通过 `forbidden_ops_absent` 检查 | L1 语法 |
| CI 层 | 每次 PR | `rejected_by_L1` 检测写操作被拒绝 | L1 写操作检测 |
| CI 层 | 每次 PR | `has_org_id` 验证非管理员查询包含组织过滤 | L3 权限隔离 |
| CI 层 | 每次 PR | `rejected_by_L3` 验证禁止的查询类型被拒绝 | L3 进程 ACL |
| Offline 层 | 手动/定期 | LLM 生成的 nGQL 在 N 次运行中的通过率 | 全链路 |

详见 README §6.4 与设计文档 `docs/superpowers/specs/2026-06-29-eval-suite-design.md`。
