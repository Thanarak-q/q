"""Interactive chat loop for ctf-agent.

Provides the main REPL, input handling (single-line, multi-line),
AgentCallbacks implementation with tree-structured output, and
session management.
"""

from __future__ import annotations

import json
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent.orchestrator import AgentCallbacks, Orchestrator, SolveResult
from config import AppConfig, load_config
from ui.commands import handle_command
from ui.display import Display
from ui.input_filter import classify_input
from ui.input_handler import QInput
from ui.spinner import PhaseSpinner
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

    # White-box analysis
    repo_path: str | None = None

    # YAML config path
    yaml_config_path: str | None = None

    # Orchestrator reference for /rewind command
    _rewind_orchestrator: Any = None

    # Team mode
    team_mode: bool = False
    _team_leader: Any = None

    # Plan mode
    plan_mode: bool = True


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
        self._spinner: PhaseSpinner | None = None

    # -- Lifecycle -------------------------------------------------

    def reset_for_new_solve(self) -> None:
        """Clear tree state for a new solve session."""
        self._tree.reset()
        self._current_tool_node = None
        self._found_flag = None
        self._found_answer = None
        self._answer_confidence = ""
        self._root_set = False

    def set_spinner(self, spinner: PhaseSpinner | None) -> None:
        """Attach a PhaseSpinner so callbacks can update it."""
        self._spinner = spinner

    # -- Phase / structure -----------------------------------------

    def on_phase(self, phase: str, detail: str) -> None:
        if self._spinner:
            self._spinner.set_phase(phase.lower())
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

    def on_thinking_delta(self, delta: str) -> None:
        """Stream thinking text in verbose mode."""
        if self._state.verbose:
            import sys
            sys.stdout.write(delta)
            sys.stdout.flush()

    # -- Tool calls ------------------------------------------------

    def on_tool_call(self, tool_name: str, args: dict) -> None:
        if self._spinner:
            self._spinner.set_phase(tool_name)
        summary = summarize_tool_call(tool_name, args)
        self._current_tool_node = self._tree.add_node(
            summary, state=NodeState.RUNNING
        )

        if self._state.verbose:
            args_str = json.dumps(args, ensure_ascii=False, indent=2)
            for line in args_str.splitlines():
                self._display.console.print(f"│     [dim]{line}[/dim]")

    def on_tool_result(self, tool_name: str, output: str, success: bool) -> None:
        if self._spinner:
            self._spinner.reset()
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

    # -- Report ----------------------------------------------------

    def on_report_saved(self, path: str) -> None:
        self._display.console.print(
            f"[dim]\U0001f4c4 Report: {path}[/dim]"
        )

    # -- User interaction ------------------------------------------

    def on_ask_user(self, prompt: str) -> str:
        from prompt_toolkit import prompt as pt_prompt

        self._display.console.print(f"\n  [warning]{prompt}[/warning]")
        try:
            return pt_prompt("  hint> ")
        except (KeyboardInterrupt, EOFError):
            return ""

    # -- Multi-agent pipeline callbacks ----------------------------

    def on_agent_start(self, agent_role: str, model: str) -> None:
        self._tree.set_root(f"\u25c6 {agent_role.capitalize()} ({model})")
        self._root_set = True

    def on_agent_done(self, agent_role: str, summary: str, success: bool) -> None:
        if summary:
            self._tree.add_completed_node(
                f"{summary[:120]}",
                success=success,
            )

    def on_pipeline_phase(
        self, phase: str, detail: str, is_fast_path: bool = False
    ) -> None:
        label = phase.capitalize()
        if is_fast_path:
            label += " [fast-path]"
        self._display.show_info(f"\u25c6 {label}: {detail}")

    def on_parallel_start(self, count: int) -> None:
        self._tree.add_completed_node(
            f"Launching {count} parallel solvers",
            success=True,
        )

    def on_parallel_result(
        self, index: int, success: bool, summary: str
    ) -> None:
        icon = "\u2713" if success else "\u2717"
        self._tree.add_completed_node(
            f"Solver #{index}: {icon} {summary[:100]}",
            success=success,
        )


# ------------------------------------------------------------------
# Input handling (prompt_toolkit-based)
# ------------------------------------------------------------------


