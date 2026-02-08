"""Flag extraction utilities.

Searches text for common CTF flag formats using regex patterns.
Includes validation to avoid false positives from regex patterns
embedded in agent-generated code.
"""

from __future__ import annotations

import re
from typing import Optional

# Valid flag content: alphanumeric, underscores, hyphens, dots, and common
# CTF characters.  Minimum 3 characters to avoid matching template patterns.
_VALID_FLAG_CONTENT = r"[a-zA-Z0-9_\-\.!@#$%&*+=,;:~]{3,}"

# Common CTF flag prefixes — matched case-insensitively where appropriate.
DEFAULT_FLAG_PATTERNS: list[str] = [
    rf"flag\{{{_VALID_FLAG_CONTENT}\}}",
    rf"FLAG\{{{_VALID_FLAG_CONTENT}\}}",
    rf"ctf\{{{_VALID_FLAG_CONTENT}\}}",
    rf"CTF\{{{_VALID_FLAG_CONTENT}\}}",
    rf"htb\{{{_VALID_FLAG_CONTENT}\}}",
    rf"HTB\{{{_VALID_FLAG_CONTENT}\}}",
    rf"picoCTF\{{{_VALID_FLAG_CONTENT}\}}",
    rf"ictf\{{{_VALID_FLAG_CONTENT}\}}",
    rf"DUCTF\{{{_VALID_FLAG_CONTENT}\}}",
    rf"zer0pts\{{{_VALID_FLAG_CONTENT}\}}",
    rf"SECCON\{{{_VALID_FLAG_CONTENT}\}}",
    rf"corctf\{{{_VALID_FLAG_CONTENT}\}}",
]

# Characters that signal the "flag" is actually a regex pattern, not a real flag.
_REGEX_META_CHARS = set(r"[]()?*+^$|\\")

# Prefixes that indicate the match is inside source code (e.g. rb'flag{...}')
_CODE_CONTEXT_PREFIXES = (
    "r'", 'r"', "rb'", 'rb"', "b'", 'b"',
    "re.compile(", "re.search(", "re.findall(", "re.match(",
    "pattern=", "regex=",
)


def _is_regex_pattern(flag_content: str) -> bool:
    """Return True if *flag_content* looks like regex metacharacters."""
    return bool(_REGEX_META_CHARS & set(flag_content))


def _is_in_code_context(text: str, match_start: int) -> bool:
    """Return True if the match appears to be inside source code."""
    # Look at the 20 characters preceding the match
    prefix_window = text[max(0, match_start - 20) : match_start].rstrip()
    lower = prefix_window.lower()
    for code_prefix in _CODE_CONTEXT_PREFIXES:
        if lower.endswith(code_prefix):
            return True
    # Also reject if the flag is wrapped in quotes typical of code strings
    if prefix_window.endswith(("'", '"')):
        return True
    return False


def _validate_flag(flag: str, full_text: str, match_start: int) -> str:
    """Validate a candidate flag and classify it.

    Returns:
        "confirmed" — high confidence this is a real flag.
        "potential" — might be a flag but could be a false positive.
        "rejected"  — almost certainly a false positive.
    """
    # Extract the content between the braces
    brace_start = flag.index("{")
    content = flag[brace_start + 1 : -1]

    # Reject if content contains regex metacharacters
    if _is_regex_pattern(content):
        return "rejected"

    # Reject if content is too short
    if len(content) < 3:
        return "rejected"

    # Reject if embedded in code context
    if _is_in_code_context(full_text, match_start):
        return "rejected"

    # Mark as potential if content looks like a placeholder
    placeholders = {"...", "xxx", "???", "flag", "FLAG", "here", "PLACEHOLDER"}
    if content.lower() in placeholders:
        return "potential"

    return "confirmed"


def extract_flags(
    text: str,
    custom_pattern: Optional[str] = None,
) -> list[str]:
    """Extract all validated CTF flags found in text.

    Args:
        text: The text to search for flags.
        custom_pattern: Optional additional regex pattern to try.

    Returns:
        List of unique confirmed flag strings found.
    """
    patterns = list(DEFAULT_FLAG_PATTERNS)
    if custom_pattern:
        patterns.insert(0, custom_pattern)

    found: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        try:
            for match in re.finditer(pattern, text):
                flag = match.group(0)
                if flag in seen:
                    continue
                seen.add(flag)

                status = _validate_flag(flag, text, match.start())
                if status == "confirmed":
                    found.append(flag)
                elif status == "potential":
                    # Still include but the caller can inspect
                    found.append(flag)
                # "rejected" flags are silently dropped
        except re.error:
            continue
    return found


def extract_flags_with_status(
    text: str,
    custom_pattern: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Extract flags with their validation status.

    Args:
        text: The text to search for flags.
        custom_pattern: Optional additional regex pattern to try.

    Returns:
        List of (flag_string, status) tuples where status is
        "confirmed" or "potential".
    """
    patterns = list(DEFAULT_FLAG_PATTERNS)
    if custom_pattern:
        patterns.insert(0, custom_pattern)

    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern in patterns:
        try:
            for match in re.finditer(pattern, text):
                flag = match.group(0)
                if flag in seen:
                    continue
                seen.add(flag)

                status = _validate_flag(flag, text, match.start())
                if status in ("confirmed", "potential"):
                    found.append((flag, status))
        except re.error:
            continue
    return found


def looks_like_flag(text: str, custom_pattern: Optional[str] = None) -> bool:
    """Check whether text contains at least one CTF flag.

    Args:
        text: Text to inspect.
        custom_pattern: Optional additional regex pattern.

    Returns:
        True if any validated flag pattern matches.
    """
    return len(extract_flags(text, custom_pattern)) > 0
