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


# Command help — grouped by function
COMMAND_HELP: dict[str, str] = {
    # Solving
    "/repo <path>": "Set source code path for white-box analysis",
    "/resume [id|latest]": "Resume a paused session",
    "/report [list|id]": "Show latest report, list all, or show by session ID",
    "/audit [id]": "Show audit log (current or by session ID)",
    "/rewind [n|list]": "Rewind agent state by n steps, or list checkpoints",
    # Intelligence
    "/knowledge [search|clear|export]": "Knowledge base stats or search",
    "/stats": "Performance dashboard",
    "/benchmark <file>": "Run benchmark challenges from a JSON file",
    "/workflow [id]": "Show workflow state history",
    # AI CTF
    "/flag [pattern]": "Set flag format (e.g. NCSA{...}) or show current pattern",
    # Session
    "/file <path>": "Load a file into the workspace",
    "/url <url>": "Set the target URL for the next challenge",
    "/category [cat]": "Force category (web/pwn/crypto/reverse/forensics/ai/misc)",
    "/save": "Save current session",
    "/load <id>": "Load a saved session",
    "/sessions": "List all saved sessions",
    "/history": "Show solve history for this session",
    # Team
    "/team": "Show team status or toggle team mode",
    "/team on, /team off": "Enable/disable team solving",
    "/team tasks": "Show team task board",
    "/team messages": "Show team message log",
    "/team agents": "Show active teammates with status",
    # Plan mode
    "/plan [on|off]": "Toggle plan mode (review, refine, and approve plan before solving)",
    # Settings
    "/settings": "Show all settings from ~/.q/settings.json",
    "/settings <key> <value>": "Update a setting (e.g. /settings openai_api_key sk-...)",
    "/model [name]": "Show or change the model (gpt-4o, gpt-4o-mini, o3)",
    "/config [load|show]": "Show config, load YAML, or show target details",
    "/cost": "Show token usage and cost for this session",
    "/verbose [on|off]": "Toggle verbose mode",
    "/clear": "Clear screen and reset context",
    "/mode": "Show pipeline mode",
    "/help": "Show this help message",
    "/exit, /quit": "Exit with session summary",
}

# Valid model prefixes (used by /model validation)
_MODEL_EXAMPLES = "gpt-4o, o3, claude-sonnet-4-5, gemini-2.0-flash"

