"""Slash command handlers for ctf-agent interactive mode.

Each command modifies the ChatState or displays information via Display.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ui.chat import ChatState
    from ui.display import Display


# Command help descriptions
COMMAND_HELP: dict[str, str] = {
    "/help": "Show this help message",
    "/model [name]": "Show or change the model (gpt-4o, gpt-4o-mini, o3)",
    "/config": "Show current configuration",
    "/category [cat]": "Force category (web/pwn/crypto/reverse/forensics/misc)",
    "/file <path>": "Load a file into the workspace",
    "/url <url>": "Set the target URL for the next challenge",
    "/cost": "Show token usage and cost for this session",
    "/history": "Show solve history for this session",
    "/clear": "Clear screen and reset context",
    "/save": "Save current session",
    "/load <id>": "Load a saved session",
    "/sessions": "List all saved sessions",
    "/exit, /quit": "Exit with session summary",
}

# Valid models
VALID_MODELS = {"gpt-4o", "gpt-4o-mini", "o3", "o3-mini", "gpt-4-turbo"}

# Valid categories
VALID_CATEGORIES = {"web", "pwn", "crypto", "reverse", "forensics", "misc"}


def handle_command(
    raw_input: str,
    state: ChatState,
    display: Display,
) -> bool | None:
    """Process a slash command.

    Args:
        raw_input: The full input string starting with '/'.
        state: Mutable chat state.
        display: Display renderer.

    Returns:
        True if the program should exit.
        False if the command was handled (continue chat loop).
        None if the input is not a recognised command.
    """
    parts = raw_input.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    handlers = {
        "/help": _cmd_help,
        "/model": _cmd_model,
        "/config": _cmd_config,
        "/category": _cmd_category,
        "/file": _cmd_file,
        "/url": _cmd_url,
        "/cost": _cmd_cost,
        "/history": _cmd_history,
        "/clear": _cmd_clear,
        "/save": _cmd_save,
        "/load": _cmd_load,
        "/sessions": _cmd_sessions,
        "/exit": _cmd_exit,
        "/quit": _cmd_exit,
    }

    handler = handlers.get(cmd)
    if handler is None:
        display.show_error(f"Unknown command: {cmd}. Type /help for commands.")
        return False

    return handler(arg, state, display)


# ------------------------------------------------------------------
# Individual command handlers
# ------------------------------------------------------------------


def _cmd_help(arg: str, state: ChatState, display: Display) -> bool:
    display.show_help(COMMAND_HELP)
    return False


def _cmd_model(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        display.console.print(
            f"\n  Current model: [cyan]{state.current_model}[/cyan]\n"
            f"  Fast model:    [dim]{state.config.model.fast_model}[/dim]\n"
            f"  Reasoning:     [dim]{state.config.model.reasoning_model}[/dim]\n"
        )
        return False

    model = arg.strip()
    if model not in VALID_MODELS:
        display.show_error(
            f"Unknown model '{model}'. Valid: {', '.join(sorted(VALID_MODELS))}"
        )
        return False

    old = state.current_model
    state.current_model = model
    # Also update config for new orchestrator instances
    from config import AppConfig, ModelConfig

    state.config = AppConfig(
        model=ModelConfig(
            fast_model=state.config.model.fast_model,
            default_model=model,
            reasoning_model=state.config.model.reasoning_model,
            api_key=state.config.model.api_key,
            temperature=state.config.model.temperature,
            max_tokens=state.config.model.max_tokens,
        ),
        agent=state.config.agent,
        tool=state.config.tool,
        docker=state.config.docker,
        log=state.config.log,
        sandbox_mode=state.config.sandbox_mode,
    )
    display.show_model_change(old, model)
    return False


def _cmd_config(arg: str, state: ChatState, display: Display) -> bool:
    cfg = state.config
    display.show_config(
        {
            "Default Model": cfg.model.default_model,
            "Fast Model": cfg.model.fast_model,
            "Reasoning Model": cfg.model.reasoning_model,
            "Max Iterations": cfg.agent.max_iterations,
            "Stall Threshold": cfg.agent.stall_threshold,
            "Budget Limit": f"${cfg.agent.max_cost_per_challenge:.2f}",
            "Sandbox Mode": cfg.sandbox_mode,
            "Docker Image": cfg.docker.image_name,
            "Tool Output Max": f"{cfg.agent.tool_output_max_chars} chars",
            "Context Limit": f"{cfg.agent.context_limit_percent}%",
        }
    )
    return False


def _cmd_category(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        current = state.forced_category or "(auto-detect)"
        display.console.print(
            f"\n  Current category: [cyan]{current}[/cyan]\n"
            f"  [dim]Use /category <name> to force, "
            f"or /category auto to reset.[/dim]\n"
        )
        return False

    cat = arg.strip().lower()
    if cat == "auto":
        state.forced_category = None
        display.show_info("Category reset to auto-detect.")
        return False

    if cat == "rev":
        cat = "reverse"

    if cat not in VALID_CATEGORIES:
        display.show_error(
            f"Unknown category '{cat}'. "
            f"Valid: {', '.join(sorted(VALID_CATEGORIES))}"
        )
        return False

    state.forced_category = cat
    display.show_info(f"Category forced to: {cat}")
    return False


def _cmd_file(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        if state.pending_files:
            display.console.print("\n  [bold]Loaded files:[/bold]")
            for f in state.pending_files:
                display.console.print(f"    [dim]{f}[/dim]")
            display.console.print()
        else:
            display.show_info("No files loaded. Use: /file <path>")
        return False

    path = Path(arg).expanduser().resolve()
    if not path.exists():
        display.show_error(f"File not found: {path}")
        return False

    # Copy to workspace if not already there
    dest = state.workspace / path.name
    if path != dest:
        try:
            if path.is_dir():
                shutil.copytree(path, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(path, dest)
        except Exception as exc:
            display.show_error(f"Failed to copy file: {exc}")
            return False

    state.pending_files.append(dest)
    display.show_info(f"Loaded: {path.name} -> {dest}")
    return False


def _cmd_url(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        current = state.pending_url or "(none)"
        display.console.print(
            f"\n  Target URL: [cyan]{current}[/cyan]\n"
        )
        return False

    state.pending_url = arg.strip()
    display.show_info(f"Target URL set: {state.pending_url}")
    return False


def _cmd_cost(arg: str, state: ChatState, display: Display) -> bool:
    if state.session_cost_tracker:
        display.show_cost_summary(state.session_cost_tracker.to_dict())
    else:
        display.console.print(
            f"\n  Session cost: [green]${state.total_session_cost:.4f}[/green]\n"
            f"  Challenges solved: {len(state.solve_history)}\n"
        )
    return False


def _cmd_history(arg: str, state: ChatState, display: Display) -> bool:
    display.show_history(state.solve_history)
    return False


def _cmd_clear(arg: str, state: ChatState, display: Display) -> bool:
    display.clear()
    display.show_banner(state.current_model)
    display.show_info("Screen cleared. Context reset for next challenge.")
    # Reset pending state
    state.pending_files = []
    state.pending_url = None
    state.forced_category = None
    return False


def _cmd_save(arg: str, state: ChatState, display: Display) -> bool:
    if not state.last_session_id:
        display.show_info("No active session to save.")
        return False

    from utils.session_manager import SessionManager

    mgr = SessionManager(session_dir=state.config.log.session_dir)
    # The session is already saved by the orchestrator; just confirm
    display.show_info(f"Session saved: {state.last_session_id}")
    return False


def _cmd_load(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        display.show_error("Usage: /load <session_id>")
        return False

    from utils.session_manager import SessionManager

    mgr = SessionManager(session_dir=state.config.log.session_dir)
    data = mgr.load(arg.strip())
    if data is None:
        display.show_error(f"Session not found: {arg}")
        return False

    display.console.print(
        f"\n  [bold]Loaded session: {data.session_id}[/bold]\n"
        f"  Status: {data.status}  |  Category: {data.category}\n"
        f"  Description: {data.description[:80]}\n"
        f"  Flags: {', '.join(data.flags) if data.flags else 'None'}\n"
        f"  Iterations: {data.current_iteration}\n"
    )

    if data.status == "paused":
        display.console.print(
            "  [info]This session was paused. "
            "Type a message to resume solving.[/info]\n"
        )
        state.resume_session_id = arg.strip()

    return False


def _cmd_sessions(arg: str, state: ChatState, display: Display) -> bool:
    from utils.session_manager import SessionManager

    mgr = SessionManager(session_dir=state.config.log.session_dir)
    sessions = mgr.list_sessions()
    display.show_sessions_list(sessions)
    return False


def _cmd_exit(arg: str, state: ChatState, display: Display) -> bool:
    display.show_goodbye(state.total_session_cost, len(state.solve_history))
    return True
