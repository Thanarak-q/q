"""Challenge category classifier.

Uses the LLM to classify a CTF challenge into one of the known categories
so the agent can load the appropriate playbook.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from openai import OpenAI

from agent.planner import select_model_for_classification
from config import AppConfig
from utils.logger import get_logger


class Category(str, Enum):
    """Known CTF challenge categories."""

    WEB = "web"
    PWN = "pwn"
    CRYPTO = "crypto"
    REVERSE = "reverse"
    FORENSICS = "forensics"
    MISC = "misc"


CLASSIFICATION_PROMPT = """\
You are a CTF challenge classifier. Given the challenge description and any
associated file information, classify it into exactly ONE of these categories:

- web: Web exploitation, SQL injection, XSS, SSTI, SSRF, authentication bypass
- pwn: Binary exploitation, buffer overflow, format string, heap, ROP
- crypto: Cryptography, RSA, AES, XOR, hashing, PRNG
- reverse: Reverse engineering, disassembly, decompilation, keygen, crackme
- forensics: Digital forensics, steganography, PCAP analysis, memory dumps
- misc: Programming challenges, OSINT, jail escapes, encoding puzzles

Respond with ONLY the category name (lowercase, one word).
"""


def classify_challenge(
    description: str,
    file_info: str,
    client: OpenAI,
    config: AppConfig,
) -> Category:
    """Classify a CTF challenge into a category.

    Args:
        description: The challenge description text.
        file_info: Information about associated files (types, names).
        client: OpenAI API client.
        config: Application configuration.

    Returns:
        The predicted Category enum value.
    """
    log = get_logger()

    user_content = f"Challenge description: {description}"
    if file_info:
        user_content += f"\n\nAssociated files:\n{file_info}"

    model = select_model_for_classification(config)

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=10,
            messages=[
                {"role": "system", "content": CLASSIFICATION_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content.strip().lower()
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
    """Load the playbook for a given category.

    Args:
        category: The challenge category.

    Returns:
        Playbook text string.
    """
    playbook_map: dict[Category, str] = {}

    # Import playbooks lazily to avoid circular imports
    from prompts.categories import web, pwn, crypto, reverse, forensics, misc

    playbook_map[Category.WEB] = web.PLAYBOOK
    playbook_map[Category.PWN] = pwn.PLAYBOOK
    playbook_map[Category.CRYPTO] = crypto.PLAYBOOK
    playbook_map[Category.REVERSE] = reverse.PLAYBOOK
    playbook_map[Category.FORENSICS] = forensics.PLAYBOOK
    playbook_map[Category.MISC] = misc.PLAYBOOK

    return playbook_map.get(category, misc.PLAYBOOK)
