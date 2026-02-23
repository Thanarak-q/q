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


class FailureType(Enum):
    """Types of failure the agent can encounter."""

    TOOL_ERROR = "tool_error"
    NO_OUTPUT = "no_output"
    WRONG_CATEGORY = "wrong_category"
    PARTIAL_PROGRESS = "partial_progress"
    REPEATED_ACTION = "repeated_action"


FAILURE_PIVOT_PROMPTS: dict[FailureType, str] = {
    FailureType.TOOL_ERROR: (
        "The last command failed with an error. Analyze the error message "
        "and try a different command or fix the syntax."
    ),
    FailureType.NO_OUTPUT: (
        "The last command produced no useful output. Try a broader search, "
        "different file, or different approach entirely."
    ),
    FailureType.REPEATED_ACTION: (
        "You're repeating similar actions. STOP and try a completely "
        "different technique or tool."
    ),
    FailureType.PARTIAL_PROGRESS: (
        "You found some data but haven't reached the flag. Focus on what "
        "you found and dig deeper into it."
    ),
    FailureType.WRONG_CATEGORY: (
        "Multiple approaches have failed. The challenge category might be "
        "wrong. Reconsider what type of challenge this really is."
    ),
}


def classify_failure(
    recent_outputs: list[str],
    recent_tool_calls: list[dict[str, Any]],
) -> FailureType:
    """Classify the type of failure based on recent outputs and tool calls.

    Args:
        recent_outputs: Last few tool outputs.
        recent_tool_calls: Last few tool call dicts with 'name' and 'args'.

    Returns:
        The classified FailureType.
    """
    error_keywords = (
        "error", "traceback", "exception", "failed", "permission denied",
    )

    # TOOL_ERROR: any recent output contains error indicators
    if recent_outputs:
        last_output = recent_outputs[-1].lower()
        if any(kw in last_output for kw in error_keywords):
            return FailureType.TOOL_ERROR

    # NO_OUTPUT: last output is empty or very short
    if recent_outputs:
        last_output = recent_outputs[-1].strip()
        if len(last_output) < 10:
            return FailureType.NO_OUTPUT

    # REPEATED_ACTION: last 2 tool calls have same name and similar args
    if len(recent_tool_calls) >= 2:
        tc1 = recent_tool_calls[-1]
        tc2 = recent_tool_calls[-2]
        if tc1.get("name") == tc2.get("name"):
            args1 = str(tc1.get("args", ""))
            args2 = str(tc2.get("args", ""))
            # Simple similarity: same tool + args share > 60% characters
            if args1 and args2:
                common = sum(1 for a, b in zip(args1, args2) if a == b)
                max_len = max(len(args1), len(args2))
                if max_len > 0 and common / max_len > 0.6:
                    return FailureType.REPEATED_ACTION

    # WRONG_CATEGORY: 3+ different tool names tried with no progress
    if len(recent_tool_calls) >= 3:
        unique_tools = {tc.get("name") for tc in recent_tool_calls[-4:]}
        if len(unique_tools) >= 3:
            # Check if any output has flag-like patterns
            has_flag_hint = False
            for out in recent_outputs[-3:]:
                out_lower = out.lower()
                if any(kw in out_lower for kw in ("flag{", "ctf{", "flag:")):
                    has_flag_hint = True
                    break
            if not has_flag_hint:
                return FailureType.WRONG_CATEGORY

    # PARTIAL_PROGRESS: default when there's data but no flag
    return FailureType.PARTIAL_PROGRESS


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

    def get_targeted_pivot(
        self,
        level: PivotLevel,
        recent_outputs: list[str],
        recent_tool_calls: list[dict[str, Any]],
    ) -> str:
        """Get a failure-type-aware pivot prompt.

        First classifies the failure type from recent context, then
        returns targeted advice combined with the level-appropriate
        escalation prompt.

        Args:
            level: The pivot escalation level.
            recent_outputs: Recent tool outputs for failure classification.
            recent_tool_calls: Recent tool call dicts.

        Returns:
            Targeted pivot prompt string.
        """
        # Get the base escalation prompt for this level
        base_prompt = self.get_pivot_prompt(level)

        # Classify the failure and get targeted advice
        if not recent_outputs and not recent_tool_calls:
            return base_prompt

        failure_type = classify_failure(recent_outputs, recent_tool_calls)
        targeted_advice = FAILURE_PIVOT_PROMPTS.get(failure_type, "")

        self._log.info(
            f"Failure classified as {failure_type.value} "
            f"(pivot level: {level.name})"
        )

        if targeted_advice:
            return f"{targeted_advice}\n\n{base_prompt}"
        return base_prompt


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
