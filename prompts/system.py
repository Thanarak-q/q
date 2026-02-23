"""Main system prompt for the CTF agent.

Loads base rules from SKILL.md and category-specific guides from .md files.
Supports intent-aware instructions so the agent knows when to stop.
"""

from __future__ import annotations

from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def get_base_prompt() -> str:
    """Core rules all agents follow (from SKILL.md)."""
    skill_file = _SKILLS_DIR / "SKILL.md"
    if skill_file.exists():
        return skill_file.read_text()
    return ""


def get_category_prompt(category: str) -> str:
    """Category-specific cheat sheet (.md file)."""
    path = _SKILLS_DIR / f"{category}.md"
    if path.exists():
        return path.read_text()
    # Fallback to misc
    fallback = _SKILLS_DIR / "misc.md"
    if fallback.exists():
        return fallback.read_text()
    return ""


def build_system_prompt(
    category: str = "",
    extra_context: str = "",
    intent_context: str = "",
    scope: dict | None = None,
    procedural_hints: str = "",
) -> str:
    """Build the complete system prompt with base rules + category guide.

    Args:
        category: Challenge category (web, pwn, crypto, etc.).
        extra_context: Any additional context (e.g., challenge metadata).
        intent_context: Intent-specific instructions (stop criteria, etc.).
        scope: Optional scope lock dict with challenge/category/goal/files.

    Returns:
        Complete system prompt string.
    """
    base = get_base_prompt()
    category_guide = get_category_prompt(category) if category else ""

    parts = ["You are Q, a CTF challenge solver.\n"]

    # Thinking enforcement
    parts.append("""## CRITICAL: Think Before Every Action

You MUST wrap your reasoning in <think> tags before EVERY tool call.
If you call a tool without <think> first, you are doing it wrong.

First <think> must include: GOAL, PLAN, SCOPE, DONE WHEN
Every subsequent <think> must include: LEARNED, HYPOTHESIS, NEXT, DONE?

When <think> says "DONE? yes" → call answer_user IMMEDIATELY.
""")

    parts.append(base)

    if intent_context:
        parts.append(f"\n## User Intent\n\n{intent_context}")
    if procedural_hints:
        parts.append(f"\n{procedural_hints}")
    if category_guide:
        parts.append(f"\n## Reference Guide for {category}\n\n{category_guide}")
    if extra_context:
        parts.append(f"\n## Additional Context\n\n{extra_context}")

    # Scope lock — prevent agent from drifting to other challenges
    if scope:
        scope_lines = ["\n## Your Scope (DO NOT go outside this)"]
        if scope.get("challenge"):
            scope_lines.append(f"Challenge: {scope['challenge']}")
        if scope.get("category"):
            scope_lines.append(f"Category: {scope['category']}")
        if scope.get("goal"):
            scope_lines.append(f"Goal: {scope['goal']}")
        if scope.get("files"):
            scope_lines.append(f"Relevant files: {', '.join(scope['files'])}")
        scope_lines.append(
            "\nYou are solving ONE challenge. Do not touch files or tasks "
            "outside this scope. If you find the flag/answer, stop immediately."
        )
        parts.append("\n".join(scope_lines))

    parts.append("""
REMEMBER:
- Solve in 3-6 commands. You have max 15 but you should NOT need them.
- When you have the answer, call answer_user IMMEDIATELY.
- When you find a flag, report it IMMEDIATELY. Do NOT continue after finding it.
- Do NOT explore further after finding the answer.
- Do NOT start working on a different challenge or file after solving.
- If you are on your LAST STEP, you MUST provide your best answer with answer_user tool. Never end without answering.
""")

    return "\n".join(parts)
