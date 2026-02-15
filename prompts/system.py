"""Main system prompt for the CTF agent.

Loads base rules from SKILL.md and category-specific guides from .md files.
Supports intent-aware instructions so the agent knows when to stop.
"""

from __future__ import annotations

from pathlib import Path

_CATEGORIES_DIR = Path(__file__).resolve().parent / "categories"


def get_base_prompt() -> str:
    """Core rules all agents follow (from SKILL.md)."""
    skill_file = _CATEGORIES_DIR / "SKILL.md"
    if skill_file.exists():
        return skill_file.read_text()
    return ""


def get_category_prompt(category: str) -> str:
    """Category-specific cheat sheet (.md file)."""
    path = _CATEGORIES_DIR / f"{category}.md"
    if path.exists():
        return path.read_text()
    # Fallback to misc
    fallback = _CATEGORIES_DIR / "misc.md"
    if fallback.exists():
        return fallback.read_text()
    return ""


def build_system_prompt(
    category: str = "",
    extra_context: str = "",
    intent_context: str = "",
) -> str:
    """Build the complete system prompt with base rules + category guide.

    Args:
        category: Challenge category (web, pwn, crypto, etc.).
        extra_context: Any additional context (e.g., challenge metadata).
        intent_context: Intent-specific instructions (stop criteria, etc.).

    Returns:
        Complete system prompt string.
    """
    base = get_base_prompt()
    category_guide = get_category_prompt(category) if category else ""

    parts = ["You are Q, a CTF challenge solver.\n"]
    parts.append(base)

    if intent_context:
        parts.append(f"\n## User Intent\n\n{intent_context}")
    if category_guide:
        parts.append(f"\n## Reference Guide for {category}\n\n{category_guide}")
    if extra_context:
        parts.append(f"\n## Additional Context\n\n{extra_context}")

    parts.append("""
REMEMBER:
- Solve in 3-6 commands. You have max 15 but you should NOT need them.
- When you have the answer, call answer_user IMMEDIATELY.
- When you find a flag, report it IMMEDIATELY.
- Do NOT explore further after finding the answer.
- If you are on your LAST STEP, you MUST provide your best answer with answer_user tool. Never end without answering.
""")

    return "\n".join(parts)