def read_input(qi: QInput, display: Display) -> str | None:
    """Read user input with prompt_toolkit line editing.

    Features:
    - Arrow keys work (cursor navigation, history)
    - Tab auto-complete for slash commands
    - Ctrl+R history search
    - Multi-line via triple quotes or backslash continuation
    - Ctrl+C returns empty string, Ctrl+D returns None

    Args:
        qi: QInput instance with prompt_toolkit session.
        display: Display for fallback output.

    Returns:
        User input string, empty on Ctrl+C, None on EOF.
    """
    line = qi.get_input("> ")

    # Ctrl+D (EOF)
    if line is None:
        return None

    # Ctrl+C — pass sentinel through so main loop can handle it
    if line == QInput.CTRL_C:
        return QInput.CTRL_C

    stripped = line.strip()

    # Multi-line mode with triple quotes
    if stripped.startswith('"""'):
        lines = [stripped[3:]]
        while True:
            next_line = qi.get_continuation("... ")
            if next_line is None:
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
            next_line = qi.get_continuation("... ")
            if next_line is None:
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

    Uses auto-detection to find the best sandbox mode.
    Returns the DockerSandbox manager on success, None on failure.
    Errors are logged to file only — no console output.
    """
    from utils.logger import get_logger

    log = get_logger()

    # Auto-detect if configured for docker
    if config.sandbox_mode == "docker":
        try:
            from sandbox.docker_manager import detect_sandbox_mode

            detected = detect_sandbox_mode()
            log.info(f"Sandbox auto-detect: {detected}")
            if detected == "local":
                log.info("Docker unavailable — falling back to local execution.")
                return None
        except Exception:
            pass

    if config.sandbox_mode not in ("docker", "docker_sudo"):
        return None

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
# Plan phase
# ------------------------------------------------------------------


def _run_plan_phase(
    description: str,
    state: ChatState,
    display: Display,
) -> tuple[str | None, str | None]:
    """Run classify + plan before the main solve.

    Returns (category_str, plan_text) or (None, None) on failure.
    """
    from agent.classifier import classify_challenge
    from agent.planner import create_plan
    from agent.providers.router import ProviderRouter

    spinner = PhaseSpinner(display.console)
    try:
        with spinner:
            spinner.set_phase("classify")
            provider = ProviderRouter(state.config)
            category = classify_challenge(
                description=description,
                file_info="",
                client=provider,
                config=state.config,
            )
            spinner.set_phase("plan")
            plan = create_plan(
                description=description,
                category=category,
                file_info="",
                client=provider,
                config=state.config,
            )
    except Exception as exc:
        display.show_error(f"Planning failed: {exc}")
        return None, None

    return category.value, plan


# ------------------------------------------------------------------
# Solve logic
# ------------------------------------------------------------------


def run_solve(
    description: str,
    state: ChatState,
    display: Display,
    callbacks: ChatCallbacks,
    watch_mode: bool = False,
    qi: "QInput | None" = None,
) -> SolveResult | None:
    """Run the solve pipeline for a challenge description."""
    # --- Team mode: delegate to TeamLeader ---
    if state.team_mode:
        return _run_team_solve(description, state, display, callbacks)

    # --- Plan mode: classify + plan, show to user, get approval ---
    forced_plan: str | None = None
    if state.plan_mode and not state.resume_session_id:
        cat_str, plan_text = _run_plan_phase(description, state, display)
        if plan_text is None:
            return None  # planning failed, abort
        display.show_plan(plan_text, cat_str or "?")
        try:
            if qi is not None:
                response = qi.get_input("  plan> ") or ""
                if response == QInput.CTRL_C:
                    display.console.print("\n  [dim]Cancelled.[/dim]")
                    return None
            else:
                response = input("  plan> ").strip()
        except (KeyboardInterrupt, EOFError):
            display.console.print("\n  [dim]Cancelled.[/dim]")
            return None
        if response.lower() in ("skip", "s", "no", "cancel"):
            display.show_info("Plan skipped.")
        else:
            if response:
                plan_text += f"\n\nUser notes: {response}"
            forced_plan = plan_text
            if cat_str and not state.forced_category:
                state.forced_category = cat_str

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
        repo_path=state.repo_path,
        yaml_config_path=state.yaml_config_path,
    )
    state._rewind_orchestrator = orch

    if state.solving:
        display.show_error("Already solving. Wait or Ctrl+C to stop.")
        return None

    state.solving = True
    callbacks.reset_for_new_solve()

    # Set up Ctrl+C: first press = cancel agent + save state,
    # second press within 2s = exit program
    original_handler = signal.getsignal(signal.SIGINT)
    _last_ctrl_c: list[float] = [0.0]

    def cancel_handler(signum, frame):
        now = time.time()
        if now - _last_ctrl_c[0] < 2.0:
            # Double Ctrl+C — exit immediately
            display.console.print("\n  [warning]Exiting...[/warning]")
            signal.signal(signal.SIGINT, original_handler)
            raise KeyboardInterrupt
        _last_ctrl_c[0] = now
        display.console.print(
            "\n  [warning]Stopping agent... "
            "/resume to continue[/warning]"
        )
        orch.cancel()

    signal.signal(signal.SIGINT, cancel_handler)

    if watch_mode:
        try:
            from ui.watch import WatchDisplay, WatchCallbacks
            watch_display = WatchDisplay()
            watch_cb = WatchCallbacks(callbacks, watch_display, callbacks._tree)
            orch._cb = watch_cb  # Replace callbacks for watch mode
            try:
                with watch_display:
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
                            forced_plan=forced_plan,
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
        except ImportError:
            display.show_error("Watch mode requires Rich. Falling back to normal mode.")
            watch_mode = False

    if not watch_mode:
        spinner = PhaseSpinner(display.console)
        try:
            with spinner:
                callbacks.set_spinner(spinner)
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
                        forced_plan=forced_plan,
                    )
        except KeyboardInterrupt:
            display.show_error("Interrupted.")
            result = None
        finally:
            callbacks.set_spinner(None)
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
# Team solve
# ------------------------------------------------------------------


def _run_team_solve(
    description: str,
    state: ChatState,
    display: Display,
    callbacks: ChatCallbacks,
) -> SolveResult | None:
    """Run team-based solve using TeamLeader."""
    from agent.team.leader import TeamLeader

    if state.solving:
        display.show_error("Already solving. Wait or Ctrl+C to stop.")
        return None

    state.solving = True
    callbacks.reset_for_new_solve()

    # Classify category for team preset selection
    category = state.forced_category or "misc"
    if not state.forced_category:
        try:
            from agent.classifier import classify_challenge
            result = classify_challenge(description, state.config)
            category = result.get("category", "misc")
        except Exception:
            pass

    display.show_info(f"Team mode: assembling {category} team...")

    leader = TeamLeader(
        config=state.config,
        callbacks=callbacks,
        docker_manager=state.docker_manager,
        workspace=state.workspace,
    )
    state._team_leader = leader

    # Set up Ctrl+C handler
    import signal
    original_handler = signal.getsignal(signal.SIGINT)
    _last_ctrl_c: list[float] = [0.0]

    def cancel_handler(signum, frame):
        now = time.time()
        if now - _last_ctrl_c[0] < 2.0:
            display.console.print("\n  [warning]Exiting...[/warning]")
            signal.signal(signal.SIGINT, original_handler)
            raise KeyboardInterrupt
        _last_ctrl_c[0] = now
        display.console.print("\n  [warning]Stopping team...[/warning]")
        leader.cancel()

    signal.signal(signal.SIGINT, cancel_handler)

    spinner = PhaseSpinner(display.console)
    result = None
    try:
        with spinner:
            callbacks.set_spinner(spinner)
            result = leader.solve_with_team(
                description=description,
                category=category,
                files=state.pending_files or None,
                target_url=state.pending_url,
                flag_pattern=state.flag_pattern,
            )
    except KeyboardInterrupt:
        display.show_error("Team interrupted.")
        result = None
    finally:
        callbacks.set_spinner(None)
        signal.signal(signal.SIGINT, original_handler)
        state.solving = False
        state.pending_files = []
        state.pending_url = None
        state.forced_category = None
        state._team_leader = None

    if result:
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

        # Show team summary
        if result.summary:
            display.console.print(f"\n[dim]{result.summary}[/dim]")

        state.solve_history.append({
            "description": description[:80],
            "status": "solved" if result.success else "failed",
            "flags": result.flags,
            "category": result.category,
            "iterations": result.iterations,
            "cost": result.cost_usd,
            "session_id": result.session_id,
            "team": True,
        })
        state.total_session_cost += result.cost_usd
        state.last_session_id = result.session_id

    return result


# ------------------------------------------------------------------
# Main chat loop
# ------------------------------------------------------------------


def chat_loop(
    verbose: bool = False,
    repo_path: str | None = None,
    config_path: str | None = None,
    watch: bool = False,
    team: bool = False,
    no_plan: bool = False,
) -> None:
    """Run the main interactive chat loop.

    Args:
        verbose: Enable verbose output.
        repo_path: Optional path to source code for white-box analysis.
        config_path: Optional path to YAML config file.
        team: Enable team mode from CLI flag.
    """
    # Load config
    config = load_config()
    setup_logger(
        level=config.log.level,
        log_dir=config.log.log_dir,
        verbose=verbose,
    )

    # Init display and state
    display = Display()
    # Apply YAML config overrides
    yaml_config = None
    if config_path:
        from config_yaml.loader import apply_yaml_to_appconfig, load_yaml_config

        yaml_config = load_yaml_config(config_path)
        config = apply_yaml_to_appconfig(yaml_config, config)

    state = ChatState(
        config=config,
        current_model=config.model.default_model,
        workspace=Path.cwd(),
        verbose=verbose or (yaml_config.verbose if yaml_config else False),
        repo_path=repo_path,
        yaml_config_path=config_path,
        team_mode=team or config.team.enabled,
        plan_mode=config.plan_mode and not no_plan,
    )
    callbacks = ChatCallbacks(display, state)

    # Docker setup (silent — errors go to log file only)
    state.docker_manager = setup_docker(config)
    state.sandbox_display = "docker" if state.docker_manager else "local"

    # Detect first run — no API key set
    _no_key = not config.model.api_key and not config.model.anthropic_api_key

    # Minimal welcome banner (after docker so we show the actual mode)
    display.show_banner(
        model=state.current_model,
        sandbox=state.sandbox_display,
        workspace=str(state.workspace),
        first_run=_no_key,
    )

    if _no_key:
        display.show_setup_needed()

    # Show YAML config info if loaded
    if yaml_config and config_path:
        from config_yaml.loader import config_summary

        display.show_info(f"Config loaded: {config_path}")
        summary = config_summary(yaml_config)
        if yaml_config.target and yaml_config.target.url:
            display.console.print(
                f"  [dim]Target: {yaml_config.target.url}[/dim]"
            )

    # Input handler with prompt_toolkit (arrow keys, autocomplete, history)
    qi = QInput()

    # Ctrl+C double-tap tracker for idle mode
    _last_idle_ctrl_c: float = 0.0

    # Ignore Ctrl+Z (SIGTSTP) — no job control in agent mode
    try:
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    except (OSError, AttributeError):
        pass  # SIGTSTP not available on Windows

    # Greeting responses
    _GREETINGS = [
        "Hey! Got a CTF challenge for me?",
        "Hi! Paste a challenge or type /help",
        "Yo! Ready to hack. What's the target?",
    ]

    # Main loop
    try:
        while True:
            raw_input = read_input(qi, display)

            # EOF (Ctrl+D)
            if raw_input is None:
                display.show_goodbye(
                    state.total_session_cost, len(state.solve_history)
                )
                break

            # Ctrl+C while idle — double-tap to exit
            if raw_input == QInput.CTRL_C:
                now = time.time()
                if now - _last_idle_ctrl_c < 2.0:
                    display.show_goodbye(
                        state.total_session_cost, len(state.solve_history)
                    )
                    break
                _last_idle_ctrl_c = now
                display.console.print(
                    "  [dim]Press Ctrl+C again to quit, "
                    "or type a challenge.[/dim]"
                )
                continue

            # Empty input
            if not raw_input:
                continue

            # Classify input before acting
            action = classify_input(raw_input)

            if action["action"] == "ignore":
                continue

            elif action["action"] == "exit":
                display.show_goodbye(
                    state.total_session_cost, len(state.solve_history)
                )
                break

            elif action["action"] == "greet":
                display.console.print(
                    f"  [dim]{random.choice(_GREETINGS)}[/dim]"
                )
                continue

            elif action["action"] == "help":
                handle_command("/help", state, display)
                continue

            elif action["action"] == "command":
                should_exit = handle_command(action["cmd"], state, display)
                if should_exit:
                    break
                continue

            elif action["action"] == "clarify":
                display.console.print(
                    f"  [dim]Did you mean to solve a challenge? "
                    f"Give me more details.[/dim]\n"
                    f"  [dim]Or type /help for commands.[/dim]"
                )
                continue

            elif action["action"] == "solve":
                # Reload config in case user just set an API key via /settings
                if not state.config.model.api_key and not state.config.model.anthropic_api_key:
                    state.config = load_config()
                    state.current_model = state.config.model.default_model
                if not state.config.model.api_key and not state.config.model.anthropic_api_key:
                    display.show_setup_needed()
                    continue
                display.console.print()
                run_solve(action["text"], state, display, callbacks, watch_mode=watch, qi=qi)

    except KeyboardInterrupt:
        display.console.print()
        display.show_goodbye(state.total_session_cost, len(state.solve_history))
    finally:
        if state.docker_manager:
            try:
                state.docker_manager.stop()
            except Exception:
                pass
