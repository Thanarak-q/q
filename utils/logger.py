"""Structured logging for ctf-agent.

Provides a pre-configured Rich console logger and a file logger for
persistent session logs.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# Custom theme matching the spec colours
CTF_THEME = Theme(
    {
        "thinking": "cyan",
        "tool_call": "yellow",
        "result": "green",
        "error": "bold red",
        "flag": "bold green",
        "step": "bold white",
        "info": "dim white",
    }
)

console = Console(theme=CTF_THEME)

_logger: Optional[logging.Logger] = None


def setup_logger(level: str = "INFO", log_dir: Optional[Path] = None) -> logging.Logger:
    """Initialise and return the application logger.

    Args:
        level: Logging level name (DEBUG, INFO, WARNING, ERROR).
        log_dir: Directory for file-based log output. Created if absent.

    Returns:
        Configured logging.Logger instance.
    """
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("ctf-agent")
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Rich console handler
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    rich_handler.setLevel(logging.DEBUG)
    _logger.addHandler(rich_handler)

    # File handler
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        fh = logging.FileHandler(log_dir / f"session_{ts}.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
        fh.setFormatter(fmt)
        _logger.addHandler(fh)

    return _logger


def get_logger() -> logging.Logger:
    """Return the existing logger, or set up a default one.

    Returns:
        The application logger.
    """
    global _logger
    if _logger is None:
        return setup_logger()
    return _logger
