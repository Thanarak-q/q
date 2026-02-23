"""Google (Gemini) LLM provider — stub for future implementation."""
from __future__ import annotations

from typing import Any, Iterator

from agent.providers.base import LLMProvider, SimpleUsage


class GoogleProvider(LLMProvider):
    """Google Gemini API provider (stub).

    Not yet implemented. Use FALLBACK_MODEL to route to OpenAI or Anthropic.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "Google provider not yet implemented. "
            "Use FALLBACK_MODEL to route to OpenAI or Anthropic."
        )

    def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Iterator[dict[str, Any]]:
        raise NotImplementedError(
            "Google provider not yet implemented. "
            "Use FALLBACK_MODEL to route to OpenAI or Anthropic."
        )

    def name(self) -> str:
        return "google"
