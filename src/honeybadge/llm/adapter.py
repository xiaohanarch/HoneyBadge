"""LLM adapter implementation for HoneyBadge.

Provides LLMRequest/LLMResponse dataclasses, abstract LLMAdapter base class,
OpenAI-compatible adapter with httpx, token metering, and rate limiting.
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import httpx
import structlog

from honeybadge.core.exceptions import (
    LLMError,
    LLMGenerationError,
    LLMSummarizationError,
    LLMTimeoutError,
    RateLimitExceeded,
)

logger = structlog.get_logger()


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class LLMRequest:
    """
    Request payload for LLM chat completion.

    Attributes:
        messages: List of message dicts with "role" and "content" keys.
                  Example: [{"role": "system", "content": "..."}, ...]
        model: Optional model identifier. If None, uses adapter default.
        temperature: Sampling temperature (0.0-2.0). Lower values are more
            deterministic. Default 0.1 for consistent nGQL generation.
        max_tokens: Maximum tokens in completion. Default 4096.
        stream: Whether to use streaming. Default False.
        trace_id: Optional trace ID for audit logging.
        user_id: Optional user ID for token metering.
    """

    messages: list[dict[str, str]]
    model: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 4096
    stream: bool = False
    trace_id: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class LLMResponse:
    """
    Response from LLM chat completion.

    Attributes:
        content: The generated text content.
        model: Model that generated the response.
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the completion.
        total_tokens: Total tokens used (prompt + completion).
        finish_reason: Why generation stopped (stop/length/error).
        latency_ms: Request latency in milliseconds.
    """

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str
    latency_ms: int


# =============================================================================
# Abstract Adapter
# =============================================================================


class LLMAdapter(ABC):
    """
    Abstract base class for LLM adapters.

    All LLM implementations must provide chat(), chat_stream(), and health_check()
    methods. This enables seamless switching between providers (Qwen, GLM, GPT).
    """

    @abstractmethod
    async def chat(self, request: LLMRequest) -> LLMResponse:
        """
        Synchronous chat completion.

        Args:
            request: LLMRequest with messages and options.

        Returns:
            LLMResponse with generated content and metadata.

        Raises:
            LLMError: On generation failure.
            LLMTimeoutError: On timeout.
            RateLimitExceeded: On rate limit.
        """
        ...

    @abstractmethod
    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """
        Streaming chat completion.

        Args:
            request: LLMRequest with messages and options.

        Yields:
            String chunks of the generated content.

        Raises:
            LLMError: On generation failure.
            LLMTimeoutError: On timeout.
            RateLimitExceeded: On rate limit.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the LLM provider is available.

        Returns:
            True if healthy, False otherwise.
        """
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Get the default model identifier."""
        ...


# =============================================================================
# OpenAI-Compatible Adapter
# =============================================================================


