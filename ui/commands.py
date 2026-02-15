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
    "/report [list|id]": "Show latest report, list all, or show by session ID",
    "/resume [id|latest]": "Resume a paused session",
    "/audit [id]": "Show audit log (current or by session ID)",
    "/verbose [on|off]": "Toggle verbose mode (full thinking + tool output)",
    "/mode": "Show pipeline mode (single agent)",
    "/benchmark <file>": "Run benchmark challenges from a JSON file",
    "/workflow [id]": "Show workflow state history for a session",
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
        "/report": _cmd_report,
        "/resume": _cmd_resume,
        "/audit": _cmd_audit,
        "/verbose": _cmd_verbose,
        "/mode": _cmd_mode,
        "/benchmark": _cmd_benchmark,
        "/workflow": _cmd_workflow,
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
        pipeline=state.config.pipeline,
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
    display.show_banner(
        model=state.current_model,
        sandbox=state.sandbox_display,
        workspace=str(state.workspace),
    )
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


def _cmd_report(arg: str, state: ChatState, display: Display) -> bool:
    from pathlib import Path as P

    report_dir = P("reports")

    if arg == "list":
        # List all reports
        if not report_dir.exists():
            display.show_info("No reports found.")
            return False
        reports = sorted(report_dir.glob("*.md"), reverse=True)
        if not reports:
            display.show_info("No reports found.")
            return False
        display.console.print("\n  [bold]Reports:[/bold]")
        for rp in reports[:20]:
            display.console.print(f"    [dim]{rp.name}[/dim]")
        display.console.print()
        return False

    if arg and arg != "list":
        # Show report by session ID
        fpath = report_dir / f"{arg}.md"
        if not fpath.exists():
            # Try as filename directly
            fpath = report_dir / arg
        if not fpath.exists():
            display.show_error(f"Report not found: {arg}")
            return False
        display.console.print(fpath.read_text(encoding="utf-8"))
        return False

    # No arg — show latest report
    if not state.last_session_id:
        display.show_info("No active session. Solve a challenge first.")
        return False

    fpath = report_dir / f"{state.last_session_id}.md"
    if fpath.exists():
        display.console.print(fpath.read_text(encoding="utf-8"))
    else:
        # Fall back to generating from session data
        from utils.session_manager import SessionManager

        mgr = SessionManager(session_dir=state.config.log.session_dir)
        md = mgr.export_writeup(session_id=state.last_session_id)
        display.console.print(md)

    return False


def _cmd_resume(arg: str, state: ChatState, display: Display) -> bool:
    from utils.session_manager import SessionManager

    mgr = SessionManager(session_dir=state.config.log.session_dir)

    if not arg or arg == "latest":
        # Find latest resumable session
        sid = mgr.find_latest(status_filter="paused")
        if not sid:
            sid = mgr.find_latest(status_filter="failed")
        if not sid:
            display.show_info("No paused or failed sessions to resume.")
            return False
    else:
        sid = arg.strip()

    data = mgr.load(sid)
    if data is None:
        display.show_error(f"Session not found: {sid}")
        return False

    if data.status == "solved":
        display.show_info(
            f"Session {sid} is already solved. "
            f"Flags: {', '.join(data.flags) if data.flags else 'None'}"
        )
        return False

    display.console.print(
        f"\n  [bold]Resuming: {data.session_id}[/bold]\n"
        f"  Status: {data.status}  |  Category: {data.category}\n"
        f"  Step: {data.current_iteration}\n"
        f"  Description: {data.description[:80]}\n"
    )
    state.resume_session_id = sid
    display.show_info("Type anything to start solving from where you left off.")
    return False


