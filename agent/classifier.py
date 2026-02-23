"""Challenge category and intent classifier.

Uses the LLM to classify a CTF challenge into one of the known categories
so the agent can load the appropriate playbook.  Also classifies the user's
intent so the agent knows when to stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from config import AppConfig
from utils.logger import get_logger


class Category(str, Enum):
    """Known CTF challenge categories."""

    WEB = "web"
    PWN = "pwn"
    CRYPTO = "crypto"
    REVERSE = "reverse"
    FORENSICS = "forensics"
    OSINT = "osint"
    MISC = "misc"


class UserIntent(str, Enum):
    """What the user actually wants from this session."""

    FIND_FLAG = "find_flag"           # default CTF: find and capture a flag
    ANSWER_QUESTION = "answer_question"  # user asks a specific question
    ANALYZE = "analyze"               # user wants analysis / report
    HELP_SOLVE = "help_solve"         # user wants guidance, not auto-solve


@dataclass
class IntentResult:
    """Result of intent classification."""

    intent: UserIntent
    stop_criteria: str  # human-readable description of what counts as "done"
    specific_question: str  # the concrete thing the user wants answered (may be empty)


CLASSIFICATION_PROMPT = """\
You are a CTF challenge classifier. Given the challenge description and any
associated file information, classify it into exactly ONE of these categories:

- web: Web exploitation, SQL injection, XSS, SSTI, SSRF, authentication bypass
- pwn: Binary exploitation, buffer overflow, format string, heap, ROP
- crypto: Cryptography, RSA, AES, XOR, hashing, PRNG
- reverse: Reverse engineering, disassembly, decompilation, keygen, crackme
- forensics: Digital forensics, steganography, PCAP analysis, memory dumps
- osint: Open source intelligence, geolocation, username search, domain investigation
- misc: Programming challenges, jail escapes, encoding puzzles

Respond with ONLY the category name (lowercase, one word).
"""

INTENT_PROMPT = """\
You are an assistant that determines user intent for a CTF-related task.

Given the user's input, classify their intent into exactly ONE of:

- find_flag: The user wants to find/capture a flag (default for CTF challenges).
  Examples: "solve this CTF challenge", "find the flag in this binary",
  "what is the flag?"
- answer_question: The user asks a specific question and wants a specific answer.
  Examples: "what is the attacker's IP?", "what tool was used?",
  "how many connections are there?", "what is the vulnerability?"
- analyze: The user wants a full analysis or report on the data.
  Examples: "analyze this pcap", "give me a forensics report",
  "what happened in this incident?"
- help_solve: The user wants guidance or hints, not autonomous solving.
  Examples: "help me solve this", "what should I try next?",
  "give me a hint"

Respond in exactly this format (3 lines):
intent: <one of find_flag, answer_question, analyze, help_solve>
question: <the specific thing the user wants answered, or empty>
stop: <one sentence describing when the agent should stop>
"""


def classify_challenge(
    description: str,
    file_info: str,
    client,
    config: AppConfig,
) -> Category:
    """Classify a CTF challenge into a category.

    Args:
        description: The challenge description text.
        file_info: Information about associated files (types, names).
        client: LLM provider (ProviderRouter or compatible).
        config: Application configuration.

    Returns:
        The predicted Category enum value.
    """
    log = get_logger()

    user_content = f"Challenge description: {description}"
    if file_info:
        user_content += f"\n\nAssociated files:\n{file_info}"

    from agent.planner import select_model_for_classification

    model = select_model_for_classification(config)

    try:
        result = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": CLASSIFICATION_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=10,
        )
        raw = result["message"]["content"].strip().lower()
        log.info(f"Classified challenge as: {raw}")

        # Map to Category enum
        for cat in Category:
            if cat.value in raw:
                return cat

        log.warning(f"Unrecognised category '{raw}', defaulting to misc")
        return Category.MISC

    except Exception as exc:
        log.error(f"Classification failed: {exc}, defaulting to misc")
        return Category.MISC


def get_playbook(category: Category) -> str:
    """Load the category skill file (.md) for a given category.

    Args:
        category: The challenge category.

    Returns:
        Skill file content string.
    """
    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    skill_file = skills_dir / f"{category.value}.md"

    if skill_file.exists():
        return skill_file.read_text()

    # Fallback to misc
    fallback = skills_dir / "misc.md"
    if fallback.exists():
        return fallback.read_text()

    return ""


def get_base_skills() -> str:
    """Load the base SKILL.md rules that all agents share.

    Returns:
        SKILL.md content string.
    """
    skill_file = Path(__file__).resolve().parent.parent / "prompts" / "categories" / "SKILL.md"
    if skill_file.exists():
        return skill_file.read_text()
    return ""


def classify_intent(
    description: str,
    client,
    config: AppConfig,
) -> IntentResult:
    """Classify the user's intent for this task.

    Args:
        description: The user's input / challenge description.
        client: LLM provider (ProviderRouter or compatible).
        config: Application configuration.

    Returns:
        IntentResult with intent, stop criteria, and specific question.
    """
    log = get_logger()
    from agent.planner import select_model_for_classification

    model = select_model_for_classification(config)

    try:
        result = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": INTENT_PROMPT},
                {"role": "user", "content": description},
            ],
            temperature=0.0,
            max_tokens=150,
        )
        raw = result["message"]["content"].strip()
        log.info(f"Intent classification raw: {raw}")

        # Parse the 3-line response
        intent = UserIntent.FIND_FLAG
        question = ""
        stop = "Find and report the flag."

        for line in raw.splitlines():
            line = line.strip()
            if line.lower().startswith("intent:"):
                val = line.split(":", 1)[1].strip().lower()
                for ui in UserIntent:
                    if ui.value == val:
                        intent = ui
                        break
            elif line.lower().startswith("question:"):
                question = line.split(":", 1)[1].strip()
            elif line.lower().startswith("stop:"):
                stop = line.split(":", 1)[1].strip()

        return IntentResult(intent=intent, stop_criteria=stop, specific_question=question)

    except Exception as exc:
        log.error(f"Intent classification failed: {exc}, defaulting to find_flag")
        return IntentResult(
            intent=UserIntent.FIND_FLAG,
            stop_criteria="Find and report the flag.",
            specific_question="",
        )


def max_steps_for_intent(intent: UserIntent, category: Category) -> int:
    """Return the maximum step budget based on intent and category.

    Single-agent architecture: tight budgets to force efficiency.
    Agent should aim for 3-6 steps; these are hard limits.

    Args:
        intent: Classified user intent.
        category: Challenge category.

    Returns:
        Maximum number of iterations.
    """
    if intent == UserIntent.ANSWER_QUESTION:
        return 10
    if intent == UserIntent.HELP_SOLVE:
        return 10
    if intent == UserIntent.ANALYZE:
        return 15
    # find_flag — always 15 max
    return 15
