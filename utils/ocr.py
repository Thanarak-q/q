"""Auto-OCR utility using GPT vision.

Uses GPT-4o-mini (vision-capable) to analyze images and extract text.
The LLM itself decides whether the image contains meaningful text —
returning None if there is nothing worth extracting.
"""
from __future__ import annotations

import base64

from utils.logger import get_logger

_log = get_logger()

_SYSTEM_PROMPT = (
    "You are an OCR assistant for a CTF security challenge solver. "
    "Analyze the image and decide: does it contain meaningful text, code, "
    "flags, CAPTCHAs, challenge instructions, or other readable information "
    "that would help solve a CTF challenge? "
    "If YES — extract ALL visible text faithfully, preserving layout where helpful. "
    "If NO (blank page, decorative image, or no readable text) — respond with exactly: NO_TEXT"
)


def analyze_image(
    image_bytes: bytes,
    api_key: str,
    model: str = "gpt-4o-mini",
    max_tokens: int = 500,
) -> str | None:
    """Send image to GPT vision and extract text if the LLM decides it's useful.

    Args:
        image_bytes: Raw image data (PNG, JPG, etc.).
        api_key: OpenAI API key.
        model: Vision-capable model to use.
        max_tokens: Max tokens for the response.

    Returns:
        Extracted text string, or None if no useful text detected.
    """
    if not api_key:
        _log.warning("OCR skipped: no OpenAI API key configured")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        _log.warning("OCR skipped: openai package not installed")
        return None

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "high"},
                        }
                    ],
                },
            ],
        )
        text = response.choices[0].message.content or ""
        text = text.strip()
        if not text or text == "NO_TEXT":
            return None
        return text
    except Exception as exc:
        _log.warning(f"OCR vision call failed: {exc}")
        return None
