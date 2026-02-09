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


_rich_handler: Optional[RichHandler] = None


def setup_logger(
    level: str = "INFO",
    log_dir: Optional[Path] = None,
    verbose: bool = False,
) -> logging.Logger:
    """Initialise and return the application logger.

    Args:
        level: Logging level name (DEBUG, INFO, WARNING, ERROR).
        log_dir: Directory for file-based log output. Created if absent.
        verbose: If False, suppress console log output (file logging
            continues at DEBUG).  If True, show all logs on console.

    Returns:
        Configured logging.Logger instance.
    """
    global _logger, _rich_handler
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("ctf-agent")
    _logger.setLevel(logging.DEBUG)

    # Rich console handler — silent by default, verbose shows everything
    _rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    _rich_handler.setLevel(logging.DEBUG if verbose else logging.CRITICAL)
    _logger.addHandler(_rich_handler)

    # File handler — always captures everything
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        fh = logging.FileHandler(log_dir / f"session_{ts}.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
        fh.setFormatter(fmt)
        _logger.addHandler(fh)

    return _logger


def set_console_verbose(verbose: bool) -> None:
    """Toggle console log verbosity at runtime.

    Args:
        verbose: True to show all logs on console, False to suppress.
    """
    global _rich_handler
    if _rich_handler is not None:
        _rich_handler.setLevel(logging.DEBUG if verbose else logging.CRITICAL)


def get_logger() -> logging.Logger:
    """Return the existing logger, or set up a default one.

    Returns:
        The application logger.
    """
    global _logger
    if _logger is None:
        return setup_logger()
    return _logger
