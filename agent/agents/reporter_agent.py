"""Reporter agent — Phase 4 of the multi-agent pipeline.

Compiles all pipeline findings into a structured markdown report.
Uses the fast model since this is just writing, not reasoning.
"""

from __future__ import annotations

import json
from typing import Any

from agent.base_agent import BaseAgent
from prompts.agent_prompts import REPORTER_SYSTEM_PROMPT


class ReporterAgent(BaseAgent):
    """Technical report writer.

    Takes all pipeline deliverables and produces a structured writeup.
    Only uses submit_deliverable (no tool execution).
    """

    @property
    def role(self) -> str:
        return "reporter"

    @property
    def model(self) -> str:
        return self._config.model.fast_model

    def get_allowed_tools(self) -> list[str]:
        return ["submit_deliverable"]

    def get_max_steps(self) -> int:
        return self._config.pipeline.reporter_max_steps

    def build_system_prompt(self, context: dict[str, Any]) -> str:
        return REPORTER_SYSTEM_PROMPT

    def build_initial_message(self, context: dict[str, Any]) -> str:
        parts: list[str] = []

        desc = context.get("description", "")
        parts.append(f"## Challenge\n{desc}")

        # Collect all deliverables
        recon = context.get("recon_deliverable", {})
        if recon:
            parts.append(f"\n## Recon Findings\n{json.dumps(recon, indent=2)}")

        analyst = context.get("analyst_deliverable", {})
        if analyst:
            parts.append(f"\n## Analysis Report\n{json.dumps(analyst, indent=2)}")

        solver = context.get("solver_deliverable", {})
        if solver:
            parts.append(f"\n## Solver Result\n{json.dumps(solver, indent=2)}")

        # Result metadata
        flags = context.get("flags", [])
        answer = context.get("answer", "")
        if flags:
            parts.append(f"\n## Flags Found\n{', '.join(flags)}")
        if answer:
            parts.append(f"\n## Answer\n{answer}")

        parts.append(
            "\n\nCompile this into a professional markdown report "
            "and call submit_deliverable with the report."
        )

        return "\n".join(parts)
