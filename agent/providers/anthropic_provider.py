"""Anthropic (Claude) LLM provider with message format translation."""
from __future__ import annotations

import json
from typing import Any, Iterator

from agent.providers.base import LLMProvider, SimpleUsage


class AnthropicProvider(LLMProvider):
    """Anthropic API provider (Claude models)."""

    def __init__(self, api_key: str) -> None:
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package is required for Anthropic provider. "
                "Install with: pip install anthropic"
            )
        self._client = anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # Message format translation
    # ------------------------------------------------------------------

    @staticmethod
    def _translate_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """OpenAI tool format -> Anthropic tool format."""
        if not tools:
            return None
        translated = []
        for tool in tools:
            func = tool.get("function", {})
            translated.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {}),
            })
        return translated

    @staticmethod
    def _translate_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Translate OpenAI-format messages to Anthropic format.

        Returns:
            (system_prompt, translated_messages)
        """
        system_prompt = ""
        translated: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")

            # Extract system message
            if role == "system":
                system_prompt = msg.get("content", "") or ""
                continue

            # Tool result messages -> Anthropic tool_result format
            if role == "tool":
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", "") or "",
                }
                # Merge into previous user message or create new one
                if translated and translated[-1]["role"] == "user":
                    content = translated[-1]["content"]
                    if isinstance(content, str):
                        translated[-1]["content"] = [
                            {"type": "text", "text": content},
                            tool_result,
                        ]
                    elif isinstance(content, list):
                        content.append(tool_result)
                else:
                    translated.append({
                        "role": "user",
                        "content": [tool_result],
                    })
                continue

            # Assistant messages with tool_calls
            if role == "assistant":
                content_blocks: list[dict[str, Any]] = []
                text = msg.get("content", "") or ""
                if text:
                    content_blocks.append({"type": "text", "text": text})

                tool_calls = msg.get("tool_calls", [])
                for tc in tool_calls:
                    func = tc.get("function", {})
                    try:
                        input_data = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        input_data = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": input_data,
                    })

                if content_blocks:
                    translated.append({
                        "role": "assistant",
                        "content": content_blocks,
                    })
                else:
                    translated.append({
                        "role": "assistant",
                        "content": text or "",
                    })
                continue

            # Regular user messages
            if role == "user":
                translated.append({
                    "role": "user",
                    "content": msg.get("content", "") or "",
                })
                continue

        # Merge consecutive same-role messages (Anthropic requires alternating roles)
        merged: list[dict[str, Any]] = []
        for msg in translated:
            if merged and merged[-1]["role"] == msg["role"]:
                prev_content = merged[-1]["content"]
                curr_content = msg["content"]

                # Normalize both to list format
                if isinstance(prev_content, str):
                    prev_content = [{"type": "text", "text": prev_content}]
                if isinstance(curr_content, str):
                    curr_content = [{"type": "text", "text": curr_content}]
                if not isinstance(prev_content, list):
                    prev_content = [prev_content]
                if not isinstance(curr_content, list):
                    curr_content = [curr_content]

                merged[-1]["content"] = prev_content + curr_content
            else:
                merged.append(msg)

        return system_prompt, merged

    @staticmethod
    def _translate_response(response: Any) -> dict[str, Any]:
        """Map Anthropic response back to internal (OpenAI-like) format."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    },
                })

        msg_dict: dict[str, Any] = {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None,
        }
        if tool_calls:
            msg_dict["tool_calls"] = tool_calls

        return msg_dict

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        system_prompt, translated_msgs = self._translate_messages(messages)
        anthropic_tools = self._translate_tools(tools)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": translated_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
            # Map tool_choice
            if tool_choice == "auto":
                kwargs["tool_choice"] = {"type": "auto"}
            elif tool_choice == "none":
                kwargs["tool_choice"] = {"type": "none"}
            elif tool_choice == "required":
                kwargs["tool_choice"] = {"type": "any"}

        response = self._client.messages.create(**kwargs)

        usage = SimpleUsage(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
        )

        msg_dict = self._translate_response(response)
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
        system_prompt, translated_msgs = self._translate_messages(messages)
        anthropic_tools = self._translate_tools(tools)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": translated_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
            if tool_choice == "auto":
                kwargs["tool_choice"] = {"type": "auto"}
            elif tool_choice == "none":
                kwargs["tool_choice"] = {"type": "none"}
            elif tool_choice == "required":
                kwargs["tool_choice"] = {"type": "any"}

        with self._client.messages.stream(**kwargs) as stream:
            current_tool_index = -1

            for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool_index += 1
                        yield {
                            "type": "tool_call_delta",
                            "index": current_tool_index,
                            "id": block.id,
                            "name": block.name,
                            "arguments": None,
                        }

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield {"type": "content_delta", "content": delta.text}
                    elif delta.type == "input_json_delta":
                        yield {
                            "type": "tool_call_delta",
                            "index": current_tool_index,
                            "id": None,
                            "name": None,
                            "arguments": delta.partial_json,
                        }

                elif event.type == "message_delta":
                    if hasattr(event, "usage") and event.usage:
                        yield {
                            "type": "usage",
                            "usage": SimpleUsage(
                                prompt_tokens=0,
                                completion_tokens=event.usage.output_tokens,
                            ),
                        }

                elif event.type == "message_start":
                    if hasattr(event.message, "usage") and event.message.usage:
                        yield {
                            "type": "usage",
                            "usage": SimpleUsage(
                                prompt_tokens=event.message.usage.input_tokens,
                                completion_tokens=0,
                            ),
                        }

        yield {"type": "done"}

    def name(self) -> str:
        return "anthropic"
