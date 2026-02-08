"""Spinner and loading animations for ctf-agent interactive mode.

Provides context-manager based spinners for tool execution and
LLM calls.
"""

from __future__ import annotations

import contextlib
from typing import Generator

from rich.console import Console
from rich.status import Status


@contextlib.contextmanager
def tool_spinner(
    console: Console,
    tool_name: str,
) -> Generator[Status, None, None]:
    """Show a spinner while a tool is executing.

    Args:
        console: Rich console instance.
        tool_name: Name of the tool being executed.

    Yields:
        The Rich Status object (can be used to update text).
    """
    with console.status(
        f"  [yellow]Running {tool_name}...[/yellow]",
        spinner="dots",
        spinner_style="yellow",
    ) as status:
        yield status


@contextlib.contextmanager
def thinking_spinner(
    console: Console,
) -> Generator[Status, None, None]:
    """Show a spinner while the LLM is thinking.

    Args:
        console: Rich console instance.

    Yields:
        The Rich Status object.
    """
    with console.status(
        "  [cyan]Thinking...[/cyan]",
        spinner="dots",
        spinner_style="cyan",
    ) as status:
        yield status


@contextlib.contextmanager
def classify_spinner(
    console: Console,
) -> Generator[Status, None, None]:
    """Show a spinner during challenge classification.

    Args:
        console: Rich console instance.

    Yields:
        The Rich Status object.
    """
    with console.status(
        "  [cyan]Classifying challenge...[/cyan]",
        spinner="dots",
        spinner_style="cyan",
    ) as status:
        yield status


@contextlib.contextmanager
def planning_spinner(
    console: Console,
) -> Generator[Status, None, None]:
    """Show a spinner during attack planning.

    Args:
        console: Rich console instance.

    Yields:
        The Rich Status object.
    """
    with console.status(
        "  [cyan]Planning attack...[/cyan]",
        spinner="dots",
        spinner_style="cyan",
    ) as status:
        yield status
