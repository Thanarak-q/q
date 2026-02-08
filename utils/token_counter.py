"""Token counting utilities to prevent context overflow.

Uses tiktoken to count tokens for OpenAI models.
"""

from __future__ import annotations

import json
from typing import Any

import tiktoken

# Model-to-encoding mapping; fall back to cl100k_base for unknowns.
_ENCODING_CACHE: dict[str, tiktoken.Encoding] = {}


def _get_encoding(model: str) -> tiktoken.Encoding:
    """Return the tiktoken encoding for a given model name.

    Args:
        model: OpenAI model identifier (e.g. "gpt-4o").

    Returns:
        tiktoken.Encoding appropriate for the model.
    """
    if model not in _ENCODING_CACHE:
        try:
            _ENCODING_CACHE[model] = tiktoken.encoding_for_model(model)
        except KeyError:
            _ENCODING_CACHE[model] = tiktoken.get_encoding("cl100k_base")
    return _ENCODING_CACHE[model]


def count_text_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count the number of tokens in a plain text string.

    Args:
        text: The text to tokenise.
        model: Model name for encoding selection.

    Returns:
        Token count.
    """
    enc = _get_encoding(model)
    return len(enc.encode(text))


def count_message_tokens(messages: list[dict[str, Any]], model: str = "gpt-4o") -> int:
    """Estimate token count for a list of chat messages.

    Uses the OpenAI token-counting heuristic:
    each message has ~4 overhead tokens, plus content tokens.

    Args:
        messages: List of message dicts with 'role' and 'content'.
        model: Model name for encoding selection.

    Returns:
        Estimated total token count.
    """
    enc = _get_encoding(model)
    tokens = 3  # priming tokens
    for msg in messages:
        tokens += 4  # message overhead
        for key, value in msg.items():
            if isinstance(value, str):
                tokens += len(enc.encode(value))
            elif isinstance(value, list):
                # tool_calls or content blocks
                tokens += len(enc.encode(json.dumps(value)))
    return tokens


def context_limit_for_model(model: str) -> int:
    """Return the context window size for known models.

    Args:
        model: Model identifier.

    Returns:
        Maximum context tokens.
    """
    limits: dict[str, int] = {
        "gpt-4o": 128_000,
        "gpt-4o-mini": 128_000,
        "gpt-4-turbo": 128_000,
        "gpt-4": 8_192,
        "o3": 200_000,
        "o3-mini": 200_000,
    }
    return limits.get(model, 128_000)


def is_near_limit(
    messages: list[dict[str, Any]],
    model: str = "gpt-4o",
    threshold_percent: int = 80,
) -> bool:
    """Check whether current messages are approaching the context limit.

    Args:
        messages: Current conversation messages.
        model: Model name.
        threshold_percent: Percentage of context limit to trigger warning.

    Returns:
        True if token usage exceeds the threshold percentage.
    """
    used = count_message_tokens(messages, model)
    limit = context_limit_for_model(model)
    return used >= (limit * threshold_percent // 100)
