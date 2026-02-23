"""Abstract base for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class SimpleUsage:
    """Token usage that works with existing CostTracker.record()."""

    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider(ABC):
    """Abstract LLM provider interface.

    All providers accept and return OpenAI-format message dicts as the
    canonical internal format. Translation happens inside each provider.
    """

    @abstractmethod
    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Synchronous chat completion.

        Returns:
            {"message": <assistant msg dict>, "usage": SimpleUsage}
        """
        ...

    @abstractmethod
    def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Iterator[dict[str, Any]]:
        """Streaming chat completion.

        Yields dicts with "type" key:
            - {"type": "content_delta", "content": str}
            - {"type": "tool_call_delta", "index": int, "id": str|None, "name": str|None, "arguments": str|None}
            - {"type": "usage", "usage": SimpleUsage}
            - {"type": "done"}
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Provider name identifier."""
        ...