class OpenAICompatibleAdapter(LLMAdapter):
    """
    OpenAI-compatible LLM adapter.

    Supports Qwen (Tongyi Qianwen), GLM (Zhipu), GPT-4o mini, and any other
    API that follows the OpenAI chat completion interface.

    Configuration example:
        {
            "endpoint": "https://dashscope.aliyuncs.com/compatible-mode",
            "api_key": "${QWEN_API_KEY}",
            "model": "qwen-turbo",
            "timeout": 60,
            "rate_limit": {
                "rpm": 60,      # requests per minute
                "tpm": 100000,  # tokens per minute
            }
        }
    """

    def __init__(
        self,
        config: dict[str, Any],
        redis_client: Optional[Any] = None,
    ) -> None:
        """
        Initialize OpenAI-compatible adapter.

        Args:
            config: Provider configuration dict with keys:
                - endpoint: API base URL
                - api_key: API key (supports ${ENV_VAR} syntax)
                - model: Default model identifier
                - timeout: Request timeout in seconds (default 60)
                - rate_limit: Optional dict with rpm/tpm limits
            redis_client: Optional Redis client for token metering.
        """
        self.endpoint = config["endpoint"]
        self.api_key = self._resolve_env_var(config["api_key"])
        self.default_model_name = config["model"]
        self.timeout = config.get("timeout", 60)
        self.rate_limit = config.get("rate_limit", {})

        self._redis_client = redis_client
        self._client: Optional[httpx.AsyncClient] = None

        # Token meter (initialized later with Redis client if available)
        self._token_meter: Optional[TokenMeter] = None
        if redis_client:
            self._token_meter = TokenMeter(redis_client)

        # Rate limiter
        self._rate_limiter: Optional[TokenRateLimiter] = None
        if self.rate_limit and redis_client:
            self._rate_limiter = TokenRateLimiter(
                redis_client,
                daily_token_limit=500_000,  # 50万 tokens per user per day
            )

        logger.info(
            "llm_adapter_initialized",
            endpoint=self.endpoint,
            model=self.default_model_name,
            timeout=self.timeout,
        )

    @staticmethod
    def _resolve_env_var(value: str) -> str:
        """
        Resolve environment variable references in config values.

        Supports ${ENV_VAR} and ${ENV_VAR:-default} syntax.

        Args:
            value: String that may contain env var references.

        Returns:
            Resolved string with env vars expanded.
        """
        import os

        if not isinstance(value, str):
            return value

        # Handle ${VAR:-default} syntax
        if value.startswith("${") and value.endswith("}"):
            inner = value[2:-1]
            if ":-" in inner:
                var_name, default = inner.split(":-", 1)
                return os.environ.get(var_name, default)
            else:
                return os.environ.get(inner, value)

        return value

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            # Normalize endpoint: strip trailing /v1 so that paths like
            # "/v1/chat/completions" don't produce a doubled /v1/v1/ with httpx.
            # httpx appends request paths to the base_url path, so if base_url
            # already ends with /v1, we strip it and let the request path carry it.
            endpoint = self.endpoint.rstrip("/")
            if endpoint.endswith("/v1"):
                endpoint = endpoint[:-3]
            self._client = httpx.AsyncClient(
                base_url=endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("llm_adapter_closed", endpoint=self.endpoint)

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """
        Execute synchronous chat completion with retry on rate limit (429/529).

        Args:
            request: LLMRequest with messages and options.

        Returns:
            LLMResponse with generated content.

        Raises:
            LLMError: On generation failure.
            LLMTimeoutError: On timeout.
            RateLimitExceeded: On rate limit (after exhausting retries).
        """
        max_retries = 3
        retry_delay = 3.0  # seconds between retries for 429/529
        for attempt in range(max_retries + 1):
            try:
                return await self._chat_once(request)
            except RateLimitExceeded:
                if attempt >= max_retries:
                    raise
                logger.warning(
                    "llm_rate_limit_retry",
                    attempt=attempt + 1,
                    delay=retry_delay,
                    trace_id=request.trace_id,
                )
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # exponential back-off

        raise RateLimitExceeded("LLM rate limit exceeded after retries")

    async def _chat_once(self, request: LLMRequest) -> LLMResponse:
        """Single chat attempt — called by chat() with retry wrapper."""
        start_time = time.monotonic()

        # Check rate limit before request
        if request.user_id and self._rate_limiter:
            await self._rate_limiter.on_request(request.user_id)

        client = await self._get_client()
        model = request.model or self.default_model_name

        try:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": request.messages,
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                    "stream": False,
                },
            )

            if response.status_code in (429, 529):
                raise RateLimitExceeded("LLM provider rate limit exceeded")

            if response.status_code == 401:
                logger.error("llm_auth_error", status_code=401, trace_id=request.trace_id)
                raise LLMError("LLM API authentication failed", "AUTH_ERROR")

            if response.status_code >= 500:
                logger.error(
                    "llm_server_error",
                    status_code=response.status_code,
                    trace_id=request.trace_id,
                )
                raise LLMError(
                    f"LLM server error: {response.status_code}",
                    "SERVER_ERROR",
                )

            response.raise_for_status()

        except httpx.TimeoutException as e:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "llm_timeout",
                timeout=self.timeout,
                latency_ms=latency_ms,
                trace_id=request.trace_id,
            )
            raise LLMTimeoutError(f"LLM request timed out after {self.timeout}s")

        except httpx.HTTPError as e:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "llm_http_error",
                error=str(e),
                latency_ms=latency_ms,
                trace_id=request.trace_id,
            )
            raise LLMError(f"LLM HTTP error: {e}")

        data = response.json()
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Extract usage information
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)

        # Record token usage
        if request.user_id and self._token_meter:
            await self._token_meter.record(
                user_id=request.user_id,
                model=model,
                tokens=total_tokens,
            )

        logger.info(
            "llm_chat_completed",
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            trace_id=request.trace_id,
        )

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=data["choices"][0].get("finish_reason", "stop"),
            latency_ms=latency_ms,
        )

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """
        Execute streaming chat completion.

        Args:
            request: LLMRequest with messages and options.

        Yields:
            String chunks of the generated content.

        Raises:
            LLMError: On generation failure.
            LLMTimeoutError: On timeout.
            RateLimitExceeded: On rate limit.
        """
        # Check rate limit before request
        if request.user_id and self._rate_limiter:
            await self._rate_limiter.on_request(request.user_id)

        client = await self._get_client()
        model = request.model or self.default_model_name

        try:
            async with client.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": request.messages,
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                    "stream": True,
                },
            ) as response:
                if response.status_code == 429:
                    raise RateLimitExceeded("LLM provider rate limit exceeded")

                if response.status_code >= 500:
                    raise LLMError(
                        f"LLM server error: {response.status_code}",
                        "SERVER_ERROR",
                    )

                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line[6:])
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]
                    elif line == "data: [DONE]":
                        break

        except httpx.TimeoutException:
            raise LLMTimeoutError(f"LLM streaming request timed out after {self.timeout}s")
        except httpx.HTTPError as e:
            raise LLMError(f"LLM streaming HTTP error: {e}")

    async def health_check(self) -> bool:
        """
        Check if the LLM provider is available.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get("/v1/models")
            return response.status_code == 200
        except Exception as e:
            logger.warning("llm_health_check_failed", error=str(e))
            return False

    @property
    def default_model(self) -> str:
        """Get the default model identifier."""
        return self.default_model_name


# =============================================================================
# Token Metering
# =============================================================================


class TokenMeter:
    """
    Token usage metering with Redis backend.

    Tracks per-user daily token consumption for billing and quota management.
    """

    def __init__(self, redis_client: Any) -> None:
        """
        Initialize token meter.

        Args:
            redis_client: Redis client instance (async).
        """
        self._redis = redis_client

    async def record(
        self,
        user_id: str,
        model: str,
        tokens: int,
    ) -> None:
        """
        Record token consumption for a user.

        Args:
            user_id: User identifier.
            model: Model used for the request.
            tokens: Number of tokens consumed.
        """
        date_str = datetime.now().strftime("%Y%m%d")

        # User daily consumption
        user_key = f"token_usage:{user_id}:{date_str}"
        await self._redis.incrby(user_key, tokens)
        await self._redis.expire(user_key, 86400 * 7)  # Keep for 7 days

        # Global daily consumption
        global_key = f"token_usage:global:{date_str}"
        await self._redis.incrby(global_key, tokens)
        await self._redis.expire(global_key, 86400 * 30)  # Keep for 30 days

        # Per-model daily consumption
        model_key = f"token_usage:model:{model}:{date_str}"
        await self._redis.incrby(model_key, tokens)
        await self._redis.expire(model_key, 86400 * 7)

        logger.debug(
            "token_usage_recorded",
            user_id=user_id,
            model=model,
            tokens=tokens,
        )

    async def get_usage(
        self,
        user_id: str,
        date: Optional[str] = None,
    ) -> int:
        """
        Get user's token usage for a specific day.

        Args:
            user_id: User identifier.
            date: Date string in YYYYMMDD format. Defaults to today.

        Returns:
            Total tokens consumed.
        """
        date_str = date or datetime.now().strftime("%Y%m%d")
        key = f"token_usage:{user_id}:{date_str}"
        value = await self._redis.get(key)
        return int(value) if value else 0

    async def get_global_usage(
        self,
        date: Optional[str] = None,
    ) -> int:
        """
        Get global token usage for a specific day.

        Args:
            date: Date string in YYYYMMDD format. Defaults to today.

        Returns:
            Total tokens consumed globally.
        """
        date_str = date or datetime.now().strftime("%Y%m%d")
        key = f"token_usage:global:{date_str}"
        value = await self._redis.get(key)
        return int(value) if value else 0

    async def get_model_usage(
        self,
        model: str,
        date: Optional[str] = None,
    ) -> int:
        """
        Get token usage for a specific model on a specific day.

        Args:
            model: Model identifier.
            date: Date string in YYYYMMDD format. Defaults to today.

        Returns:
            Total tokens consumed by the model.
        """
        date_str = date or datetime.now().strftime("%Y%m%d")
        key = f"token_usage:model:{model}:{date_str}"
        value = await self._redis.get(key)
        return int(value) if value else 0


# =============================================================================
# Rate Limiting
# =============================================================================


class TokenRateLimiter:
    """
    Per-user daily token rate limiting.

    Phase 1 implementation limits users to 500,000 tokens per day.
    Phase 2 will expand to department/organization quota management.
    """

    DEFAULT_DAILY_LIMIT = 500_000  # 50万 tokens per user per day

    def __init__(
        self,
        redis_client: Any,
        daily_token_limit: int = DEFAULT_DAILY_LIMIT,
    ) -> None:
        """
        Initialize rate limiter.

        Args:
            redis_client: Redis client instance (async).
            daily_token_limit: Maximum tokens per user per day.
        """
        self._meter = TokenMeter(redis_client)
        self._daily_limit = daily_token_limit

    async def check_limit(self, user_id: str) -> bool:
        """
        Check if user is within their daily token limit.

        Args:
            user_id: User identifier.

        Returns:
            True if within limit, False if exceeded.
        """
        usage = await self._meter.get_usage(user_id)
        return usage < self._daily_limit

    async def get_remaining(self, user_id: str) -> int:
        """
        Get remaining token quota for user.

        Args:
            user_id: User identifier.

        Returns:
            Number of tokens remaining in the daily window.
        """
        usage = await self._meter.get_usage(user_id)
        return max(0, self._daily_limit - usage)

    async def on_request(self, user_id: str) -> None:
        """
        Enforce rate limit before processing a request.

        Args:
            user_id: User identifier.

        Raises:
            RateLimitExceeded: If user has exceeded their daily limit.
        """
        if not await self.check_limit(user_id):
            remaining = await self.get_remaining(user_id)
            logger.warning(
                "rate_limit_exceeded",
                user_id=user_id,
                limit=self._daily_limit,
                remaining=remaining,
            )
            raise RateLimitExceeded(
                f"Daily token limit exceeded for user {user_id}. "
                f"Limit: {self._daily_limit}, Remaining: {remaining}"
            )


# =============================================================================
# LLM Generation Helpers
# =============================================================================


async def generate_ngql(
    adapter: LLMAdapter,
    question: str,
    schema_info: str,
    ontology_info: str,
    user_context: Optional[dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> LLMResponse:
    """
    Generate nGQL query from natural language question.

    Args:
        adapter: LLM adapter to use.
        question: User's natural language question.
        schema_info: Schema information (tags, edges, properties).
        ontology_info: Ontology/property mappings for context.
        user_context: Optional user context for permission-aware generation.
        trace_id: Optional trace ID for logging.

    Returns:
        LLMResponse with generated nGQL query.

    Raises:
        LLMGenerationError: If generation fails.
    """
    # Build system prompt with constraints
    system_prompt = f"""你是一个 NebulaGraph 数据库查询专家。你的唯一任务是将用户的自然语言问题转换为正确的 nGQL (NebulaGraph Query Language) 查询语句。

