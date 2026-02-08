"""Conversation context manager.

Manages the message history, handles context window limits by
summarizing older messages, and maintains the agent's scratchpad.
"""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from config import AppConfig
from prompts.strategies import CONTEXT_SUMMARY_REQUEST
from utils.logger import get_logger
from utils.token_counter import count_message_tokens, context_limit_for_model


class ContextManager:
    """Manages conversation history and context window for the agent.

    Handles message accumulation, automatic summarization when
    approaching token limits, and a persistent scratchpad for
    tracking discoveries.
    """

    def __init__(self, client: OpenAI, config: AppConfig) -> None:
        """Initialise the context manager.

        Args:
            client: OpenAI API client for summarization calls.
            config: Application configuration.
        """
        self._client = client
        self._config = config
        self._messages: list[dict[str, Any]] = []
        self._scratchpad: list[str] = []
        self._log = get_logger()
        self._model = config.model.default_model

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Return the current message history.

        Returns:
            List of message dicts.
        """
        return self._messages

    @property
    def scratchpad(self) -> str:
        """Return the scratchpad contents as a single string.

        Returns:
            Newline-joined scratchpad entries.
        """
        return "\n".join(self._scratchpad)

    def set_system_prompt(self, prompt: str) -> None:
        """Set or replace the system message.

        Args:
            prompt: System prompt text.
        """
        if self._messages and self._messages[0]["role"] == "system":
            self._messages[0]["content"] = prompt
        else:
            self._messages.insert(0, {"role": "system", "content": prompt})

    def add_user_message(self, content: str) -> None:
        """Append a user message.

        Args:
            content: User message text.
        """
        self._messages.append({"role": "user", "content": content})

    def add_assistant_message(self, message: dict[str, Any]) -> None:
        """Append a raw assistant message dict (may contain tool_calls).

        Args:
            message: The full assistant message dict from the API response.
        """
        self._messages.append(message)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        """Append a tool result message.

        Args:
            tool_call_id: The ID of the tool call this responds to.
            content: Tool output text.
        """
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
        )

    def add_scratchpad_entry(self, entry: str) -> None:
        """Add a note to the scratchpad.

        Args:
            entry: Discovery or observation to record.
        """
        self._scratchpad.append(entry)
        self._log.debug(f"Scratchpad entry: {entry}")

    def token_count(self) -> int:
        """Count current tokens used.

        Returns:
            Estimated token count.
        """
        return count_message_tokens(self._messages, self._model)

    def needs_summarization(self) -> bool:
        """Check if the context is approaching the token limit.

        Returns:
            True if summarization is needed.
        """
        used = self.token_count()
        limit = context_limit_for_model(self._model)
        threshold = limit * self._config.agent.context_limit_percent // 100
        return used >= threshold

    def summarize_history(self) -> None:
        """Summarize older messages to free up context space.

        Keeps the system prompt, the last 6 messages, and replaces
        everything in between with a summary.
        """
        self._log.info("Summarizing conversation history to save context...")

        if len(self._messages) <= 8:
            self._log.debug("Too few messages to summarize")
            return

        # Extract messages to summarize (skip system + keep last 6)
        system_msg = self._messages[0] if self._messages[0]["role"] == "system" else None
        start_idx = 1 if system_msg else 0
        keep_recent = 6
        to_summarize = self._messages[start_idx:-keep_recent]
        recent = self._messages[-keep_recent:]

        if not to_summarize:
            return

        # Build summary request
        summary_text = ""
        for msg in to_summarize:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                summary_text += f"[{role}]: {content[:500]}\n"

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=0.1,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": CONTEXT_SUMMARY_REQUEST},
                    {"role": "user", "content": summary_text},
                ],
            )
            summary = response.choices[0].message.content.strip()
        except Exception as exc:
            self._log.error(f"Summarization failed: {exc}")
            summary = "(Summary unavailable due to error)"

        # Rebuild messages
        scratchpad_note = ""
        if self._scratchpad:
            scratchpad_note = f"\n\nScratchpad:\n{self.scratchpad}"

        summary_message = {
            "role": "user",
            "content": (
                f"[CONTEXT SUMMARY of previous steps]\n\n"
                f"{summary}{scratchpad_note}\n\n"
                f"[END SUMMARY — continuing from here]"
            ),
        }

        new_messages: list[dict[str, Any]] = []
        if system_msg:
            new_messages.append(system_msg)
        new_messages.append(summary_message)
        new_messages.extend(recent)

        old_count = len(self._messages)
        self._messages = new_messages
        self._log.info(
            f"Summarized {old_count} messages down to {len(self._messages)}"
        )