def _cmd_audit(arg: str, state: ChatState, display: Display) -> bool:
    from utils.audit_log import read_audit_log, summarize_audit_log, export_audit_csv

    # Parse subcommands: /audit, /audit <id>, /audit export <id>
    parts = arg.split() if arg else []

    if parts and parts[0] == "export":
        sid = parts[1] if len(parts) > 1 else state.last_session_id
        if not sid:
            display.show_error("No session ID. Usage: /audit export <session_id>")
            return False
        entries = read_audit_log(sid, session_dir=state.config.log.session_dir)
        if not entries:
            display.show_info(f"No audit log for session {sid}.")
            return False
        csv_path = Path("reports") / f"{sid}_audit.csv"
        export_audit_csv(entries, csv_path)
        display.show_info(f"Audit exported to {csv_path}")
        return False

    sid = parts[0] if parts else state.last_session_id
    if not sid:
        display.show_info("No active session. Usage: /audit <session_id>")
        return False

    entries = read_audit_log(sid, session_dir=state.config.log.session_dir)
    if not entries:
        display.show_info(f"No audit log for session {sid}.")
        return False

    summary = summarize_audit_log(entries)
    display.console.print(f"\n[bold]Audit Log: {sid}[/bold]\n")
    display.console.print(summary)
    display.console.print()
    return False


def _cmd_verbose(arg: str, state: ChatState, display: Display) -> bool:
    from utils.logger import set_console_verbose

    if arg.lower() in ("on", "true", "1"):
        state.verbose = True
    elif arg.lower() in ("off", "false", "0"):
        state.verbose = False
    else:
        # Toggle
        state.verbose = not state.verbose

    set_console_verbose(state.verbose)
    status = "ON" if state.verbose else "OFF"
    display.show_info(f"Verbose mode: {status}")
    return False


def _cmd_mode(arg: str, state: ChatState, display: Display) -> bool:
    display.show_info("Single-agent mode (multi-agent pipeline removed)")
    return False


def _cmd_benchmark(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        display.show_error("Usage: /benchmark <challenges.json>")
        return False

    from pathlib import Path as P

    fpath = P(arg.strip())
    if not fpath.exists():
        display.show_error(f"File not found: {fpath}")
        return False

    from benchmark.runner import BenchmarkRunner
    from rich.table import Table

    display.show_info(f"Running benchmark: {fpath}")

    try:
        runner = BenchmarkRunner(challenges_file=fpath)
        results = runner.run()
        summary = runner.summarize(results)
    except Exception as exc:
        display.show_error(f"Benchmark failed: {exc}")
        return False

    table = Table(title="Benchmark Results")
    table.add_column("ID", style="dim")
    table.add_column("Name", max_width=30)
    table.add_column("Passed")
    table.add_column("Steps", justify="right")
    table.add_column("Cost", justify="right")

    for r in results:
        style = "green" if r.passed else "red"
        table.add_row(
            r.id,
            r.name,
            f"[{style}]{'PASS' if r.passed else 'FAIL'}[/{style}]",
            f"{r.steps}/{r.max_steps}",
            f"${r.cost:.4f}",
        )

    display.console.print(table)
    display.console.print(
        f"\nPassed: {summary['passed']}/{summary['total_challenges']}  |  "
        f"Pass rate: {summary['pass_rate']}  |  "
        f"Cost: ${summary['total_cost_usd']:.4f}"
    )
    return False


def _cmd_workflow(arg: str, state: ChatState, display: Display) -> bool:
    from utils.session_manager import SessionManager
    from rich.table import Table

    sid = arg.strip() if arg else state.last_session_id
    if not sid:
        display.show_error("Usage: /workflow <session_id>")
        return False

    mgr = SessionManager(session_dir=state.config.log.session_dir)
    data = mgr.load(sid)
    if data is None:
        display.show_error(f"Session not found: {sid}")
        return False

    display.console.print(
        f"\n  [bold]Workflow: {sid}[/bold]\n"
        f"  Current state: [cyan]{data.workflow_state}[/cyan]\n"
    )

    if not data.workflow_history:
        display.show_info("No workflow transitions recorded.")
        return False

    table = Table(title="Workflow History")
    table.add_column("From", style="dim")
    table.add_column("To", style="cyan")
    table.add_column("Detail", max_width=50)
    table.add_column("Timestamp")

    for entry in data.workflow_history:
        table.add_row(
            entry.get("from", "?"),
            entry.get("to", "?"),
            entry.get("detail", ""),
            entry.get("timestamp", "")[:19],
        )

    display.console.print(table)
    return False


def _cmd_exit(arg: str, state: ChatState, display: Display) -> bool:
    display.show_goodbye(state.total_session_cost, len(state.solve_history))
    return True