# 严格规则

1. **只生成 nGQL 查询**，不要回答问题，不要解释，不要猜测数据
2. **只使用 READ 操作**：MATCH, LOOKUP, GO, FETCH, FIND PATH
3. **禁止 WRITE 操作**：INSERT, UPDATE, UPSERT, DELETE, DROP, CREATE, ALTER
4. **每个查询必须有 LIMIT**（默认 LIMIT 100，除非用户指定数量或使用聚合函数）
5. **遍历深度不超过 5 跳**
6. **使用双等号 `==` 做比较**，单等号 `=` 是赋值
7. **字符串值使用双引号**

# NebulaGraph nGQL 语法约束

- **顶点属性访问**：`v.TagName.property_name`（带 Tag 前缀）
  - 示例：`s.Supplier.supplier_name`、`po.PurchaseOrder.total_amount`
  - 常见 Tag：Supplier、PurchaseOrder、Invoice、Payment、Receipt、Item 等
- **边属性访问**：直接用别名，不带边类型前缀
  - 示例：`e.match_status`（不是 `e.HAS_INVOICE.match_status`）
  - 示例：`e.priority`（不是 `e.SUPPLIES_ITEM.priority`）
- 比较运算符: `==`（不是 `=`）
- 分页: `LIMIT 10 OFFSET 5`（不是 `SKIP 5 LIMIT 10`）
- 不支持 MERGE（用 UPSERT 替代，但这里只做读查询）
- **OPTIONAL MATCH 禁止加 WHERE 子句**：`OPTIONAL MATCH ... WHERE` 语法不支持
  - 正确：分两步查 `MATCH ... WHERE ... RETURN` + `OPTIONAL MATCH ... RETURN`
  - 错误：`OPTIONAL MATCH (a)->(b) WHERE a.x == 1 RETURN ...`（WHERE 放在 OPTIONAL MATCH 后会报 SyntaxError）
