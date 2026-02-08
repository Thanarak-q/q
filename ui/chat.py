"""Interactive chat loop for ctf-agent.

Provides the main REPL, input handling (single-line, multi-line),
AgentCallbacks implementation, and session management.
"""

from __future__ import annotations

import signal
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent.orchestrator import AgentCallbacks, Orchestrator, SolveResult
from config import AppConfig, load_config
from ui.commands import handle_command
from ui.display import Display
from ui.spinner import thinking_spinner, tool_spinner
from utils.cost_tracker import CostTracker
from utils.logger import setup_logger
from utils.session_manager import SessionManager


# ------------------------------------------------------------------
# Mutable chat state shared across the session
# ------------------------------------------------------------------


@dataclass
class ChatState:
    """Mutable state for the interactive chat session."""

    config: AppConfig
    current_model: str = ""
    forced_category: str | None = None
    pending_files: list[Path] = field(default_factory=list)
    pending_url: str | None = None
    flag_pattern: str | None = None

    # Session tracking
    solve_history: list[dict[str, Any]] = field(default_factory=list)
    total_session_cost: float = 0.0
    last_session_id: str = ""
    resume_session_id: str | None = None
    session_cost_tracker: CostTracker | None = None

    # Workspace
    workspace: Path = field(default_factory=Path.cwd)

    # Runtime
    docker_manager: Any = None
    solving: bool = False


# ------------------------------------------------------------------
# Chat UI callback implementation
# ------------------------------------------------------------------


class ChatCallbacks(AgentCallbacks):
    """Interactive chat UI callback implementation.

    Renders agent events using the Display class.
    """

    def __init__(self, display: Display, state: ChatState) -> None:
        self._display = display
        self._state = state
        self._current_spinner: Any = None

    def on_thinking(self, text: str) -> None:
        self._display.show_thinking(text)

    def on_tool_call(self, tool_name: str, args: dict) -> None:
        self._display.show_tool_call(tool_name, args)

    def on_tool_result(self, tool_name: str, output: str, success: bool) -> None:
        self._display.show_tool_result(output, success)

    def on_answer(self, answer: str, confidence: str, flag: str | None) -> None:
        self._display.show_answer(answer, confidence, flag)

    def on_flag_found(self, flag: str) -> None:
        self._display.show_flag(flag)

    def on_error(self, message: str) -> None:
        self._display.show_error(message)

    def on_status(
        self,
        step: int,
        max_steps: int,
        tokens: int,
        cost: float,
        model: str,
    ) -> None:
        self._display.show_status_bar(model, step, max_steps, tokens, cost)

    def on_phase(self, phase: str, detail: str) -> None:
        self._display.show_info(f"{phase}: {detail}")

    def on_pivot(self, level_name: str, pivot_count: int) -> None:
        self._display.show_pivot(level_name, pivot_count)

    def on_model_change(self, old_model: str, new_model: str) -> None:
        self._display.show_model_change(old_model, new_model)

    def on_context_summary(self) -> None:
        self._display.show_context_summary()

    def on_budget_warning(self, warning: str) -> None:
        self._display.show_budget_warning(warning)

    def on_iteration(self, current: int, total: int) -> None:
        self._display.show_iteration_header(current, total)

    def on_ask_user(self, prompt: str) -> str:
        """Ask the user for a hint during solving."""
        self._display.console.print(
            f"\n  [warning]{prompt}[/warning]"
        )
        try:
            hint = self._display.console.input("  [bold]Your hint> [/bold]")
            return hint
        except (KeyboardInterrupt, EOFError):
            return ""


# ------------------------------------------------------------------
# Input handling
# ------------------------------------------------------------------


def read_input(display: Display) -> str | None:
    """Read user input with multi-line support.

    Supports:
    - Single line input
    - Multi-line via triple quotes (\"\"\" ... \"\"\")
    - Multi-line via backslash continuation (\\)
    - EOF (Ctrl+D) returns None

    Args:
        display: Display instance for the prompt.

    Returns:
        The user input string, or None on EOF.
    """
    try:
        line = display.console.input("[bold]You > [/bold]")
    except EOFError:
        return None
    except KeyboardInterrupt:
        display.console.print()
        return ""

    stripped = line.strip()

    # Multi-line mode with triple quotes
    if stripped.startswith('"""'):
        lines = [stripped[3:]]  # content after opening """
        while True:
            try:
                next_line = display.console.input("[dim]... [/dim]")
            except (EOFError, KeyboardInterrupt):
                break
            if next_line.rstrip().endswith('"""'):
                lines.append(next_line.rstrip()[:-3])
                break
            lines.append(next_line)
        return "\n".join(lines).strip()

    # Backslash continuation
    if stripped.endswith("\\"):
        lines = [stripped[:-1]]
        while True:
            try:
                next_line = display.console.input("[dim]... [/dim]")
            except (EOFError, KeyboardInterrupt):
                break
            if next_line.rstrip().endswith("\\"):
                lines.append(next_line.rstrip()[:-1])
            else:
                lines.append(next_line)
                break
        return "\n".join(lines).strip()

    return stripped


