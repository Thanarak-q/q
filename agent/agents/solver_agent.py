"""Solver agent — Phase 3 of the multi-agent pipeline.

Receives a hypothesis to pursue and attempts to solve the challenge.
Multiple instances may run in parallel (one per hypothesis).
"""

from __future__ import annotations

import json
from typing import Any

from agent.base_agent import BaseAgent
from agent.classifier import get_playbook, Category
from prompts.agent_prompts import get_solver_prompt


class SolverAgent(BaseAgent):
    """Challenge solver and exploit developer.

    Gets the largest step budget.  Uses gpt-4o by default,
    upgraded to o3 for hard challenges.
    """

    def __init__(self, *, hypothesis: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._hypothesis = hypothesis

    @property
    def role(self) -> str:
        return "solver"

    @property
    def model(self) -> str:
        # Escalate to reasoning model for hard challenges
        difficulty = getattr(self, "_difficulty", "medium")
        if difficulty == "hard":
            return self._config.model.reasoning_model
        return self._config.model.default_model

    def set_difficulty(self, difficulty: str) -> None:
        """Set difficulty for model selection."""
        self._difficulty = difficulty

    def get_allowed_tools(self) -> list[str]:
        return [
            "shell",
            "file_manager",
            "network",
            "python_exec",
            "answer_user",
            "submit_deliverable",
        ]

    def get_max_steps(self) -> int:
        return self._config.pipeline.solver_max_steps

    def build_system_prompt(self, context: dict[str, Any]) -> str:
        category_str = context.get("category", "misc")
        playbook = ""
        for cat in Category:
            if cat.value == category_str:
                playbook = get_playbook(cat)
                break

        stop_criteria = context.get(
            "stop_criteria", "Find the flag or answer the question."
        )
        return get_solver_prompt(
            category_playbook=playbook,
            stop_criteria=stop_criteria,
        )

    def build_initial_message(self, context: dict[str, Any]) -> str:
        parts: list[str] = []

        desc = context.get("description", "")
        parts.append(f"Challenge description:\n{desc}")

        # Recon data
        recon = context.get("recon_deliverable", {})
        if recon:
            parts.append(f"\n## Recon Findings\n{json.dumps(recon, indent=2)}")

        # Analyst data
        analyst = context.get("analyst_deliverable", {})
        if analyst:
            parts.append(f"\n## Analysis Report\n{json.dumps(analyst, indent=2)}")

        # Specific hypothesis to pursue
        if self._hypothesis:
            parts.append(
                f"\n## Your Assigned Hypothesis\n"
                f"{json.dumps(self._hypothesis, indent=2)}\n\n"
                f"Focus on this specific approach."
            )

        # Intent-specific instructions
        intent = context.get("intent", "find_flag")
        question = context.get("specific_question", "")
        if intent == "answer_question" and question:
            parts.append(
                f"\n## User Question\n{question}\n"
                f"Call answer_user when you have the answer."
            )
        elif intent == "find_flag":
            parts.append(
                "\n\nFind the flag. Call answer_user with the flag when found."
            )

        # Working directory
        workspace = context.get("workspace", ".")
        parts.append(f"\nWorking directory: {workspace}")

        return "\n".join(parts)