- **MATCH 查询 ORDER BY 必须使用列别名**：ORDER BY 不能直接引用顶点/边属性路径，必须在 RETURN 中先用 `AS` 指定列别名，再在 ORDER BY 中使用该别名
  - 正确：`MATCH (po:PurchaseOrder) RETURN po.PurchaseOrder.po_number AS po_number, po.PurchaseOrder.total_amount AS amount ORDER BY amount DESC LIMIT 5`
  - 错误：`MATCH (po:PurchaseOrder) RETURN po.PurchaseOrder.total_amount ORDER BY po.PurchaseOrder.total_amount DESC LIMIT 5`（会报 SemanticError: Only column name can be used as sort item）
  - **所有 MATCH 查询的每个 RETURN 列都必须有 AS 别名**，ORDER BY 只用别名
- 最短路径: `FIND SHORTEST PATH FROM "vid1" TO "vid2" OVER * BIDIRECT UPTO 5 STEPS`
- 标签函数: `tags(n)`（不是 `labels(n)`）

# 可用函数

- 聚合: count(), sum(), avg(), min(), max(), collect()
- 字符串: lower(), upper(), trim(), left(), right(), length()
- 数学: abs(), ceil(), floor(), round(), sqrt()
- 日期: now(), date(), time(), datetime(), datetime_diff()
- 类型: toInteger(), toFloat(), toString(), toBoolean()
- 列表: size(), range(), head(), tail(), reduce()

