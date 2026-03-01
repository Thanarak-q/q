"""Google (Gemini) LLM provider with message format translation."""
from __future__ import annotations

import json
from typing import Any, Iterator

from agent.providers.base import LLMProvider, SimpleUsage


class GoogleProvider(LLMProvider):
    """Google Gemini API provider (gemini-2.0-flash, gemini-2.5-pro, etc.)."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._genai: Any = None

    def _get_genai(self) -> Any:
        if self._genai is None:
            try:
                import google.generativeai as genai  # type: ignore
                genai.configure(api_key=self._api_key)
                self._genai = genai
            except ImportError:
                raise ImportError(
                    "google-generativeai package required for Google provider. "
                    "Install with: pip install google-generativeai"
                )
        return self._genai

    # ------------------------------------------------------------------
    # Format translation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _translate_tools(tools: list[dict[str, Any]] | None) -> list[Any] | None:
        """OpenAI tool format → Google FunctionDeclaration list."""
        if not tools:
            return None
        try:
            import google.generativeai.types as gtypes  # type: ignore
        except ImportError:
            return None

        declarations = []
        for tool in tools:
            func = tool.get("function", {})
            declarations.append(
                gtypes.FunctionDeclaration(
                    name=func.get("name", ""),
                    description=func.get("description", ""),
                    parameters=func.get("parameters", {}),
                )
            )
        return [gtypes.Tool(function_declarations=declarations)]

    @staticmethod
    def _translate_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """OpenAI-format messages → (system_instruction, google contents).

        Builds a tool_id → name map from assistant messages so that
        tool result messages can include the required function name.
        """
        system = ""
        contents: list[dict[str, Any]] = []
        tool_id_to_name: dict[str, str] = {}

        for msg in messages:
            role = msg.get("role", "")

            if role == "system":
                system = msg.get("content", "")
                continue

            if role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": msg.get("content", "") or ""}],
                })
                continue

            if role == "assistant":
                parts: list[dict[str, Any]] = []
                text = msg.get("content") or ""
                if text:
                    parts.append({"text": text})
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    name = func.get("name", "tool")
                    tool_id_to_name[tc.get("id", "")] = name
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    parts.append({
                        "function_call": {"name": name, "args": args},
                    })
                if parts:
                    contents.append({"role": "model", "parts": parts})
                continue

            if role == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                func_name = tool_id_to_name.get(tool_call_id, "tool")
                result_content = msg.get("content", "") or ""
                fn_response = {
                    "function_response": {
                        "name": func_name,
                        "response": {"result": result_content},
                    }
                }
                if contents and contents[-1]["role"] == "user":
                    contents[-1]["parts"].append(fn_response)
                else:
                    contents.append({"role": "user", "parts": [fn_response]})
                continue

        return system, contents

    @staticmethod
    def _translate_response(candidate: Any) -> tuple[dict[str, Any], SimpleUsage]:
        """Google candidate → internal (OpenAI-like) message dict."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for part in candidate.content.parts:
            if hasattr(part, "text") and part.text:
                text_parts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc and fc.name:
                tool_calls.append({
                    "id": f"call_{fc.name}_{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(dict(fc.args)),
                    },
                })

        msg: dict[str, Any] = {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None,
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls

        return msg, SimpleUsage()

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
        genai = self._get_genai()
        system, contents = self._translate_messages(messages)
        google_tools = self._translate_tools(tools)

        kwargs: dict[str, Any] = {
            "generation_config": {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        }
        if system:
            kwargs["system_instruction"] = system
        if google_tools:
            kwargs["tools"] = google_tools

        m = genai.GenerativeModel(model, **kwargs)
        response = m.generate_content(contents)

        msg, usage = self._translate_response(response.candidates[0])

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage = SimpleUsage(
                prompt_tokens=getattr(um, "prompt_token_count", 0) or 0,
                completion_tokens=getattr(um, "candidates_token_count", 0) or 0,
            )

        return {"message": msg, "usage": usage}

    def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Iterator[dict[str, Any]]:
        genai = self._get_genai()
        system, contents = self._translate_messages(messages)
        google_tools = self._translate_tools(tools)

        kwargs: dict[str, Any] = {
            "generation_config": {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        }
        if system:
            kwargs["system_instruction"] = system
        if google_tools:
            kwargs["tools"] = google_tools

        m = genai.GenerativeModel(model, **kwargs)
        stream = m.generate_content(contents, stream=True)

        tool_index = -1
        for chunk in stream:
            if not chunk.candidates:
                continue
            for part in chunk.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    yield {"type": "content_delta", "content": part.text}
                fc = getattr(part, "function_call", None)
                if fc and fc.name:
                    tool_index += 1
                    yield {
                        "type": "tool_call_delta",
                        "index": tool_index,
                        "id": f"call_{fc.name}_{tool_index}",
                        "name": fc.name,
                        "arguments": json.dumps(dict(fc.args)),
                    }

        yield {"type": "done"}

    def name(self) -> str:
        return "google"
