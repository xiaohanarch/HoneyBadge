"""LLM adapter layer for HoneyBadge.

Provides unified interface for LLM calls with OpenAI-compatible API support,
token metering, and rate limiting.
"""

from honeybadge.llm.adapter import (
    LLMAdapter,
    LLMRequest,
    LLMResponse,
    OpenAICompatibleAdapter,
    TokenMeter,
    TokenRateLimiter,
    generate_ngql,
    summarize_results,
)
from honeybadge.llm.provider import (
    LLMProviderManager,
    QueryComplexity,
)

__all__ = [
    # Core adapter classes
    "LLMAdapter",
    "LLMRequest",
    "LLMResponse",
    "OpenAICompatibleAdapter",
    "TokenMeter",
    "TokenRateLimiter",
    # Provider manager
    "LLMProviderManager",
    "QueryComplexity",
    # Helper functions
    "generate_ngql",
    "summarize_results",
]
