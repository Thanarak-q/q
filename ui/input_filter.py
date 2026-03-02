"""Pre-filter user input — minimal, everything else goes to LLM."""

from __future__ import annotations

EXIT_WORDS = frozenset({
    "exit", "quit", "quite", "quir", "q", "bye", "bye!",
    "goodbye", "ออก", "จบ",
})


def classify_input(text: str) -> dict:
    """Classify user input.

    Returns a dict with:
        action: one of "ignore", "exit", "command", "chat"
        Plus action-specific keys (text, cmd).
    """
    stripped = text.strip()

    if not stripped:
        return {"action": "ignore"}

    # Slash commands — pass through to command handler
    if stripped.startswith("/"):
        return {"action": "command", "cmd": stripped}

    # Exit words (exact match)
    if stripped.lower() in EXIT_WORDS:
        return {"action": "exit"}

    # Everything else → LLM chat
    return {"action": "chat", "text": stripped}
