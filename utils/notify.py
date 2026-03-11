"""Desktop notifications for long-running solve completions."""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def notify(
    title: str,
    message: str,
    urgency: str = "normal",
    timeout_ms: int = 5000,
) -> bool:
    """Send a desktop notification. Returns True if sent.

    Tries notify-send (Linux), osascript (macOS), falls back silently.
    """
    # Linux: notify-send
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", f"--urgency={urgency}", f"--expire-time={timeout_ms}", title, message],
                capture_output=True,
                timeout=5,
            )
            return True
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("notify-send failed: %s", e)

    # macOS: osascript
    if shutil.which("osascript"):
        try:
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
            )
            return True
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("osascript failed: %s", e)

    return False


def notify_solve_complete(
    success: bool,
    flags: list[str] | None = None,
    challenge: str = "",
    cost: float = 0.0,
) -> None:
    """Notify user when a solve attempt completes."""
    if success:
        flag_str = ", ".join(flags) if flags else "found"
        title = "Q: Challenge Solved!"
        msg = f"Flag: {flag_str}"
        urgency = "normal"
    else:
        title = "Q: Solve Attempt Complete"
        msg = f"No flag found. Cost: ${cost:.4f}"
        urgency = "low"

    if challenge:
        msg = f"{challenge[:50]}... — {msg}" if len(challenge) > 50 else f"{challenge} — {msg}"

    notify(title, msg, urgency=urgency)
