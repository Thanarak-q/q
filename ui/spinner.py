"""Spinner and loading animations for ctf-agent interactive mode.

Provides context-manager based spinners for tool execution and
LLM calls, plus a persistent PhaseSpinner that updates its text
based on the current agent phase/tool.
"""

from __future__ import annotations

import contextlib
from typing import Generator

from rich.console import Console
from rich.status import Status


# ------------------------------------------------------------------
# Phase verb mapping — tool/phase names → human-friendly display
# ------------------------------------------------------------------

PHASE_VERBS: dict[str, str] = {
    "classifying": "Classifying challenge",
    "planning": "Planning attack",
    "shell": "Running command",
    "python_exec": "Executing Python",
    "file_manager": "Reading files",
    "browser": "Browsing target",
    "recon": "Running recon",
    "code_analyzer": "Analyzing source code",
    "network": "Testing network",
    "debugger": "Debugging binary",
    "pwntools_session": "Exploiting target",
    "netcat_session": "Connecting to service",
    "answer_user": "Preparing answer",
    "evidence_tracker": "Verifying evidence",
    "refine": "Refining plan",
    "thinking": "Thinking",
}


class PhaseSpinner:
    """A persistent spinner that updates its displayed text by phase.

    Use as a context manager around the solve loop. Call set_phase()
    to change the displayed verb as the agent works.
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._status: Status | None = None

    def __enter__(self) -> PhaseSpinner:
        self._status = self._console.status(
            "  [cyan]Thinking...[/cyan]",
            spinner="dots",
            spinner_style="cyan",
        )
        self._status.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._status is not None:
            self._status.__exit__(*exc)
            self._status = None

    def set_phase(self, phase: str) -> None:
        """Update the spinner text based on phase/tool name."""
        if self._status is None:
            return
        verb = PHASE_VERBS.get(phase, "Thinking")
        self._status.update(f"  [cyan]{verb}...[/cyan]")

    def reset(self) -> None:
        """Reset spinner text to default 'Thinking...'."""
        if self._status is not None:
            self._status.update("  [cyan]Thinking...[/cyan]")


# ------------------------------------------------------------------
# Legacy context-manager spinners (kept for compatibility)
# ------------------------------------------------------------------


@contextlib.contextmanager
def tool_spinner(
    console: Console,
    tool_name: str,
) -> Generator[Status, None, None]:
    """Show a spinner while a tool is executing."""
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
    """Show a spinner while the LLM is thinking."""
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
    """Show a spinner during challenge classification."""
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
    """Show a spinner during attack planning."""
    with console.status(
        "  [cyan]Planning attack...[/cyan]",
        spinner="dots",
        spinner_style="cyan",
    ) as status:
        yield status
