"""Analyst agent — Phase 2 of the multi-agent pipeline.

Performs deep analysis on the challenge based on recon findings.
Generates ranked hypotheses for the solver agent.
Skipped on fast-path when difficulty is "easy".
"""

from __future__ import annotations

import json
from typing import Any

from agent.base_agent import BaseAgent
from agent.classifier import get_playbook, Category
from prompts.agent_prompts import get_analyst_prompt


class AnalystAgent(BaseAgent):
    """Vulnerability and data analyst.

    Uses the default model (gpt-4o) for deeper reasoning.
    """

    @property
    def role(self) -> str:
        return "analyst"

    @property
    def model(self) -> str:
        return self._config.model.default_model

    def get_allowed_tools(self) -> list[str]:
        return ["shell", "file_manager", "python_exec", "submit_deliverable"]

    def get_max_steps(self) -> int:
        return self._config.pipeline.analyst_max_steps

    def build_system_prompt(self, context: dict[str, Any]) -> str:
        # Inject category playbook if available
        category_str = context.get("category", "misc")
        playbook = ""
        for cat in Category:
            if cat.value == category_str:
                playbook = get_playbook(cat)
                break
        return get_analyst_prompt(category_playbook=playbook)

    def build_initial_message(self, context: dict[str, Any]) -> str:
        parts: list[str] = []

        desc = context.get("description", "")
        parts.append(f"Challenge description:\n{desc}")

        # Recon deliverable
        recon = context.get("recon_deliverable", {})
        if recon:
            parts.append(f"\n## Recon Findings\n{json.dumps(recon, indent=2)}")

        # Plan
        plan = context.get("plan", "")
        if plan:
            parts.append(f"\n## Attack Plan\n{plan}")

        # Working directory
        workspace = context.get("workspace", ".")
        parts.append(f"\nWorking directory: {workspace}")

        parts.append(
            "\n\nAnalyze the challenge deeply and call submit_deliverable "
            "with your hypotheses and findings."
        )

        return "\n".join(parts)
