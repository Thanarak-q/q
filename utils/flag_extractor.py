"""Flag extraction utilities.

Searches text for common CTF flag formats using regex patterns.
"""

from __future__ import annotations

import re
from typing import Optional

# Common CTF flag patterns.  Order matters: more specific first.
DEFAULT_FLAG_PATTERNS: list[str] = [
    r"flag\{[^\}]+\}",
    r"FLAG\{[^\}]+\}",
    r"ctf\{[^\}]+\}",
    r"CTF\{[^\}]+\}",
    r"htb\{[^\}]+\}",
    r"HTB\{[^\}]+\}",
    r"picoCTF\{[^\}]+\}",
    r"ictf\{[^\}]+\}",
    r"DUCTF\{[^\}]+\}",
    r"zer0pts\{[^\}]+\}",
    r"SECCON\{[^\}]+\}",
    r"corctf\{[^\}]+\}",
]


def extract_flags(
    text: str,
    custom_pattern: Optional[str] = None,
) -> list[str]:
    """Extract all CTF flags found in text.

    Args:
        text: The text to search for flags.
        custom_pattern: Optional additional regex pattern to try.

    Returns:
        List of unique flag strings found.
    """
    patterns = list(DEFAULT_FLAG_PATTERNS)
    if custom_pattern:
        patterns.insert(0, custom_pattern)

    found: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            flag = match.group(0)
            if flag not in seen:
                seen.add(flag)
                found.append(flag)
    return found


def looks_like_flag(text: str, custom_pattern: Optional[str] = None) -> bool:
    """Check whether text contains at least one CTF flag.

    Args:
        text: Text to inspect.
        custom_pattern: Optional additional regex pattern.

    Returns:
        True if any flag pattern matches.
    """
    return len(extract_flags(text, custom_pattern)) > 0
