"""Interactive chat loop for ctf-agent.

Provides the main REPL, input handling (single-line, multi-line),
AgentCallbacks implementation with tree-structured output, and
session management.
"""

from __future__ import annotations

import json
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent.orchestrator import AgentCallbacks, Orchestrator, SolveResult
from config import AppConfig, load_config
from ui.commands import handle_command
from ui.display import Display
from ui.tree import (
    NodeState,
    TaskTree,
    summarize_thinking,
    summarize_tool_call,
    summarize_tool_result,
)
from utils.cost_tracker import CostTracker
from utils.logger import setup_logger


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
    verbose: bool = False
    sandbox_display: str = "local"


# ------------------------------------------------------------------
# Chat UI callback implementation — tree-structured output
# ------------------------------------------------------------------


class ChatCallbacks(AgentCallbacks):
    """Interactive chat UI callback — renders events as a task tree.

    In minimal mode (default): shows a compact tree with 1-line
    summaries for each step.
    In verbose mode: also shows full LLM thinking and raw tool output.
    """

    def __init__(self, display: Display, state: ChatState) -> None:
        self._display = display
        self._state = state
        self._tree = TaskTree(use_color=True)
        self._current_tool_node: int | None = None
        self._found_flag: str | None = None
        self._found_answer: str | None = None
        self._answer_confidence: str = ""
        self._root_set: bool = False

    # -- Lifecycle -------------------------------------------------

    def reset_for_new_solve(self) -> None:
        """Clear tree state for a new solve session."""
        self._tree.reset()
        self._current_tool_node = None
        self._found_flag = None
        self._found_answer = None
        self._answer_confidence = ""
        self._root_set = False

    # -- Phase / structure -----------------------------------------

    def on_phase(self, phase: str, detail: str) -> None:
        if phase == "Category":
            self._tree.set_root(f"Analyzing challenge ({detail})")
            self._root_set = True
        elif phase in ("Intent", "Classifying", "Planning"):
            if self._state.verbose:
                self._display.show_info(f"{phase}: {detail}")
        elif phase == "Solving":
            if self._state.verbose:
                self._display.show_info(f"{phase}: {detail}")
        else:
            if self._state.verbose:
                self._display.show_info(f"{phase}: {detail}")

    # -- Thinking --------------------------------------------------

    def on_thinking(self, text: str) -> None:
        if not self._root_set:
            # Planning phase — show as info in verbose, skip in minimal
            if self._state.verbose:
                for line in text.splitlines()[:20]:
                    self._display.console.print(f"  [dim]{line}[/dim]")
            return

        summary = summarize_thinking(text)
        if summary:
            self._tree.add_completed_node(summary, success=True)

        if self._state.verbose:
            for line in text.splitlines():
                self._display.console.print(f"│     [dim]{line}[/dim]")

    # -- Tool calls ------------------------------------------------

    def on_tool_call(self, tool_name: str, args: dict) -> None:
        summary = summarize_tool_call(tool_name, args)
        self._current_tool_node = self._tree.add_node(
            summary, state=NodeState.RUNNING
        )

        if self._state.verbose:
            args_str = json.dumps(args, ensure_ascii=False, indent=2)
            for line in args_str.splitlines():
                self._display.console.print(f"│     [dim]{line}[/dim]")

    def on_tool_result(self, tool_name: str, output: str, success: bool) -> None:
        detail = summarize_tool_result(output)

        if self._current_tool_node is not None:
            self._tree.complete_node(
                self._current_tool_node,
                detail=detail,
                verbose_detail=output,
                success=success,
            )
            self._current_tool_node = None

        if self._state.verbose:
            lines = output.splitlines()
            for line in lines[:50]:
                self._display.console.print(f"│     [dim]{line}[/dim]")
            if len(lines) > 50:
                self._display.console.print(
                    f"│     [dim]... ({len(lines) - 50} more lines)[/dim]"
                )

    # -- Results ---------------------------------------------------

    def on_flag_found(self, flag: str) -> None:
        self._found_flag = flag

    def on_answer(self, answer: str, confidence: str, flag: str | None) -> None:
        self._found_answer = answer
        self._answer_confidence = confidence
        if flag:
            self._found_flag = flag

    # -- Errors ----------------------------------------------------

    def on_error(self, message: str) -> None:
        if self._root_set:
            self._tree.add_completed_node(message, success=False)
        else:
            self._display.show_error(message)

    # -- Status / iteration ----------------------------------------

    def on_status(
        self,
        step: int,
        max_steps: int,
        tokens: int,
        cost: float,
        model: str,
    ) -> None:
        if self._state.verbose:
            self._display.show_info(
                f"Step {step}/{max_steps} | "
                f"Tokens: {tokens:,} | Cost: ${cost:.4f} | Model: {model}"
            )

    def on_iteration(self, current: int, total: int) -> None:
        if self._state.verbose:
            self._display.console.print(
                f"│  [dim]--- Step {current}/{total} ---[/dim]"
            )

    # -- Pivot / model / context -----------------------------------

    def on_pivot(self, level_name: str, pivot_count: int) -> None:
        self._tree.add_completed_node(
            f"Strategy pivot #{pivot_count}: {level_name}",
            success=True,
        )

    def on_model_change(self, old_model: str, new_model: str) -> None:
        self._tree.add_completed_node(
            f"Model: {old_model} \u2192 {new_model}",
            success=True,
        )

    def on_context_summary(self) -> None:
        self._tree.add_completed_node("Context summarized", success=True)

    def on_budget_warning(self, warning: str) -> None:
        self._display.console.print(f"│  [warning]{warning}[/warning]")

    # -- User interaction ------------------------------------------

    def on_ask_user(self, prompt: str) -> str:
        self._display.console.print(f"\n  [warning]{prompt}[/warning]")
        try:
            hint = self._display.console.input("  [bold]hint> [/bold]")
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
    - Multi-line via triple quotes (\"\"\")
    - Multi-line via backslash continuation (\\\\)
    - EOF (Ctrl+D) returns None
    """
    try:
        line = display.console.input("[bold]> [/bold]")
    except EOFError:
        return None
    except KeyboardInterrupt:
        display.console.print()
        return ""

    stripped = line.strip()

    # Multi-line mode with triple quotes
    if stripped.startswith('"""'):
        lines = [stripped[3:]]
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


def setup_docker(config: AppConfig) -> Any:
    """Attempt to start the Docker sandbox silently.

    Returns the DockerSandbox manager on success, None on failure.
    Errors are logged to file only — no console output.
    """
    if config.sandbox_mode != "docker":
        return None

    from utils.logger import get_logger

    log = get_logger()
    try:
        from sandbox.docker_manager import DockerSandbox

        mgr = DockerSandbox(config=config)
        if mgr.start():
            log.info("Docker sandbox started successfully.")
            return mgr
        else:
            log.info("Docker unavailable — falling back to local execution.")
            return None
    except Exception as exc:
        log.debug(f"Docker setup failed: {exc}")
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
    """Run the solve pipeline for a challenge description."""
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
    callbacks.reset_for_new_solve()

    # Set up Ctrl+C to cancel the agent (not exit the program)
    original_handler = signal.getsignal(signal.SIGINT)

    def cancel_handler(signum, frame):
        display.console.print("\n  [warning]Cancelling...[/warning]")
        orch.cancel()

    signal.signal(signal.SIGINT, cancel_handler)

    try:
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
        state.pending_files = []
        state.pending_url = None
        state.forced_category = None

    if result:
        # Show result with mascot for flag/fail, plain for answers
        if callbacks._found_flag:
            display.show_flag_result(
                flag=callbacks._found_flag,
                steps=result.iterations,
                tokens=result.total_tokens,
                cost=result.cost_usd,
                answer=callbacks._found_answer,
            )
        elif not result.success:
            if callbacks._found_answer:
                display.show_answer(
                    callbacks._found_answer, callbacks._answer_confidence
                )
            display.show_fail_result(
                steps=result.iterations,
                tokens=result.total_tokens,
                cost=result.cost_usd,
            )
        else:
            if callbacks._found_answer:
                display.show_answer(
                    callbacks._found_answer, callbacks._answer_confidence
                )
            display.show_done(result.iterations, result.total_tokens, result.cost_usd)

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


def chat_loop(verbose: bool = False) -> None:
    """Run the main interactive chat loop."""
    # Load config
    config = load_config()
    setup_logger(
        level=config.log.level,
        log_dir=config.log.log_dir,
        verbose=verbose,
    )

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
        verbose=verbose,
    )
    callbacks = ChatCallbacks(display, state)

    # Docker setup (silent — errors go to log file only)
    state.docker_manager = setup_docker(config)
    state.sandbox_display = "docker" if state.docker_manager else "local"

    # Minimal welcome banner (after docker so we show the actual mode)
    display.show_banner(
        model=state.current_model,
        sandbox=state.sandbox_display,
        workspace=str(state.workspace),
    )

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
        if state.docker_manager:
            try:
                state.docker_manager.stop()
            except Exception:
                pass