# 业务概念 → nGQL 查询映射（重要！）

回答以下业务问题时，直接使用对应的查询模式，不要自己臆造查询：

## 供应商风险相关

**高风险供应商 / 高风险供应商有哪些 / 哪些供应商风险高**
→ 满足以下任一条件：
  - credit_rating IN ["C", "D"]（信用评级为 C 或 D）
  - status == "BLOCKED"（被冻结的供应商）
  - qualification_expiry <= now() + 30天 AND qualification status == "VALID"（资质即将过期）
- 示例: `WHERE s.Supplier.credit_rating IN ["C", "D"] OR s.Supplier.status == "BLOCKED"`

**被冻结的供应商 / BLOCKED 供应商**
→ status == "BLOCKED"

**单一供应商风险 / 单一来源物料**
→ 某 Item 只有 1 个 ACTIVE 供应商（count(s) == 1）

**供应商集中度风险 / 采购集中度过高**
→ 某供应商 PO 金额占全局 PO 金额 > 30%

## 付款风险相关

**高风险付款 / 有风险的付款记录**
→ 满足以下任一条件即为高风险：
  - 付款供应商为 BLOCKED 状态：`(pay:Payment)-[:PAID_TO]->(s:Supplier) WHERE s.Supplier.status == "BLOCKED"`
  - 提前付款（早于到期日 30 天以上）：`pay.Payment.payment_date < inv.Invoice.due_date - 30天`
  - 超额付款：Payment.amount > Invoice.total_amount
  - 金额异常付款（付款金额与发票金额偏差 > 20%）

