"""Spinner and loading animations for ctf-agent interactive mode.

Provides context-manager based spinners for tool execution and
LLM calls, plus a persistent PhaseSpinner that updates its text
based on the current agent phase/tool.

LiveSpinner is an ANSI-based spinner that coexists with TaskTree
direct-stdout output by pausing/resuming around writes.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import time
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
    "llm_interact": "Probing target AI",
    "answer_user": "Preparing answer",
    "evidence_tracker": "Verifying evidence",
    "agent_handoff": "Consulting specialist",
    "mcp": "Calling external tool",
    "web_search": "Searching the web",
    "symbolic": "Running symbolic analysis",
    "refine": "Refining plan",
    "thinking": "Thinking",
}


class LiveSpinner:
    """ANSI-based spinner that coexists with TaskTree stdout output.

    Unlike PhaseSpinner (Rich Status), this writes directly to stdout
    using ANSI escapes and coordinates with the tree via
    clear_for_output() / done_output() to avoid visual corruption.
    """

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        self._phase = "Thinking"
        self._detail = ""
        self._idx = 0
        self._active = False
        self._paused = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> LiveSpinner:
        self._active = True
        # Only spin when stdout is a real terminal (skip in tests/pipes)
        if sys.stdout.isatty():
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._active = False
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        self._clear()

    def set_phase(self, phase: str) -> None:
        """Update the displayed phase text."""
        verb = PHASE_VERBS.get(phase, phase.replace("_", " ").title())
        with self._lock:
            self._phase = verb
            self._detail = ""

    def set_phase_detail(self, detail: str) -> None:
        """Update the detail suffix (e.g. token count) without changing phase."""
        with self._lock:
            self._detail = detail

    def reset(self) -> None:
        """Reset to default 'Thinking' phase."""
        with self._lock:
            self._phase = "Thinking"
            self._detail = ""

    def clear_for_output(self) -> None:
        """Pause spinner and clear its line before external stdout writes."""
        with self._lock:
            self._paused = True
            self._clear()

    def done_output(self) -> None:
        """Resume spinner after external stdout writes are finished."""
        with self._lock:
            self._paused = False

    def _loop(self) -> None:
        while self._active:
            with self._lock:
                if not self._paused and self._active:
                    self._render()
            time.sleep(0.08)

    def _render(self) -> None:
        if not sys.stdout.isatty():
            return
        frame = self.FRAMES[self._idx % len(self.FRAMES)]
        self._idx += 1
        detail = f" ({self._detail})" if self._detail else ""
        sys.stdout.write(
            f"\r\033[2K  \033[36m{frame}\033[0m \033[2m{self._phase}...{detail}\033[0m"
        )
        sys.stdout.flush()

    def _clear(self) -> None:
        if not sys.stdout.isatty():
            return
        sys.stdout.write("\r\033[2K")
        sys.stdout.flush()


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