# Curated model list for the interactive selector (ordered by provider)
_SELECTOR_MODELS: list[str] = [
    # OpenAI
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
    "o3",
    "o3-mini",
    "o4-mini",
    # Anthropic
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-opus-4-6",
    "claude-haiku-4-5",
    # Google
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

# Valid categories
VALID_CATEGORIES = {"web", "pwn", "crypto", "reverse", "forensics", "ai", "misc"}


def _sync_chat_orchestrator_config(state: "ChatState") -> None:
    """Propagate updated config/model into the persistent chat orchestrator."""
    orch = state._chat_orchestrator
    if orch is None:
        return

    try:
        from agent.providers import create_provider

        provider = create_provider(state.config.model)
        orch._config = state.config
        orch._provider = provider
        orch._current_model = state.current_model

        if hasattr(orch, "_context") and orch._context is not None:
            orch._context._client = provider
            orch._context._config = state.config
            orch._context._model = state.current_model
    except Exception:
        # Fall back to rebuilding on next turn if live-sync fails.
        state._chat_orchestrator = None


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
        "/repo": _cmd_repo,
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
        "/knowledge": _cmd_knowledge,
        "/stats": _cmd_stats,
        "/benchmark": _cmd_benchmark,
        "/workflow": _cmd_workflow,
        "/rewind": _cmd_rewind,
        "/settings": _cmd_settings,
        "/team": _cmd_team,
        "/plan": _cmd_plan,
        "/flag": _cmd_flag,
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


def _cmd_repo(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        current = state.repo_path or "(none)"
        display.console.print(
            f"\n  Source code repo: [cyan]{current}[/cyan]\n"
            f"  [dim]Use /repo <path> to set, /repo off to clear.[/dim]\n"
        )
        return False

    if arg.strip().lower() in ("off", "none", "clear"):
        state.repo_path = None
        display.show_info("White-box mode disabled.")
        return False

    path = Path(arg.strip()).expanduser().resolve()
    if not path.is_dir():
        display.show_error(f"Directory not found: {path}")
        return False

    state.repo_path = str(path)

    # Run analysis immediately to give feedback
    from tools.code_analyzer import CodeAnalyzer

    analyzer = CodeAnalyzer()
    analysis = analyzer.analyze_directory(str(path))
    summary = analyzer.summary(analysis)
    display.show_info(f"Repo set: {path}")
    display.console.print(f"  [dim]{summary}[/dim]\n")
    return False


def _build_model_options(state: "ChatState") -> list[tuple[str, str]]:
    """Build model list for the interactive selector."""
    models: list[str] = list(_SELECTOR_MODELS)
    # Include any configured models not already in the curated list
    for m in (
        state.current_model,
        state.config.model.default_model,
        state.config.model.fast_model,
        state.config.model.reasoning_model,
        state.config.model.fallback_model,
    ):
        if m and m not in models:
            models.append(m)
    return [(m, m) for m in models]


def _cmd_model(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        from ui.selector import interactive_select

        choice = interactive_select(
            title="Select model:",
            options=_build_model_options(state),
            current=state.current_model,
        )
        if choice is None or choice == state.current_model:
            return False
        arg = choice

    model = arg.strip()

    # Validate using provider prefix routing
    from agent.providers.router import PROVIDER_PREFIXES

    known = any(model.startswith(prefix) for prefix, _ in PROVIDER_PREFIXES)
    if not known:
        display.show_error(
            f"Unknown model prefix for '{model}'. Examples: {_MODEL_EXAMPLES}"
        )
        return False

    old = state.current_model
    state.current_model = model
    # Update config — preserve all existing fields, only change default_model
    from config import AppConfig, ModelConfig

    m = state.config.model
    state.config = AppConfig(
        model=ModelConfig(
            fast_model=m.fast_model,
            default_model=model,
            reasoning_model=m.reasoning_model,
            api_key=m.api_key,
            temperature=m.temperature,
            max_tokens=m.max_tokens,
            streaming=m.streaming,
            anthropic_api_key=m.anthropic_api_key,
            google_api_key=m.google_api_key,
            fallback_model=m.fallback_model,
            brave_api_key=m.brave_api_key,
        ),
        agent=state.config.agent,
        tool=state.config.tool,
        docker=state.config.docker,
        log=state.config.log,
        pipeline=state.config.pipeline,
        browser_vision=state.config.browser_vision,
        ocr=state.config.ocr,
        team=state.config.team,
        plan_mode=state.config.plan_mode,
        sandbox_mode=state.config.sandbox_mode,
    )
    _sync_chat_orchestrator_config(state)
    display.show_model_change(old, model)
    return False


def _cmd_config(arg: str, state: ChatState, display: Display) -> bool:
    parts = arg.split(maxsplit=1) if arg else []
    subcmd = parts[0].lower() if parts else ""

    # /config load <path> — load a YAML config
    if subcmd == "load":
        yaml_path = parts[1].strip() if len(parts) > 1 else ""
        if not yaml_path:
            display.show_error("Usage: /config load <path/to/config.yaml>")
            return False

        from pathlib import Path as P

        if not P(yaml_path).exists():
            display.show_error(f"File not found: {yaml_path}")
            return False

        from config_yaml.loader import (
            apply_yaml_to_appconfig,
            config_summary,
            load_yaml_config,
        )

        qcfg = load_yaml_config(yaml_path)
        state.config = apply_yaml_to_appconfig(qcfg, state.config)
        state.yaml_config_path = yaml_path
        state.current_model = state.config.model.default_model
        _sync_chat_orchestrator_config(state)

        display.show_info(f"Config loaded: {yaml_path}")
        summary = config_summary(qcfg)
        for k, v in summary.items():
            display.console.print(f"  [dim]{k}: {v}[/dim]")
        display.console.print()
        return False

    # /config show target — show target details from YAML
    if subcmd == "show" and len(parts) > 1 and "target" in parts[1].lower():
        if not state.yaml_config_path:
            display.show_info("No YAML config loaded. Use: /config load <path>")
            return False

        from config_yaml.loader import inject_target_to_prompt, load_yaml_config

        qcfg = load_yaml_config(state.yaml_config_path)
        prompt = inject_target_to_prompt(qcfg)
        if prompt:
            display.console.print(prompt)
        else:
            display.show_info("No target configured in YAML.")
        return False

    # Default: show current config
    cfg = state.config
    config_data = {
        "Default Model": cfg.model.default_model,
        "Fast Model": cfg.model.fast_model,
        "Reasoning Model": cfg.model.reasoning_model,
        "Max Iterations": cfg.agent.max_iterations,
        "Stall Threshold": cfg.agent.stall_threshold,
        "Budget Limit": f"${cfg.agent.max_cost_per_challenge:.2f}",
        "Turn Cost Limit": f"${cfg.agent.max_cost_per_turn:.2f}",
        "Turn Token Limit": f"{cfg.agent.max_tokens_per_turn:,}",
        "Session Cost Limit": f"${cfg.agent.max_cost_per_session:.2f}",
        "Sandbox Mode": cfg.sandbox_mode,
        "Docker Image": cfg.docker.image_name,
        "Tool Output Max": f"{cfg.agent.tool_output_max_chars} chars",
        "Context Limit": f"{cfg.agent.context_limit_percent}%",
    }

    # Add YAML config info if loaded
    if state.yaml_config_path:
        config_data["YAML Config"] = state.yaml_config_path
        try:
            from config_yaml.loader import load_yaml_config

            qcfg = load_yaml_config(state.yaml_config_path)
            if qcfg.target and qcfg.target.url:
                config_data["Target URL"] = qcfg.target.url
            if qcfg.target and qcfg.target.auth and qcfg.target.auth.username:
                config_data["Auth User"] = qcfg.target.auth.username
            config_data["Parallel"] = (
                f"{'enabled' if qcfg.parallel_enabled else 'disabled'} "
                f"(max {qcfg.parallel_max})"
            )
            if qcfg.target and qcfg.target.focus:
                config_data["Focus"] = ", ".join(qcfg.target.focus)
        except Exception:
            pass

    display.show_config(config_data)
    return False


def _cmd_category(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        from ui.selector import interactive_select

        options = [("auto", "auto-detect")] + [
            (c, c) for c in sorted(VALID_CATEGORIES)
        ]
        choice = interactive_select(
            title="Select category:",
            options=options,
            current=state.forced_category or "auto",
        )
        if choice is None:
            return False
        if choice == "auto":
            state.forced_category = None
            display.show_info("Category reset to auto-detect.")
            return False
        arg = choice

    cat = arg.strip().lower()
    if cat == "auto":
        state.forced_category = None
        display.show_info("Category reset to auto-detect.")
        return False

    if cat == "rev":
        cat = "reverse"

    if cat not in VALID_CATEGORIES:
        display.show_error(
            f"Unknown category '{cat}'. Valid: {', '.join(sorted(VALID_CATEGORIES))}"
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
        display.console.print(f"\n  Target URL: [cyan]{current}[/cyan]\n")
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
    # Note: repo_path is intentionally NOT cleared — it persists
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

    report_dir = P.home() / ".q" / "reports"

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
    from utils.audit_log import export_audit_csv, read_audit_log, summarize_audit_log

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
        csv_path = Path.home() / ".q" / "reports" / f"{sid}_audit.csv"
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

    a = arg.strip().lower()
    if not a:
        from ui.selector import interactive_select

        choice = interactive_select(
            title="Verbose mode:",
            options=[("on", "on — show full LLM output"), ("off", "off — compact view")],
            current="on" if state.verbose else "off",
        )
        if choice is None:
            return False
        a = choice

    if a in ("on", "true", "1"):
        state.verbose = True
    elif a in ("off", "false", "0"):
        state.verbose = False
    else:
        state.verbose = not state.verbose

    set_console_verbose(state.verbose)
    status = "ON" if state.verbose else "OFF"
    display.show_info(f"Verbose mode: {status}")
    return False


def _cmd_mode(arg: str, state: ChatState, display: Display) -> bool:
    display.show_info("Single-agent mode (multi-agent pipeline removed)")
    return False


def _cmd_knowledge(arg: str, state: ChatState, display: Display) -> bool:
    from rich.table import Table

    from knowledge.base import KnowledgeBase

    kb = KnowledgeBase()
    parts = arg.split(maxsplit=1) if arg else []
    subcmd = parts[0].lower() if parts else ""

    if subcmd == "search":
        query = parts[1] if len(parts) > 1 else ""
        if not query:
            display.show_error("Usage: /knowledge search <query>")
            return False
        results = kb.search(query, limit=5)
        if not results:
            display.show_info(f"No matches for: {query}")
            return False
        table = Table(title=f'Knowledge: "{query}"')
        table.add_column("Challenge", max_width=40)
        table.add_column("Category")
        table.add_column("Techniques", max_width=30)
        table.add_column("Steps", justify="right")
        table.add_column("Cost", justify="right")
        for r in results:
            table.add_row(
                r.get("challenge", "?")[:40],
                r.get("category", "?"),
                ", ".join(r.get("techniques", [])[:3]),
                str(r.get("steps", "?")),
                f"${r.get('cost', 0):.3f}",
            )
        display.console.print(table)
        return False

    if subcmd == "clear":
        count = len(kb.entries)
        if count == 0:
            display.show_info("Knowledge base is already empty.")
            return False
        kb.clear()
        display.show_info(f"Cleared {count} entries from knowledge base.")
        return False

    if subcmd == "export":
        path = kb.export()
        display.show_info(f"Knowledge exported to {path}")
        return False

    # Default: show stats
    stats = kb.get_stats()
    if stats["total"] == 0:
        display.show_info("Knowledge base is empty. Solve some challenges first!")
        return False

    display.console.print(f"\n  [bold]Knowledge Base[/bold]")
    display.console.print(
        f"  Entries: {stats['total']}  |  Successful: {stats['success']}"
    )
    if stats["by_category"]:
        cats = ", ".join(f"{k}: {v}" for k, v in sorted(stats["by_category"].items()))
        display.console.print(f"  Categories: {cats}")
    if stats["top_techniques"]:
        techs = ", ".join(list(stats["top_techniques"].keys())[:5])
        display.console.print(f"  Top techniques: {techs}")
    if stats["top_tools"]:
        tools = ", ".join(list(stats["top_tools"].keys())[:5])
        display.console.print(f"  Top tools: {tools}")
    display.console.print()
    return False


def _cmd_stats(arg: str, state: ChatState, display: Display) -> bool:
    from rich.table import Table

    from stats.tracker import StatsTracker

    tracker = StatsTracker()
    dashboard = tracker.get_dashboard()

    if "message" in dashboard:
        display.show_info(dashboard["message"])
        return False

    overall = dashboard["overall"]
    streaks = dashboard["streaks"]
    recent = dashboard["recent_7d"]

    display.console.print(f"\n  [bold]Q Stats[/bold]")
    display.console.print(
        f"  Overall: {overall['total']} challenges - "
        f"{overall['success']} solved ({overall['rate']})"
    )
    display.console.print(
        f"  Cost: {overall['total_cost']} total - {overall['avg_cost']} avg"
    )
    streak_str = f"  Streak: {streaks['current']} wins"
    if streaks["best"] > streaks["current"]:
        streak_str += f" - Best: {streaks['best']}"
    display.console.print(streak_str)

    categories = dashboard.get("categories", {})
    if categories:
        table = Table()
        table.add_column("Category")
        table.add_column("Solved")
        table.add_column("Rate")
        table.add_column("Avg Steps", justify="right")
        table.add_column("Avg Cost", justify="right")
        for cat, data in categories.items():
            table.add_row(
                cat,
                data["solved"],
                data["rate"],
                data["avg_steps"],
                data["avg_cost"],
            )
        display.console.print(table)

    display.console.print(
        f"  Last 7 days: {recent['solves']} solves - {recent['success']} success"
    )
    display.console.print()
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

    from rich.table import Table

    from benchmark.runner import BenchmarkRunner

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
    from rich.table import Table

    from utils.session_manager import SessionManager

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


def _cmd_rewind(arg: str, state: ChatState, display: Display) -> bool:
    from datetime import datetime, timezone

    orch = getattr(state, "_rewind_orchestrator", None)
    if orch is None:
        display.show_error("No active solve session. Start solving first.")
        return False

    if arg.strip().lower() == "list":
        checkpoints = orch.list_checkpoints()
        if not checkpoints:
            display.show_info("No checkpoints available.")
            return False
        from rich.table import Table

        table = Table(title="Checkpoints")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Step", justify="right")
        table.add_column("Action", max_width=60)
        table.add_column("Time")
        for i, cp in enumerate(checkpoints, 1):
            ts = datetime.fromtimestamp(cp["timestamp"], tz=timezone.utc)
            table.add_row(
                str(i),
                str(cp["step"]),
                cp["summary"][:60],
                ts.strftime("%H:%M:%S"),
            )
        display.console.print(table)
        return False

    # Parse rewind count
    n = 1
    if arg.strip().isdigit():
        n = int(arg.strip())

    result_msg = orch.rewind(n)
    display.show_info(result_msg)
    display.console.print(
        "  [dim]Type a new hint or instruction before the agent continues.[/dim]\n"
    )
    return False


def _cmd_team(arg: str, state: ChatState, display: Display) -> bool:
    from rich.table import Table

    subcmd = arg.strip().lower()

    # /team on — enable team mode
    if subcmd in ("on", "enable", "start"):
        state.team_mode = True
        display.show_info("Team mode enabled. Next solve will use a coordinated team.")
        return False

    # /team off — disable team mode
    if subcmd in ("off", "disable", "stop"):
        state.team_mode = False
        display.show_info("Team mode disabled. Next solve will use single agent.")
        return False

    # /team tasks — show task board
    if subcmd == "tasks":
        leader = getattr(state, "_team_leader", None)
        if leader and leader._taskboard:
            display.console.print(leader._taskboard.summary())
        else:
            display.show_info("No active team. Start a team solve first.")
        return False

    # /team messages — show message log
    if subcmd == "messages":
        leader = getattr(state, "_team_leader", None)
        if leader and leader._msgbus:
            msgs = leader._msgbus.get_log(limit=20)
            if not msgs:
                display.show_info("No messages yet.")
                return False
            table = Table(title="Team Messages", show_header=True)
            table.add_column("From", style="cyan", max_width=12)
            table.add_column("Type", max_width=10)
            table.add_column("Content", max_width=60)
            for m in msgs:
                table.add_row(m.sender, m.msg_type, m.content[:60])
            display.console.print(table)
        else:
            display.show_info("No active team.")
        return False

    # /team agents — show active teammates with status
    if subcmd == "agents":
        leader = getattr(state, "_team_leader", None)
        if leader:
            teammates = leader.get_active_teammates()
            if not teammates:
                display.show_info("No teammates spawned.")
                return False
            display.show_team_status({"teammates": teammates})
        else:
            display.show_info("No active team.")
        return False

    # /team (no args) — interactive toggle
    if not subcmd:
        from ui.selector import interactive_select

        choice = interactive_select(
            title="Team mode:",
            options=[
                ("on", "on — coordinate multiple agents"),
                ("off", "off — single agent"),
            ],
            current="on" if state.team_mode else "off",
        )
        if choice is None:
            return False
        if choice == "on":
            state.team_mode = True
            display.show_info("Team mode enabled. Next solve will use a coordinated team.")
        else:
            state.team_mode = False
            display.show_info("Team mode disabled. Next solve will use single agent.")
        return False

    display.show_error(f"Unknown /team subcommand: {subcmd}")
    return False


def _cmd_settings(arg: str, state: ChatState, display: Display) -> bool:
    import json

    from rich.table import Table

    settings_file = Path.home() / ".q" / "settings.json"

    # Load current settings
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        settings = {}
    except json.JSONDecodeError as exc:
        display.show_error(f"settings.json is invalid JSON: {exc}")
        return False

    # /settings <key> <value> — update a value
    if arg:
        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            display.show_error("Usage: /settings <key> <value>")
            return False

        key, value = parts[0].strip(), parts[1].strip()

        # Auto-cast value type to match existing type
        if key in settings:
            existing = settings[key]
            try:
                if isinstance(existing, bool):
                    value = value.lower() in ("true", "1", "yes")
                elif isinstance(existing, int):
                    value = int(value)
                elif isinstance(existing, float):
                    value = float(value)
            except ValueError:
                pass  # keep as string

        settings[key] = value
        settings_file.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # Mask key in output
        display_val = (
            ("sk-..." + value[-4:]) if "key" in key and len(value) > 8 else value
        )
        display.show_info(f"Saved: {key} = {display_val}")
        display.show_info(
            "Restart agentq or start a new solve for changes to take effect."
        )
        return False

    # /settings — show all current settings
    _KEY_GROUPS = [
        ("API Keys", ["openai_api_key", "anthropic_api_key", "google_api_key"]),
        (
            "Models",
            ["default_model", "fast_model", "reasoning_model", "fallback_model"],
        ),
        (
            "Agent",
            [
                "max_iterations",
                "max_cost_per_challenge",
                "streaming",
                "temperature",
                "max_tokens",
            ],
        ),
        ("Timeouts", ["shell_timeout", "python_timeout", "network_timeout"]),
        ("Sandbox", ["sandbox_mode", "docker_image", "docker_mem"]),
        ("Logging", ["log_level"]),
    ]

    display.console.print(f"\n  [bold]Settings[/bold]  [dim]{settings_file}[/dim]\n")

    for group_name, keys in _KEY_GROUPS:
        group_vals = {k: settings[k] for k in keys if k in settings}
        if not group_vals:
            continue
        table = Table(title=group_name, show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan", min_width=28)
        table.add_column("Value")
        for k, v in group_vals.items():
            if "key" in k and isinstance(v, str) and len(v) > 8:
                display_v = v[:8] + "..." + v[-4:]
            else:
                display_v = str(v)
            table.add_row(k, display_v)
        display.console.print(table)
        display.console.print()

    display.console.print(
        "  [dim]Set a value: /settings <key> <value>[/dim]\n"
        "  [dim]Example:    /settings openai_api_key sk-...[/dim]\n"
    )
    return False


def _cmd_plan(arg: str, state: ChatState, display: Display) -> bool:
    a = arg.strip().lower()
    if not a:
        from ui.selector import interactive_select

        choice = interactive_select(
            title="Plan mode:",
            options=[("on", "on — review plan before solving"), ("off", "off — solve immediately")],
            current="on" if state.plan_mode else "off",
        )
        if choice is None:
            return False
        a = choice

    if a == "on":
        state.plan_mode = True
        display.show_info(
            "Plan mode ON — review, refine, and approve the attack plan before solving."
        )
    elif a == "off":
        state.plan_mode = False
        display.show_info("Plan mode OFF — solve immediately without planning.")
    return False


def _cmd_flag(arg: str, state: ChatState, display: Display) -> bool:
    if not arg:
        if state.flag_pattern:
            display.console.print(
                f"\n  Flag pattern: [cyan]{state.flag_pattern}[/cyan]\n"
                f"  [dim]Use /flag <pattern> to change, /flag off to clear.[/dim]\n"
            )
        else:
            # Interactive selector for common flag formats
            from ui.selector import interactive_select

            options = [
                ("auto", "auto-detect (all known formats)"),
                (r"NCSA\{[^}]+\}", "NCSA{...}"),
                (r"flag\{[^}]+\}", "flag{...}"),
                (r"FLAG\{[^}]+\}", "FLAG{...}"),
                (r"ctf\{[^}]+\}", "ctf{...}"),
                (r"CTF\{[^}]+\}", "CTF{...}"),
                ("custom", "custom regex..."),
            ]
            choice = interactive_select(
                title="Select flag format:",
                options=options,
                current="auto",
            )
            if choice is None or choice == "auto":
                return False
            if choice == "custom":
                display.show_info("Use: /flag <regex>  e.g. /flag NCSA\\{[^}]+\\}")
                return False
            state.flag_pattern = choice
            display.show_info(f"Flag pattern set: {choice}")
        return False

    a = arg.strip()
    if a.lower() in ("off", "none", "clear", "auto"):
        state.flag_pattern = None
        display.show_info("Flag pattern cleared (using auto-detect).")
        return False

    # Validate the regex
    import re
    try:
        re.compile(a)
    except re.error as exc:
        display.show_error(f"Invalid regex: {exc}")
        return False

    state.flag_pattern = a
    display.show_info(f"Flag pattern set: {a}")
    return False


def _cmd_exit(arg: str, state: ChatState, display: Display) -> bool:
    display.show_goodbye(state.total_session_cost, len(state.solve_history))
    return True