**虚假付款 / 可疑付款 / 欺诈付款**
→ 重点关注：
  - 付款供应商为 BLOCKED：`s.Supplier.status == "BLOCKED"`
  - 提前异常付款（无合理原因的提前付款）
  - 金额异常大的付款

**虚假交易 / 虚假采购 / 高风险虚假交易 / 欺诈采购**
→ 这是最严重的风险类型，定义为以下任意一种：
  1. 收货日期早于 PO 日期（虚假发货/虚构交易）：
     `MATCH (po:PurchaseOrder)-[:HAS_RECEIPT]->(r:Receipt) WHERE r.Receipt.receipt_date < po.PurchaseOrder.order_date RETURN count(po)`
  2. 发票日期早于收货日期（先票后货/虚假发票）：
     `MATCH (po:PurchaseOrder)-[:HAS_RECEIPT]->(r:Receipt)-[:FOR_INVOICE]->(inv:Invoice) WHERE inv.Invoice.invoice_date < r.Receipt.receipt_date`
  3. 付款给 BLOCKED 供应商：
     `MATCH (pay:Payment)-[:PAYS_INVOICE]->(inv:Invoice)-[:INVOICED_BY]->(s:Supplier) WHERE s.Supplier.status == "BLOCKED"`
  4. 超额付款（付款金额 > 发票金额）：
     `MATCH (pay:Payment)-[:PAYS_INVOICE]->(inv:Invoice) WHERE pay.Payment.amount > inv.Invoice.total_amount`
  5. 供应商不一致（PO 供应商 ≠ 发票供应商）：
     `MATCH (po:PurchaseOrder)-[:PLACED_WITH]->(s_po:Supplier), (po)-[:HAS_INVOICE]->(inv:Invoice)-[:INVOICED_BY]->(s_inv:Supplier) WHERE s_po.Supplier.supplier_number != s_inv.Supplier.supplier_number`
→ 查询"高风险虚假采购"的正确方法是：使用上述任一条件，不要只查供应商状态！

**提前付款 / 早付款**
→ `payment_date < due_date - 30天`，且无合理解释

**超期未付发票 / 逾期账款**
→ `Invoice.status == "APPROVED" AND Invoice.due_date < now()`，按超期天数分级

**重复发票 / 疑似重复发票**
→ 同供应商、同金额、发票日期相差 ≤ 3 天但发票号不同

## 三单匹配相关

**三单不匹配 / 三单匹配异常 / 发票与 PO 金额不符**
→ `HAS_INVOICE.match_status IN ["UNMATCHED", "PARTIAL"]`
→ 且金额偏差 = |Invoice.total_amount - PO.total_amount| / PO.total_amount

**发票金额偏差大 / 发票与订单金额差异大**
→ 偏差百分比 > 10%（WARNING）或 > 20%（ALERT）

## 供应商资质相关

**资质过期 / 过期资质 / 供应商资质过期**
→ `SupplierQualification.status == "VALID" AND expiry_date < now()`
→ 或 `expiry_date <= now() + 30天`（即将过期预警）

**无资质供应商 / 缺少资质的供应商**
→ 供应商没有有效的 SupplierQualification 记录

## 日期/时序异常

**日期异常 / 发票日期早于收货日期**
→ `Invoice.invoice_date < Receipt.receipt_date`

**收货日期早于 PO 日期**
→ `Receipt.receipt_date < PO.order_date`

# Schema 信息

{schema_info}

# 本体信息

