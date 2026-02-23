"""OpenAI LLM provider — near pass-through since internal format matches OpenAI."""
from __future__ import annotations

from typing import Any, Iterator

from openai import APIError, OpenAI, RateLimitError

from agent.providers.base import LLMProvider, SimpleUsage


class OpenAIProvider(LLMProvider):
    """OpenAI API provider (GPT-4o, o3, etc.)."""

    def __init__(self, api_key: str) -> None:
        self._client = OpenAI(api_key=api_key)

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        # O-series models don't support temperature
        if not model.startswith("o"):
            kwargs["temperature"] = temperature

        response = self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        usage = SimpleUsage()
        if response.usage:
            usage = SimpleUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )

        msg_dict: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content,
        }
        if msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        return {"message": msg_dict, "usage": usage}

    def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Iterator[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        # O-series models don't support temperature
        if not model.startswith("o"):
            kwargs["temperature"] = temperature

        stream = self._client.chat.completions.create(**kwargs)

        try:
            for chunk in stream:
                if not chunk.choices:
                    if chunk.usage:
                        yield {
                            "type": "usage",
                            "usage": SimpleUsage(
                                prompt_tokens=chunk.usage.prompt_tokens,
                                completion_tokens=chunk.usage.completion_tokens,
                            ),
                        }
                    continue

                delta = chunk.choices[0].delta

                if delta.content:
                    yield {"type": "content_delta", "content": delta.content}

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        yield {
                            "type": "tool_call_delta",
                            "index": tc_delta.index,
                            "id": tc_delta.id if tc_delta.id else None,
                            "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else None,
                            "arguments": tc_delta.function.arguments if tc_delta.function and tc_delta.function.arguments else None,
                        }
        except KeyboardInterrupt:
            try:
                stream.close()
            except Exception:
                pass
            raise

        yield {"type": "done"}

    def name(self) -> str:
        return "openai"
