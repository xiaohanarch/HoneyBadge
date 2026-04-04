"""LLM adapter implementation for HoneyBadge.

Provides LLMRequest/LLMResponse dataclasses, abstract LLMAdapter base class,
OpenAI-compatible adapter with httpx, token metering, and rate limiting.
"""

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
            self._client = httpx.AsyncClient(
                base_url=self.endpoint,
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
        Execute synchronous chat completion.

        Args:
            request: LLMRequest with messages and options.

        Returns:
            LLMResponse with generated content.

        Raises:
            LLMError: On generation failure.
            LLMTimeoutError: On timeout.
            RateLimitExceeded: On rate limit.
        """
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

            if response.status_code == 429:
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
6. **属性访问必须带 Tag 前缀**：`n.TagName.property_name`
7. **使用双等号 `==` 做比较**，单等号 `=` 是赋值
8. **字符串值使用双引号**

# NebulaGraph nGQL 语法约束

- 属性访问: `n.Supplier.supplier_name`（不是 `n.supplier_name`）
- 比较运算符: `==`（不是 `=`）
- 分页: `LIMIT 10 OFFSET 5`（不是 `SKIP 5 LIMIT 10`）
- 不支持 MERGE（用 UPSERT 替代，但这里只做读查询）
- 最短路径: `FIND SHORTEST PATH FROM "vid1" TO "vid2" OVER * BIDIRECT UPTO 5 STEPS`
- 标签函数: `tags(n)`（不是 `labels(n)`）

# 可用函数

- 聚合: count(), sum(), avg(), min(), max(), collect()
- 字符串: lower(), upper(), trim(), left(), right(), length()
- 数学: abs(), ceil(), floor(), round(), sqrt()
- 日期: now(), date(), time(), datetime(), datetime_diff()
- 类型: toInteger(), toFloat(), toString(), toBoolean()
- 列表: size(), range(), head(), tail(), reduce()

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
        max_tokens=4096,
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
3. **不要推测或猜测任何结论**
4. 如果数据为空，直接说明"未查询到符合条件的数据"
5. 使用中文回答
6. 保持简洁明了，突出关键信息
7. 对于表格数据，使用清晰的列表或表格格式

# 输出格式

以自然语言方式总结查询结果，突出关键发现。
如果发现异常数据（如三单不匹配、金额异常），明确标注。
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
