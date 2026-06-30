"""MiniMax LLM Adapter for HoneyBadge."""

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class MiniMaxRequest:
    """MiniMax API request."""

    model: str
    messages: list[dict[str, str]]
    temperature: float = 0.1
    max_tokens: int = 4096
    stream: bool = False


@dataclass
class MiniMaxResponse:
    """MiniMax API response."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str
    latency_ms: int
    success: bool = True
    error_message: str | None = None


class MiniMaxAdapter:
    """
    Adapter for MiniMax API (compatible with OpenAI format).

    MiniMax endpoint: https://api.minimax.chat/v1
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://api.minimax.chat/v1",
        timeout: int = 60,
    ):
        """
        Initialize MiniMax adapter.

        Args:
            api_key: MiniMax API key
            endpoint: API base URL
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
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

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "MiniMax-Text-01",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> MiniMaxResponse:
        """
        Send a chat completion request.

        Args:
            messages: List of message dicts [{"role": "user", "content": "..."}]
            model: Model name
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            MiniMaxResponse with the completion
        """
        start_time = time.monotonic()

        try:
            client = await self._get_client()
            # Use Anthropic-compatible endpoint (/v1/messages) like Claude Code
            response = await client.post(
                "/v1/messages",
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # MiniMax API returns content as array with mixed types (thinking, text)
            # Find the text content
            text_content = ""
            for item in data.get("content", []):
                if item.get("type") == "text":
                    text_content = item.get("text", "")
                    break

            return MiniMaxResponse(
                content=text_content,
                model=data["model"],
                prompt_tokens=data["usage"]["input_tokens"],
                completion_tokens=data["usage"]["output_tokens"],
                total_tokens=data["usage"]["input_tokens"] + data["usage"]["output_tokens"],
                finish_reason=data["stop_reason"],
                latency_ms=latency_ms,
                success=True,
            )

        except httpx.HTTPStatusError as e:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            error_body = e.response.text[:500] if e.response.text else "No response body"
            logger.error(
                "minimax_http_error",
                status=e.response.status_code,
                error=error_body,
            )
            return MiniMaxResponse(
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
            logger.error("minimax_request_error", error=str(e))
            return MiniMaxResponse(
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
        model: str = "MiniMax-Text-01",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """
        Send a streaming chat completion request.

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
            async with client.stream(
                "POST",
                "/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line[6:])
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]
                    elif line == "data: [DONE]":
                        break

        except Exception as e:
            logger.error("minimax_stream_error", error=str(e))
            raise


# Convenience function
async def create_minimax_adapter(
    api_key: str,
    endpoint: str = "https://api.minimax.chat/v1",
) -> MiniMaxAdapter:
    """Create a MiniMax adapter instance."""
    return MiniMaxAdapter(api_key=api_key, endpoint=endpoint)
