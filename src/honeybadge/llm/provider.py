"""LLM Provider Manager for HoneyBadge.

Manages multiple LLM providers with primary/fallback routing and
model selection based on query complexity.
"""

from typing import Any

import structlog

from honeybadge.core.exceptions import LLMError, RateLimitExceeded
from honeybadge.llm.adapter import LLMAdapter, LLMRequest, LLMResponse

logger = structlog.get_logger()


class QueryComplexity:
    """Query complexity levels for model selection."""

    SIMPLE = "simple"  # Simple queries - use faster/cheaper model
    COMPLEX = "complex"  # Complex queries - use more capable model


class LLMProviderManager:
    """
    Manager for multiple LLM providers with routing and fallback.

    Supports primary/fallback provider architecture with automatic
    failover on errors. Model selection is based on query complexity.

    Configuration example:
        {
            "primary": "qwen",
            "fallback": "glm",
            "providers": {
                "qwen": {
                    "endpoint": "https://dashscope.aliyuncs.com/compatible-mode",
                    "api_key": "${QWEN_API_KEY}",
                    "model": "qwen-turbo",
                    "models": {
                        "complex": "qwen-max",
                        "simple": "qwen-turbo"
                    },
                    "rate_limit": {"rpm": 60, "tpm": 100000},
                    "timeout": 60
                },
                "glm": {
                    "endpoint": "https://open.bigmodel.cn/api/paas/v4",
                    "api_key": "${GLM_API_KEY}",
                    "model": "glm-4-flash",
                    "models": {
                        "complex": "glm-4-plus",
                        "simple": "glm-4-flash"
                    },
                    "rate_limit": {"rpm": 100, "tpm": 200000},
                    "timeout": 60
                }
            }
        }
    """

    def __init__(
        self,
        config: dict[str, Any],
        redis_client: Any | None = None,
    ) -> None:
        """
        Initialize the provider manager.

        Args:
            config: Provider configuration dict.
            redis_client: Optional Redis client for token metering.
        """
        self._providers: dict[str, LLMAdapter] = {}
        self._provider_configs: dict[str, dict[str, Any]] = {}
        self._primary = config.get("primary", "qwen")
        self._fallback = config.get("fallback")

        # Initialize all providers
        provider_configs = config.get("providers", {})
        for name, provider_config in provider_configs.items():
            self._provider_configs[name] = provider_config
            self._providers[name] = self._create_adapter(name, provider_config, redis_client)

        logger.info(
            "llm_provider_manager_initialized",
            primary=self._primary,
            fallback=self._fallback,
            provider_count=len(self._providers),
        )

    @staticmethod
    def _create_adapter(
        name: str,
        config: dict[str, Any],
        redis_client: Any | None = None,
    ) -> LLMAdapter:
        """
        Create an LLM adapter from configuration.

        Args:
            name: Provider name for logging.
            config: Provider configuration.
            redis_client: Optional Redis client.

        Returns:
            Configured LLMAdapter instance.
        """
        from honeybadge.llm.adapter import OpenAICompatibleAdapter

        adapter_type = config.get("adapter", "openai_compatible")

        if adapter_type == "openai_compatible":
            return OpenAICompatibleAdapter(config, redis_client)
        else:
            raise ValueError(f"Unknown adapter type: {adapter_type}")

    def get_provider(self, name: str | None = None) -> LLMAdapter:
        """
        Get a provider by name.

        Args:
            name: Provider name. Defaults to primary provider.

        Returns:
            LLMAdapter instance.

        Raises:
            KeyError: If provider not found.
        """
        provider_name = name or self._primary
        if provider_name not in self._providers:
            raise KeyError(f"Unknown provider: {provider_name}")
        return self._providers[provider_name]

    def get_model(
        self,
        provider_name: str | None = None,
        complexity: str = QueryComplexity.COMPLEX,
    ) -> str:
        """
        Get the model identifier for a provider and complexity level.

        Args:
            provider_name: Provider name. Defaults to primary.
            complexity: Query complexity (simple or complex).

        Returns:
            Model identifier string.
        """
        name = provider_name or self._primary
        provider_config = self._provider_configs.get(name, {})
        models = provider_config.get("models", {})
        default_model = provider_config.get("model", "unknown")
        return models.get(complexity, default_model)

    async def chat(
        self,
        request: LLMRequest,
        query_complexity: str = QueryComplexity.COMPLEX,
        provider_name: str | None = None,
    ) -> LLMResponse:
        """
        Execute chat completion with automatic fallback.

        Routes to primary provider by default, falling back to configured
        fallback provider on failure. Model selection is based on complexity.

        Args:
            request: LLMRequest with messages and options.
            query_complexity: "complex" or "simple" for model selection.
            provider_name: Override provider name.

        Returns:
            LLMResponse from the LLM.

        Raises:
            LLMError: If both primary and fallback fail.
            RateLimitExceeded: If rate limit exceeded (no fallback).
        """
        primary_name = provider_name or self._primary
        primary = self.get_provider(primary_name)

        # Set the model based on complexity
        request.model = self.get_model(primary_name, query_complexity)

        try:
            logger.debug(
                "llm_provider_chat",
                provider=primary_name,
                model=request.model,
                trace_id=request.trace_id,
            )
            return await primary.chat(request)

        except RateLimitExceeded:
            # Rate limit - do not fallback, propagate immediately
            logger.warning(
                "llm_rate_limit_no_fallback",
                provider=primary_name,
                trace_id=request.trace_id,
            )
            raise

        except LLMError as e:
            # Primary failed, try fallback if available
            logger.warning(
                "llm_primary_failed",
                provider=primary_name,
                error=str(e),
                trace_id=request.trace_id,
            )

            if self._fallback:
                return await self._chat_with_fallback(
                    request,
                    query_complexity,
                    e,
                )

            # No fallback configured, propagate the error
            raise

        except Exception as e:
            # Unexpected error - try fallback if available
            logger.error(
                "llm_unexpected_error",
                provider=primary_name,
                error=str(e),
                trace_id=request.trace_id,
            )

            if self._fallback:
                return await self._chat_with_fallback(
                    request,
                    query_complexity,
                    e,
                )

            raise LLMError(f"Unexpected LLM error: {e}")

    async def _chat_with_fallback(
        self,
        request: LLMRequest,
        query_complexity: str,
        original_error: Exception,
    ) -> LLMResponse:
        """
        Attempt to use fallback provider.

        Args:
            request: Original request.
            query_complexity: Query complexity for model selection.
            original_error: Error from primary provider.

        Returns:
            LLMResponse from fallback provider.

        Raises:
            LLMError: If fallback also fails.
        """
        fallback = self.get_provider(self._fallback)
        fallback_model = self.get_model(self._fallback, query_complexity)

        logger.info(
            "llm_trying_fallback",
            primary=self._primary,
            fallback=self._fallback,
            fallback_model=fallback_model,
            original_error=str(original_error),
            trace_id=request.trace_id,
        )

        request.model = fallback_model

        try:
            return await fallback.chat(request)
        except Exception as e:
            logger.error(
                "llm_fallback_failed",
                fallback=self._fallback,
                error=str(e),
                original_error=str(original_error),
                trace_id=request.trace_id,
            )
            raise LLMError(
                f"Both primary and fallback LLM providers failed. "
                f"Primary error: {original_error}. "
                f"Fallback error: {e}"
            )

    async def chat_stream(
        self,
        request: LLMRequest,
        query_complexity: str = QueryComplexity.COMPLEX,
        provider_name: str | None = None,
    ):
        """
        Execute streaming chat completion with fallback support.

        Args:
            request: LLMRequest with messages and options.
            query_complexity: "complex" or "simple" for model selection.
            provider_name: Override provider name.

        Yields:
            String chunks from the LLM.

        Raises:
            LLMError: If all providers fail.
        """
        primary_name = provider_name or self._primary
        primary = self.get_provider(primary_name)
        request.model = self.get_model(primary_name, query_complexity)

        try:
            async for chunk in primary.chat_stream(request):
                yield chunk

        except Exception as e:
            logger.warning(
                "llm_stream_primary_failed",
                provider=primary_name,
                error=str(e),
                trace_id=request.trace_id,
            )

            if self._fallback:
                fallback = self.get_provider(self._fallback)
                fallback_model = self.get_model(self._fallback, query_complexity)
                request.model = fallback_model

                logger.info(
                    "llm_stream_trying_fallback",
                    fallback=self._fallback,
                    fallback_model=fallback_model,
                    trace_id=request.trace_id,
                )

                try:
                    async for chunk in fallback.chat_stream(request):
                        yield chunk
                    return
                except Exception as fallback_error:
                    logger.error(
                        "llm_stream_fallback_failed",
                        fallback=self._fallback,
                        error=str(fallback_error),
                        trace_id=request.trace_id,
                    )
                    raise LLMError(
                        f"Both primary and fallback streaming failed. "
                        f"Original: {e}, Fallback: {fallback_error}"
                    )
            else:
                raise LLMError(f"Streaming failed: {e}")

    async def health_check_all(self) -> dict[str, bool]:
        """
        Check health of all configured providers.

        Returns:
            Dict mapping provider names to health status.
        """
        results = {}
        for name, provider in self._providers.items():
            results[name] = await provider.health_check()
        return results

    async def close_all(self) -> None:
        """Close all provider connections."""
        for name, provider in self._providers.items():
            if hasattr(provider, "close"):
                await provider.close()
                logger.debug("llm_provider_closed", provider=name)
