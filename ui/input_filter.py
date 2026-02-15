"""Pre-filter user input before sending to the solver.

Catches greetings, exit commands, help triggers, and ambiguous
short inputs so they don't get classified as CTF challenges.
"""

from __future__ import annotations

# Words that are clearly greetings, not challenges
GREETINGS = frozenset({
    "hi", "hello", "hey", "yo", "sup", "howdy", "hola",
    "hi!", "hello!", "hey!", "yo!",
    # Thai
    "สวัสดี", "หวัดดี", "ดี", "สวัสดีครับ", "สวัสดีค่ะ",
})

# Words that mean "quit" — including common typos
EXIT_WORDS = frozenset({
    "exit", "quit", "quite", "quir", "q", "bye", "bye!",
    "goodbye", "ออก", "จบ",
})

# Words that mean "help"
HELP_WORDS = frozenset({
    "help", "?", "ช่วย", "commands",
})

# File extensions that signal a real challenge even in short input
_CHALLENGE_EXTENSIONS = (
    ".pcap", ".pcapng", ".bin", ".elf", ".exe", ".zip", ".gz",
    ".tar", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".pdf",
    ".php", ".py", ".js", ".rb", ".c", ".cpp", ".java",
    ".apk", ".dex", ".so", ".dll", ".pyc", ".class",
    ".mem", ".raw", ".img", ".vmdk", ".e01",
)

# URL-like patterns that signal a real challenge
_URL_HINTS = ("http://", "https://", "nc ", "ncat ", "ssh ")


def classify_input(text: str) -> dict:
    """Classify user input before sending to the agent.

    Returns a dict with:
        action: one of "ignore", "exit", "greet", "help",
                "command", "clarify", "solve"
        Plus action-specific keys (text, cmd).
    """
    stripped = text.strip()

    if not stripped:
        return {"action": "ignore"}

    lower = stripped.lower()

    # Slash commands — pass through to command handler
    if stripped.startswith("/"):
        return {"action": "command", "cmd": stripped}

    # Exit words (exact match)
    if lower in EXIT_WORDS:
        return {"action": "exit"}

    # Greetings (exact match)
    if lower in GREETINGS:
        return {"action": "greet"}

    # Help triggers (exact match)
    if lower in HELP_WORDS:
        return {"action": "help"}

    # Short input (< 10 chars) with no file/URL references
    # is likely not a real challenge description
    if len(stripped) < 10:
        has_file_ref = any(ext in lower for ext in _CHALLENGE_EXTENSIONS)
        has_url_ref = any(hint in lower for hint in _URL_HINTS)
        if not has_file_ref and not has_url_ref:
            return {"action": "clarify", "text": stripped}

    # Looks like a real challenge — send to solver
    return {"action": "solve", "text": stripped}
