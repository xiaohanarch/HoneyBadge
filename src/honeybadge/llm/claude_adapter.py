"""Claude LLM Adapter for HoneyBadge (fallback when MiniMax unavailable)."""

import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class ClaudeResponse:
    """Claude API response."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str
    latency_ms: int
    success: bool = True
    error_message: Optional[str] = None


class ClaudeAdapter:
    """
    Adapter for Anthropic Claude API.

    Used as fallback when MiniMax is unavailable.
    Endpoint: https://api.anthropic.com/v1
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://api.anthropic.com/v1",
        version: str = "2023-06-01",
        timeout: int = 60,
    ):
        """
        Initialize Claude adapter.

        Args:
            api_key: Anthropic API key
            endpoint: API base URL
            version: API version
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.version = version
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.endpoint,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.version,
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

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> ClaudeResponse:
        """
        Send a chat completion request to Claude.

        Args:
            messages: List of message dicts [{"role": "user", "content": "..."}]
            model: Model name (claude-3-5-sonnet-20241022, etc.)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            ClaudeResponse with the completion
        """
        start_time = time.monotonic()

        # Convert messages format for Claude
        claude_messages = []
        for msg in messages:
            if msg["role"] == "system":
                claude_messages.append({"role": "user", "content": f"[System] {msg['content']}"})
            else:
                claude_messages.append({"role": msg["role"], "content": msg["content"]})

        try:
            client = await self._get_client()
            response = await client.post(
                "/messages",
                json={
                    "model": model,
                    "messages": claude_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Calculate approximate token counts
            input_text = " ".join(m["content"] for m in claude_messages)
            prompt_tokens = len(input_text) // 4  # Rough approximation
            completion_tokens = len(data["content"][0]["text"]) // 4

            return ClaudeResponse(
                content=data["content"][0]["text"],
                model=data["model"],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                finish_reason=data.get("stop_reason", "end_turn"),
                latency_ms=latency_ms,
                success=True,
            )

        except httpx.HTTPStatusError as e:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            error_body = e.response.text[:500] if e.response.text else "No response body"
            logger.error(
                "claude_http_error",
                status=e.response.status_code,
                error=error_body,
            )
            return ClaudeResponse(
                content="",
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                finish_reason="error",
                latency_ms=latency_ms,
                success=False,
                error_message=f"HTTP {e.response.status_code}: {error_body}",
            )

        except Exception as e:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            logger.error("claude_request_error", error=str(e))
            return ClaudeResponse(
                content="",
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                finish_reason="error",
                latency_ms=latency_ms,
                success=False,
                error_message=str(e),
            )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """
        Send a streaming chat completion request to Claude.

        Args:
            messages: List of message dicts
            model: Model name
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Yields:
            Text chunks as they arrive
        """
        try:
            client = await self._get_client()

            claude_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    claude_messages.append({"role": "user", "content": f"[System] {msg['content']}"})
                else:
                    claude_messages.append({"role": msg["role"], "content": msg["content"]})

            async with client.stream(
                "POST",
                "/messages",
                json={
                    "model": model,
                    "messages": claude_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: ") and not line.startswith("data: [DONE]"):
                        chunk = json.loads(line[6:])
                        if chunk.get("type") == "content_block_delta":
                            if chunk.get("delta", {}).get("type") == "text_delta":
                                yield chunk["delta"]["text"]

        except Exception as e:
            logger.error("claude_stream_error", error=str(e))
            raise


# Convenience function
async def create_claude_adapter(
    api_key: str,
) -> ClaudeAdapter:
    """Create a Claude adapter instance."""
    return ClaudeAdapter(api_key=api_key)
