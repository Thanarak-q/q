"""Answer-user tool — lets the agent provide a final answer.

When the agent has enough information to answer the user's question
(whether that is a flag, an IP address, a technique name, or any other
analysis result), it calls this tool and the orchestrator stops the loop.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, ToolParameter


class AnswerUserTool(BaseTool):
    """Provide a final answer to the user and end the solve loop."""

    name = "answer_user"
    description = (
        "Use this when you have enough information to answer the user's "
        "question. Call this to provide your final answer. Not every "
        "challenge requires finding a flag — sometimes the user wants "
        "analysis, an IP address, a technique name, or other specific "
        "information. When you call this tool the conversation ends, so "
        "make sure your answer is complete."
    )
    parameters = [
        ToolParameter(
            name="answer",
            type="string",
            description="Your final answer to the user's question.",
        ),
        ToolParameter(
            name="confidence",
            type="string",
            description="How confident you are in the answer.",
            enum=["high", "medium", "low"],
        ),
        ToolParameter(
            name="flag",
            type="string",
            description=(
                "If a flag was found, include it here. "
                "Leave empty or omit if no flag was found."
            ),
            required=False,
        ),
    ]

    def execute(self, **kwargs: Any) -> str:
        """Return the answer as plain text.

        The orchestrator intercepts this tool call before it reaches
        normal tool-result processing, but we still produce a
        human-readable string in case it is logged.
        """
        answer: str = kwargs.get("answer", "")
        confidence: str = kwargs.get("confidence", "medium")
        flag: str = kwargs.get("flag", "") or ""

        parts = [f"Answer (confidence={confidence}): {answer}"]
        if flag:
            parts.append(f"Flag: {flag}")
        return "\n".join(parts)
