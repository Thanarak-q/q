"""Recon agent — Phase 1 of the multi-agent pipeline.

Quickly examines the challenge: identifies files, detects category,
assesses difficulty, and suggests approaches.  Does NOT solve.
"""

from __future__ import annotations

import json
from typing import Any

from agent.base_agent import BaseAgent
from prompts.agent_prompts import RECON_SYSTEM_PROMPT


class ReconAgent(BaseAgent):
    """Challenge reconnaissance specialist.

    Uses the fast model (gpt-4o-mini) for cheap, quick reconnaissance.
    Limited to 8 steps — recon should be fast.
    """

    @property
    def role(self) -> str:
        return "recon"

    @property
    def model(self) -> str:
        return self._config.model.fast_model

    def get_allowed_tools(self) -> list[str]:
        return ["shell", "file_manager", "python_exec", "network", "submit_deliverable"]

    def get_max_steps(self) -> int:
        return self._config.pipeline.recon_max_steps

    def build_system_prompt(self, context: dict[str, Any]) -> str:
        return RECON_SYSTEM_PROMPT

    def build_initial_message(self, context: dict[str, Any]) -> str:
        parts: list[str] = []

        desc = context.get("description", "")
        parts.append(f"Challenge description:\n{desc}")

        # File info
        file_info = context.get("file_info", "")
        if file_info:
            parts.append(f"\nProvided files:\n{file_info}")

        # Target URL
        target_url = context.get("target_url")
        if target_url:
            parts.append(f"\nTarget URL: {target_url}")

        # Working directory
        workspace = context.get("workspace", ".")
        parts.append(f"\nWorking directory: {workspace}")

        parts.append(
            "\n\nExamine the challenge and call submit_deliverable "
            "with your reconnaissance findings."
        )

        return "\n".join(parts)
