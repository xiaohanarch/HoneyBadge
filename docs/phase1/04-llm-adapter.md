# LLM 适配层

> 版本：v1.0
> 创建日期：2026-04-04
> 依赖：`02-hiclaw-orchestration.md`, `10-ontology.md`

---

## 1. 统一接口抽象

所有 LLM 调用通过 OpenAI 兼容 API 格式统一封装，支持无缝切换。

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

@dataclass
class LLMRequest:
    messages: list[dict]           # [{"role": "system", "content": "..."}, ...]
    model: str | None = None       # 指定模型，None 则使用默认
    temperature: float = 0.1       # 低温度保证确定性
    max_tokens: int = 4096
    stream: bool = False
    trace_id: str | None = None

@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str             # stop / length / error
    latency_ms: int

class LLMAdapter(ABC):
    """LLM 适配器统一接口。"""

    @abstractmethod
    async def chat(self, request: LLMRequest) -> LLMResponse:
        """同步调用。"""
        ...

    @abstractmethod
    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """流式调用（逐 token 输出）。"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查。"""
        ...
```

### 1.1 OpenAI 兼容实现

```python
import httpx

class OpenAICompatibleAdapter(LLMAdapter):
    """
    支持所有 OpenAI 兼容 API 的通用适配器。
    通义千问、GLM API、GPT-4o mini 都使用此适配器。
    """

    def __init__(self, config: dict):
        self.endpoint = config["endpoint"]       # API base URL
        self.api_key = config["api_key"]
        self.default_model = config["model"]
        self.timeout = config.get("timeout", 60)
        self.client = httpx.AsyncClient(
            base_url=self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout
        )

    async def chat(self, request: LLMRequest) -> LLMResponse:
        start = time.monotonic()
        response = await self.client.post(
            "/v1/chat/completions",
            json={
                "model": request.model or self.default_model,
                "messages": request.messages,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "stream": False,
            }
        )
        response.raise_for_status()
        data = response.json()
        latency = int((time.monotonic() - start) * 1000)

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data["model"],
            prompt_tokens=data["usage"]["prompt_tokens"],
            completion_tokens=data["usage"]["completion_tokens"],
            total_tokens=data["usage"]["total_tokens"],
            finish_reason=data["choices"][0]["finish_reason"],
            latency_ms=latency,
        )

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        async with self.client.stream(
            "POST", "/v1/chat/completions",
            json={
                "model": request.model or self.default_model,
                "messages": request.messages,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "stream": True,
            }
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta:
                        yield delta["content"]

    async def health_check(self) -> bool:
        try:
            resp = await self.client.get("/v1/models")
            return resp.status_code == 200
        except Exception:
            return False
```

---

## 2. 云端 API 配置

### 2.1 通义千问 API

```yaml
llm_providers:
  qwen:
    name: "通义千问"
    adapter: openai_compatible
    endpoint: "https://dashscope.aliyuncs.com/compatible-mode"
    api_key: "${QWEN_API_KEY}"
    models:
      complex: "qwen-max"           # 复杂查询
      simple: "qwen-turbo"          # 简单查询
    rate_limit:
      rpm: 60                       # 每分钟请求数
      tpm: 100000                   # 每分钟 token 数
    timeout: 60
```

### 2.2 GLM API（智谱）

```yaml
  glm:
    name: "智谱 GLM"
    adapter: openai_compatible
    endpoint: "https://open.bigmodel.cn/api/paas/v4"
    api_key: "${GLM_API_KEY}"
    models:
      complex: "glm-4-plus"         # 复杂查询
      simple: "glm-4-flash"         # 简单查询
    rate_limit:
      rpm: 100
      tpm: 200000
    timeout: 60
```

### 2.3 GPT-4o mini（备选）

```yaml
  openai:
    name: "OpenAI"
    adapter: openai_compatible
    endpoint: "https://api.openai.com"
    api_key: "${OPENAI_API_KEY}"
    models:
      complex: "gpt-4o"
      simple: "gpt-4o-mini"
    rate_limit:
      rpm: 60
      tpm: 150000
    timeout: 60
```

### 2.4 自部署切换预留

```yaml
  # Phase 2/3: 自部署 GLM-5 (昇腾 910B)
  glm_local:
    name: "GLM-5 本地部署"
    adapter: openai_compatible
    endpoint: "http://llm-inference.internal:8000"  # vLLM-Ascend / MindIE
    api_key: "local-token"                          # 内部 token
    models:
      complex: "glm-5"
      simple: "glm-4.7-flash"
    rate_limit:
      rpm: 300                                      # 本地无限制
      tpm: 500000
    timeout: 30                                     # 本地延迟更低
```

**切换方式**：修改环境变量 `LLM_PROVIDER` 即可，接口不变。

---

## 3. Provider 管理与路由

```python
class LLMProviderManager:
    """管理多个 LLM Provider，支持路由和降级。"""

    def __init__(self, config: dict):
        self.providers = {}
        self.primary_provider = config["primary"]
        self.fallback_provider = config.get("fallback")

        for name, provider_config in config["providers"].items():
            self.providers[name] = OpenAICompatibleAdapter(provider_config)

    async def chat(self, request: LLMRequest, query_complexity: str = "complex") -> LLMResponse:
        """
        根据查询复杂度选择模型，支持降级。

        query_complexity: "complex" | "simple"
        """
        provider = self.providers[self.primary_provider]

        # 选择模型
        model = provider.config["models"][query_complexity]
        request.model = model

        try:
            return await provider.chat(request)
        except Exception as e:
            logger.error(f"Primary LLM failed: {e}")
            if self.fallback_provider:
                fallback = self.providers[self.fallback_provider]
                request.model = fallback.config["models"][query_complexity]
                return await fallback.chat(request)
            raise
```

---

## 4. Prompt 模板管理

### 4.1 模板结构

```
prompts/
├── cypher_system.md          # nGQL 生成系统指令
├── cypher_constraints.md     # nGQL 语法约束（NebulaGraph 特有）
├── schema_erp_graph.md       # 当前 Schema 信息
├── ontology_full.md          # 完整本体（Phase 1 全量注入）
├── summarize_system.md       # 结果摘要系统指令
└── error_correction.md       # 校验失败后的纠错指令
```

### 4.2 cypher_system.md（nGQL 生成系统指令）

```markdown
# 角色

你是一个 NebulaGraph 数据库查询专家。你的唯一任务是将用户的自然语言问题
转换为正确的 nGQL (NebulaGraph Query Language) 查询语句。

# 严格规则

1. **只生成 nGQL 查询**，不要回答问题，不要解释，不要猜测数据
2. **只使用 READ 操作**：MATCH, LOOKUP, GO, FETCH, FIND PATH
3. **禁止 WRITE 操作**：INSERT, UPDATE, UPSERT, DELETE, DROP, CREATE, ALTER
4. **每个查询必须有 LIMIT**（默认 LIMIT 100，除非用户指定数量或使用聚合函数）
5. **遍历深度不超过 5 跳**
6. **属性访问必须带 Tag 前缀**：`n.TagName.property_name`
7. **使用双等号 `==` 做比较**，单等号 `=` 是赋值
8. **字符串值使用双引号**

# 输出格式

只输出 nGQL 查询语句，不要添加任何解释文字。
如果用户问题无法转换为查询，输出：`-- CANNOT_QUERY: {原因}`
```

### 4.3 cypher_constraints.md（NebulaGraph 特有约束）

```markdown
# NebulaGraph nGQL 语法约束

## 关键差异（与 Neo4j Cypher 不同）

1. 属性访问: `n.Supplier.supplier_name`（不是 `n.supplier_name`）
2. 比较运算符: `==`（不是 `=`）
3. 分页: `LIMIT 10 OFFSET 5`（不是 `SKIP 5 LIMIT 10`）
4. 不支持 MERGE（用 UPSERT 替代，但这里只做读查询）
5. 最短路径: `FIND SHORTEST PATH FROM "vid1" TO "vid2" OVER * BIDIRECT UPTO 5 STEPS`
6. 标签函数: `tags(n)`（不是 `labels(n)`）

## 可用函数

- 聚合: count(), sum(), avg(), min(), max(), collect()
- 字符串: lower(), upper(), trim(), left(), right(), length()
- 数学: abs(), ceil(), floor(), round(), sqrt()
- 日期: now(), date(), time(), datetime(), datetime_diff()
- 类型: toInteger(), toFloat(), toString(), toBoolean()
- 列表: size(), range(), head(), tail(), reduce()

## NULL 处理

- `IS NULL` / `IS NOT NULL` 需加 Tag 前缀:
  `WHERE n.Supplier.contact_email IS NOT NULL`
```

### 4.4 summarize_system.md（结果摘要指令）

```markdown
# 角色

你是一个 ERP 数据分析助手。你的任务是将数据库查询结果用通俗的中文总结。

# 严格规则

1. **不要修改任何数值**（金额、数量、日期等必须与原始数据完全一致）
2. **不要补充数据库中没有的信息**
3. **不要推测或猜测任何结论**
4. 如果数据为空，直接说明"未查询到符合条件的数据"
5. 使用中文回答
6. 保持简洁明了，突出关键信息
7. 对于表格数据，使用清晰的列表或表格格式

# 输出格式

以自然语言方式总结查询结果，突出关键发现。
如果发现异常数据（如三单不匹配、金额异常），明确标注。
```

### 4.5 从 Phase 0 迁移

| Phase 0 模板 | Phase 1 变更 | 说明 |
|--------------|-------------|------|
| cypher_system.md | 更新为 nGQL 语法规则 | Cypher → nGQL |
| schema_erp_graph.md | 基于 `01-nebula-schema.md` 重写 | Neo4j labels → NebulaGraph Tags |
| 本体 Markdown | 基于 `10-ontology.md` 重写 | 查询示例改为 nGQL |
| summarize_system.md | 基本不变 | 增加"不修改数值"约束 |

---

## 5. Token 计量与限流

### 5.1 基础计量

```python
class TokenMeter:
    """Token 使用量计量与记录。"""

    def __init__(self, redis_client):
        self.redis = redis_client

    async def record(self, user_id: str, model: str, tokens: int):
        """记录 token 消耗。"""
        date = datetime.now().strftime("%Y%m%d")

        # 用户日消耗
        key = f"token_usage:{user_id}:{date}"
        await self.redis.incrby(key, tokens)
        await self.redis.expire(key, 86400 * 7)  # 保留 7 天

        # 全局日消耗
        global_key = f"token_usage:global:{date}"
        await self.redis.incrby(global_key, tokens)
        await self.redis.expire(global_key, 86400 * 30)

        # Prometheus 指标
        token_counter.labels(model=model, user=user_id).inc(tokens)

    async def get_usage(self, user_id: str, date: str = None) -> int:
        """查询用户当日消耗。"""
        date = date or datetime.now().strftime("%Y%m%d")
        key = f"token_usage:{user_id}:{date}"
        return int(await self.redis.get(key) or 0)
```

### 5.2 基础限流

```python
class TokenRateLimiter:
    """
    Phase 1 基础限流：按用户每日 token 上限。
    Phase 2 将扩展为按部门/组织配额管理。
    """

    DEFAULT_DAILY_LIMIT = 500_000  # 每用户每日 50 万 tokens

    async def check_limit(self, user_id: str) -> bool:
        usage = await self.meter.get_usage(user_id)
        return usage < self.DEFAULT_DAILY_LIMIT

    async def on_request(self, user_id: str) -> None:
        if not await self.check_limit(user_id):
            raise RateLimitExceeded(
                f"Daily token limit exceeded for user {user_id}"
            )
```

---

## 6. 错误处理与降级策略

### 6.1 降级链

```
Primary Provider (通义千问/GLM)
    │ 失败
    ▼
Fallback Provider (GPT-4o mini)
    │ 失败
    ▼
返回错误消息: "AI 服务暂时不可用，请稍后重试"
```

### 6.2 错误分类

| 错误类型 | HTTP 状态 | 处理 |
|---------|----------|------|
| 429 Rate Limit | 429 | 等待 retry-after 后重试 1 次 |
| 500 Server Error | 500 | 切换到 fallback provider |
| 401 Auth Error | 401 | 记录告警，返回配置错误 |
| Timeout | - | 切换到 fallback provider |
| Content Filter | 400 | 记录日志，返回"无法处理该查询" |
| Token Limit | 400 | 裁剪 Prompt（减少本体信息），重试 |

### 6.3 超时配置

| 场景 | 超时时间 | 说明 |
|------|---------|------|
| nGQL 生成 | 30s | 单次 LLM 调用 |
| 结果摘要 | 30s | 单次 LLM 调用 |
| 流式响应首 token | 10s | 超时则降级到同步 |
| 端到端 | 120s | 包含重试在内的总超时 |
