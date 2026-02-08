"""Challenge planning and strategy pivot module.

Generates initial attack plans and manages the graduated pivot system
that detects when the agent is stuck and escalates strategies.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

from openai import OpenAI

from agent.classifier import Category
from config import AppConfig
from utils.logger import get_logger

PLANNER_PROMPT = """\
You are a CTF challenge planning assistant. Given a challenge description,
its category, and information about provided files, create a concise
attack plan.

Your plan should:
1. List 3-5 numbered steps to attempt, in priority order
2. For each step, specify which tool to use and what to look for
3. Include a fallback strategy if the primary approach fails
4. Be specific — mention exact commands, techniques, or scripts to try

Keep the plan under 300 words. Be direct and actionable.
"""


class PivotLevel(Enum):
    """Graduated pivot escalation levels."""

    NONE = 0
    BASIC_PIVOT = auto()       # change approach within same category
    STEP_BACK = auto()         # full re-evaluation
    APPROACH_SWAP = auto()     # static ↔ dynamic, manual ↔ automated
    RECLASSIFY = auto()        # maybe wrong category entirely
    MODEL_ESCALATION = auto()  # switch to reasoning model
    ASK_USER = auto()          # give up autonomous solving, ask for hint


class PivotManager:
    """Manages strategy pivoting when the agent stalls.

    Tracks stall detection, decides which pivot level to apply, and
    whether to escalate the model.
    """

    def __init__(self, stall_threshold: int = 5) -> None:
        """Initialise the pivot manager.

        Args:
            stall_threshold: Iterations without progress before first pivot.
        """
        self._stall_threshold = stall_threshold
        self._last_progress_at: int = 0
        self._pivot_count: int = 0
        self._current_level: PivotLevel = PivotLevel.NONE
        self._model_escalated: bool = False
        self._asked_user: bool = False
        self._log = get_logger()

    @property
    def pivot_count(self) -> int:
        """Number of pivots performed so far."""
        return self._pivot_count

    @property
    def current_level(self) -> PivotLevel:
        """The most recent pivot level applied."""
        return self._current_level

    @property
    def model_escalated(self) -> bool:
        """Whether the model has been escalated to reasoning tier."""
        return self._model_escalated

    @property
    def should_ask_user(self) -> bool:
        """Whether the agent should ask the user for a hint."""
        return self._asked_user

    def record_progress(self, iteration: int) -> None:
        """Record that meaningful progress was made.

        Args:
            iteration: The current iteration number.
        """
        self._last_progress_at = iteration

    def check_stall(self, current_iteration: int) -> PivotLevel:
        """Check if the agent is stalled and determine pivot level.

        Args:
            current_iteration: The current iteration number.

        Returns:
            The pivot level to apply, or NONE if not stalled.
        """
        stall_duration = current_iteration - self._last_progress_at
        if stall_duration < self._stall_threshold:
            return PivotLevel.NONE

        # Escalate based on how many pivots we've already done
        if self._pivot_count == 0:
            level = PivotLevel.BASIC_PIVOT
        elif self._pivot_count == 1:
            level = PivotLevel.STEP_BACK
        elif self._pivot_count == 2:
            level = PivotLevel.APPROACH_SWAP
        elif self._pivot_count == 3:
            level = PivotLevel.RECLASSIFY
        elif self._pivot_count == 4 and not self._model_escalated:
            level = PivotLevel.MODEL_ESCALATION
            self._model_escalated = True
        else:
            level = PivotLevel.ASK_USER
            self._asked_user = True

        self._pivot_count += 1
        self._current_level = level
        self._last_progress_at = current_iteration
        self._log.info(f"Pivot #{self._pivot_count}: {level.name}")
        return level

    def get_pivot_prompt(self, level: PivotLevel) -> str:
        """Get the appropriate pivot prompt for the given level.

        Args:
            level: The pivot level to get the prompt for.

        Returns:
            The pivot prompt string.
        """
        from prompts.strategies import (
            APPROACH_SWAP_PROMPT,
            MODEL_ESCALATION_PROMPT,
            PIVOT_SEQUENCE,
            RECLASSIFY_PROMPT,
            STALL_PIVOT_PROMPT,
            STEP_BACK_PROMPT,
        )

        mapping = {
            PivotLevel.BASIC_PIVOT: STALL_PIVOT_PROMPT,
            PivotLevel.STEP_BACK: STEP_BACK_PROMPT,
            PivotLevel.APPROACH_SWAP: APPROACH_SWAP_PROMPT,
            PivotLevel.RECLASSIFY: RECLASSIFY_PROMPT,
            PivotLevel.MODEL_ESCALATION: MODEL_ESCALATION_PROMPT,
            PivotLevel.ASK_USER: (
                "The agent has exhausted its strategies. "
                "Please provide a hint to continue."
            ),
        }
        return mapping.get(level, STALL_PIVOT_PROMPT)


def select_model_for_task(
    category: Category,
    config: AppConfig,
    is_escalated: bool = False,
) -> str:
    """Choose the appropriate model based on task characteristics.

    Args:
        category: The challenge category.
        config: Application configuration.
        is_escalated: Whether the model has been escalated.

    Returns:
        Model identifier string.
    """
    if is_escalated:
        return config.model.reasoning_model

    # Categories that benefit from deeper reasoning
    hard_categories = {Category.CRYPTO, Category.PWN}
    if category in hard_categories:
        return config.model.default_model  # start with default, escalate later

    return config.model.default_model


def select_model_for_classification(config: AppConfig) -> str:
    """Choose the model for classification (use fast model).

    Args:
        config: Application configuration.

    Returns:
        Model identifier string.
    """
    return config.model.fast_model


def create_plan(
    description: str,
    category: Category,
    file_info: str,
    client: OpenAI,
    config: AppConfig,
) -> str:
    """Generate an initial attack plan for the challenge.

    Args:
        description: Challenge description.
        category: Classified category.
        file_info: File type/name information.
        client: OpenAI API client.
        config: Application configuration.

    Returns:
        Plan text string.
    """
    log = get_logger()

    user_content = (
        f"Category: {category.value}\n\n"
        f"Challenge description:\n{description}\n\n"
        f"Available files:\n{file_info or '(none)'}"
    )

    model = config.model.fast_model

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.3,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        plan = response.choices[0].message.content.strip()
        log.info(f"Generated plan for {category.value} challenge (model={model})")
        return plan

    except Exception as exc:
        log.error(f"Planning failed: {exc}")
        return (
            "Planning failed. Proceeding with general approach:\n"
            "1. Examine provided files\n"
            "2. Identify vulnerability or hidden data\n"
            "3. Develop and test exploit/extraction\n"
            "4. Extract the flag"
        )