{ontology_info}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    # Inject user context for permission-aware generation
    if user_context:
        context_str = f"\n\n# 用户权限上下文\nuser_id: {user_context.get('user_id', 'unknown')}\n"
        if user_context.get("org_ids"):
            context_str += f"org_ids: {', '.join(str(o) for o in user_context['org_ids'])}\n"
        if user_context.get("dept_ids"):
            context_str += f"dept_ids: {', '.join(str(d) for d in user_context['dept_ids'])}\n"
        if user_context.get("data_scope"):
            context_str += f"data_scope: {user_context['data_scope']}\n"
        messages[1]["content"] = context_str + "\n\n" + question

    request = LLMRequest(
        messages=messages,
        temperature=0.1,  # Low temperature for deterministic nGQL
        max_tokens=8192,  # Increased to allow complete nGQL generation with long schemas
        trace_id=trace_id,
        user_id=user_context.get("user_id") if user_context else None,
    )

    try:
        response = await adapter.chat(request)
        return response
    except Exception as e:
        logger.error(
            "ngql_generation_failed",
            error=str(e),
            question=question[:100],
            trace_id=trace_id,
        )
        raise LLMGenerationError(
            f"Failed to generate nGQL from question: {e}",
            question=question,
        )


async def summarize_results(
    adapter: LLMAdapter,
    question: str,
    raw_results: list[dict[str, Any]],
    columns: list[str],
    trace_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> LLMResponse:
    """
    Generate human-readable summary of query results.

    Args:
        adapter: LLM adapter to use.
        question: Original user question.
        raw_results: Raw query results from NebulaGraph.
        columns: Column names from the query.
        trace_id: Optional trace ID for logging.
        user_id: Optional user ID for metering.

    Returns:
        LLMResponse with summarized text.

    Raises:
        LLMSummarizationError: If summarization fails.
    """
    system_prompt = """你是一个 ERP 数据分析助手。你的任务是将数据库查询结果用通俗的中文总结。

# 严格规则

1. **不要修改任何数值**（金额、数量、日期等必须与原始数据完全一致）
2. **不要补充数据库中没有的信息**
3. **不要推测**任何原因或解释，但可以根据数据本身的规律指出"异常模式"
4. 如果数据为空，直接说明"未查询到符合条件的数据"
5. 使用中文回答
6. 保持简洁明了，突出关键信息

# 分析维度

根据原始问题判断当前属于哪类查询，对结果进行针对性分析：

## 如果问题是"有多少..."类（统计类）
- 直接给出数量
- 如果有分类，给出各分类的数量分布
- 指出最突出的类别

## 如果问题是"找出/检测..."类（风险检测类）
- 逐条指出每条记录为什么是高风险
- 标注风险等级（CRITICAL/HIGH/MEDIUM/WARNING）
- 重点关注以下风险标记：
  - BLOCKED 供应商相关 → CRITICAL（合规违规）
  - 金额偏差 > 20% → HIGH
  - 提前付款 30 天以上 → HIGH（可疑）
  - 金额偏差 10-20% → WARNING
  - 供应商资质即将过期（30 天内）→ MEDIUM
  - 超期未付发票 → 按超期天数分级

## 如果问题是"列出/展示..."类（列表类）
- 简洁列出前 10 条关键信息
- 说明总数量
- 如有排序，说明排序依据

# 输出格式

先说结论（查到多少条、风险等级分布），再说具体分析。
不要逐行朗读原始数据，要提炼关键信息。
"""

    # Format results for the prompt
    if not raw_results:
        results_text = "未查询到符合条件的数据"
    else:
        lines = []
        for i, row in enumerate(raw_results[:100]):  # Limit to 100 rows
            row_str = " | ".join(f"{col}={row.get(col, '')}" for col in columns)
            lines.append(f"Row {i + 1}: {row_str}")
        results_text = "\n".join(lines)
        if len(raw_results) > 100:
            results_text += f"\n... (共 {len(raw_results)} 行，已截断)"

    user_prompt = f"""# 用户问题
{question}

# 查询结果
{results_text}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    request = LLMRequest(
        messages=messages,
        temperature=0.3,  # Slightly higher for summarization creativity
        max_tokens=2048,
        trace_id=trace_id,
        user_id=user_id,
    )

    try:
        response = await adapter.chat(request)
        return response
    except Exception as e:
        logger.error(
            "summarization_failed",
            error=str(e),
            result_count=len(raw_results),
            trace_id=trace_id,
        )
        raise LLMSummarizationError(f"Failed to summarize results: {e}")
