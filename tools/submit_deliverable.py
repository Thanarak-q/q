"""Submit deliverable tool for multi-agent pipeline.

Agents call this to signal completion and pass structured findings
to the next agent in the pipeline.  The pipeline coordinator
intercepts this call (similar to how the orchestrator intercepts
answer_user).
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, ToolParameter


class SubmitDeliverableTool(BaseTool):
    """Signal agent completion with structured deliverable data."""

    name = "submit_deliverable"
    description = (
        "Call this when you have completed your analysis and want to pass "
        "your findings to the next agent in the pipeline. Provide your "
        "results as a structured JSON object in the 'deliverable' parameter."
    )
    parameters = [
        ToolParameter(
            name="deliverable",
            type="string",
            description=(
                "JSON string containing your structured findings. "
                "Must include all key discoveries and recommendations."
            ),
        ),
        ToolParameter(
            name="summary",
            type="string",
            description="One-sentence summary of your findings.",
        ),
    ]

    def execute(self, **kwargs: Any) -> str:
        """Format the deliverable for logging.

        The actual deliverable is intercepted by BaseAgent._react_loop
        before this output is used by the LLM.
        """
        deliverable = kwargs.get("deliverable", "{}")
        summary = kwargs.get("summary", "")
        return f"Deliverable submitted: {summary}\n{deliverable}"