# ------------------------------------------------------------------
# Docker setup
# ------------------------------------------------------------------


def setup_docker(config: AppConfig, display: Display) -> Any:
    """Attempt to start the Docker sandbox.

    Args:
        config: Application configuration.
        display: Display for status messages.

    Returns:
        DockerSandbox instance or None.
    """
    if config.sandbox_mode != "docker":
        return None

    try:
        from sandbox.docker_manager import DockerSandbox

        mgr = DockerSandbox(config=config)
        if mgr.start():
            display.show_info("Docker sandbox ready.")
            return mgr
        else:
            display.show_info("Docker unavailable - running tools locally.")
            return None
    except Exception as exc:
        display.show_info(f"Docker setup failed ({exc}) - running locally.")
        return None


# ------------------------------------------------------------------
# Solve logic
# ------------------------------------------------------------------


def run_solve(
    description: str,
    state: ChatState,
    display: Display,
    callbacks: ChatCallbacks,
) -> SolveResult | None:
    """Run the solve pipeline for a challenge description.

    Creates a new Orchestrator per challenge with fresh context
    but a shared cost tracker.

    Args:
        description: Challenge description.
        state: Current chat state.
        display: Display renderer.
        callbacks: Chat callbacks.

    Returns:
        SolveResult or None if interrupted.
    """
    # Shared cost tracker across session
    if state.session_cost_tracker is None:
        state.session_cost_tracker = CostTracker(
            budget_limit=state.config.agent.max_cost_per_challenge,
        )

    orch = Orchestrator(
        config=state.config,
        docker_manager=state.docker_manager,
        workspace=state.workspace,
        callbacks=callbacks,
        cost_tracker=state.session_cost_tracker,
    )

    state.solving = True

    # Set up Ctrl+C to cancel the agent (not exit the program)
    original_handler = signal.getsignal(signal.SIGINT)

    def cancel_handler(signum, frame):
        display.console.print("\n  [warning]Cancelling...[/warning]")
        orch.cancel()

    signal.signal(signal.SIGINT, cancel_handler)

    try:
        # Check for resume
        if state.resume_session_id:
            sid = state.resume_session_id
            state.resume_session_id = None
            result = orch.resume(
                session_id=sid,
                flag_pattern=state.flag_pattern,
            )
        else:
            result = orch.solve(
                description=description,
                files=state.pending_files or None,
                target_url=state.pending_url,
                flag_pattern=state.flag_pattern,
                forced_category=state.forced_category,
            )
    except KeyboardInterrupt:
        display.show_error("Interrupted.")
        result = None
    finally:
        signal.signal(signal.SIGINT, original_handler)
        state.solving = False
        # Reset per-challenge state
        state.pending_files = []
        state.pending_url = None
        state.forced_category = None

    if result:
        # Show result summary
        display.show_solve_complete(
            success=result.success,
            flags=result.flags,
            iterations=result.iterations,
            cost=result.cost_usd,
            tokens=result.total_tokens,
            category=result.category,
            session_id=result.session_id,
        )

        # Record in history
        state.solve_history.append({
            "description": description[:80],
            "status": "solved" if result.success else "failed",
            "flags": result.flags,
            "category": result.category,
            "iterations": result.iterations,
            "cost": result.cost_usd,
            "session_id": result.session_id,
        })
        state.total_session_cost += result.cost_usd
        state.last_session_id = result.session_id

    return result


# ------------------------------------------------------------------
# Main chat loop
# ------------------------------------------------------------------


def chat_loop() -> None:
    """Run the main interactive chat loop.

    This is the entry point for the interactive mode.
    """
    # Load config
    config = load_config()
    setup_logger(level=config.log.level, log_dir=config.log.log_dir)

    # Check API key
    if not config.model.api_key:
        print(
            "\nError: OPENAI_API_KEY not set.\n"
            "Set it in your .env file or environment:\n"
            "  export OPENAI_API_KEY=sk-...\n"
        )
        sys.exit(1)

    # Init display and state
    display = Display()
    state = ChatState(
        config=config,
        current_model=config.model.default_model,
        workspace=Path.cwd(),
    )
    callbacks = ChatCallbacks(display, state)

    # Show banner and welcome
    display.show_banner(state.current_model)
    display.show_welcome()

    # Docker setup
    state.docker_manager = setup_docker(config, display)

    # Main loop
    try:
        while True:
            user_input = read_input(display)

            # EOF
            if user_input is None:
                display.show_goodbye(
                    state.total_session_cost, len(state.solve_history)
                )
                break

            # Empty input
            if not user_input:
                continue

            # Slash commands
            if user_input.startswith("/"):
                should_exit = handle_command(user_input, state, display)
                if should_exit:
                    break
                continue

            # It's a challenge description — solve it
            display.console.print()
            run_solve(user_input, state, display, callbacks)

    except KeyboardInterrupt:
        display.console.print()
        display.show_goodbye(state.total_session_cost, len(state.solve_history))
    finally:
        # Cleanup Docker
        if state.docker_manager:
            try:
                state.docker_manager.stop()
            except Exception:
                pass
