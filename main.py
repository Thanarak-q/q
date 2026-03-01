"""Entry point for ctf-agent.

Launches the interactive chat mode by default.
Also supports legacy CLI commands via subcommands for batch processing,
session management, and sandbox building.

Usage:
    python main.py              # Interactive chat mode (default)
    python main.py --batch FILE # Batch mode
    python main.py --sessions   # List sessions
    python main.py --replay ID  # Replay a session
    python main.py --resume ID  # Resume a paused/failed session
    python main.py --writeup ID # Export writeup
    python main.py --build      # Build Docker sandbox
    python main.py --tools      # List available tools
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

from ui.display import VERSION

# Minimal theme for non-interactive commands
_THEME = Theme(
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
_console = Console(theme=_THEME)


# ------------------------------------------------------------------
# Batch mode
# ------------------------------------------------------------------


def cmd_batch(args: argparse.Namespace) -> None:
    """Solve multiple challenges from a JSON file."""
    from config import load_config
    from utils.logger import setup_logger

    _console.print(f"[bold]q v{VERSION}[/bold] — Batch Mode\n")

    config = load_config()
    setup_logger(level=config.log.level, log_dir=config.log.log_dir)

    if args.budget is not None:
        from config import AgentConfig, AppConfig

        config = AppConfig(
            model=config.model,
            agent=AgentConfig(
                max_iterations=config.agent.max_iterations,
                stall_threshold=config.agent.stall_threshold,
                context_limit_percent=config.agent.context_limit_percent,
                tool_output_max_chars=config.agent.tool_output_max_chars,
                max_cost_per_challenge=args.budget,
            ),
            tool=config.tool,
            docker=config.docker,
            log=config.log,
            sandbox_mode=config.sandbox_mode,
        )

    # Load challenges
    try:
        with open(args.batch, encoding="utf-8") as fh:
            challenges = json.load(fh)
    except Exception as exc:
        _console.print(f"[error]Failed to load {args.batch}: {exc}[/error]")
        sys.exit(1)

    if not isinstance(challenges, list):
        _console.print("[error]JSON file must contain an array.[/error]")
        sys.exit(1)

    # Docker setup
    docker_mgr = _setup_docker(config) if not args.no_docker else None

    results: list[dict] = []
    total_cost = 0.0
    solved_count = 0

    try:
        for idx, chall in enumerate(challenges, 1):
            _console.rule(f"[bold]Challenge {idx}/{len(challenges)}[/bold]")

            desc = chall.get("description", "")
            if not desc:
                results.append({"index": idx, "status": "skipped"})
                continue

            chall_files = [Path(f) for f in chall.get("files", [])]
            chall_url = chall.get("url")
            chall_flag = chall.get("flag_format")

            workspace = Path.cwd()
            if chall_files:
                workspace = chall_files[0].parent

            from agent.orchestrator import Orchestrator

            orch = Orchestrator(
                config=config,
                docker_manager=docker_mgr,
                workspace=workspace,
                hooks_path=args.hooks,
            )

            result = orch.solve(
                description=desc,
                files=chall_files or None,
                target_url=chall_url,
                flag_pattern=chall_flag,
            )

            total_cost += result.cost_usd
            if result.success:
                solved_count += 1

            results.append({
                "index": idx,
                "description": desc[:60],
                "status": "solved" if result.success else "failed",
                "flags": result.flags,
                "iterations": result.iterations,
                "category": result.category,
                "cost": result.cost_usd,
                "session_id": result.session_id,
            })
    finally:
        if docker_mgr:
            docker_mgr.stop()

    # Summary table
    _console.print()
    _console.rule("[bold]Batch Results[/bold]")
    table = Table(title="Batch Summary")
    table.add_column("#", style="dim")
    table.add_column("Description", max_width=40)
    table.add_column("Status")
    table.add_column("Category")
    table.add_column("Flags")
    table.add_column("Iters", justify="right")
    table.add_column("Cost", justify="right")

    for r in results:
        status_style = "green" if r.get("status") == "solved" else "red"
        table.add_row(
            str(r.get("index", "?")),
            r.get("description", "?"),
            f"[{status_style}]{r.get('status', '?')}[/{status_style}]",
            r.get("category", "?"),
            ", ".join(r.get("flags", [])) or "-",
            str(r.get("iterations", "-")),
            f"${r.get('cost', 0):.4f}",
        )

    _console.print(table)
    _console.print(
        f"\nSolved: {solved_count}/{len(challenges)}  |  "
        f"Total cost: ${total_cost:.4f}"
    )


# ------------------------------------------------------------------
# Sessions
# ------------------------------------------------------------------


def cmd_sessions(args: argparse.Namespace) -> None:
    """List all saved sessions."""
    from config import load_config
    from utils.session_manager import SessionManager

    config = load_config()
    mgr = SessionManager(session_dir=config.log.session_dir)
    sess_list = mgr.list_sessions()

    if not sess_list:
        _console.print("[info]No sessions found.[/info]")
        return

    table = Table(title="Saved Sessions")
    table.add_column("Session ID", style="cyan")
    table.add_column("Status")
    table.add_column("Category")
    table.add_column("Description", max_width=50)
    table.add_column("Iters", justify="right")
    table.add_column("Flags")
    table.add_column("Created")

    for s in sess_list:
        status = s.get("status", "?")
        style = {"solved": "green", "failed": "red", "paused": "yellow"}.get(
            status, "dim"
        )
        table.add_row(
            s.get("session_id", "?"),
            f"[{style}]{status}[/{style}]",
            s.get("category", "?"),
            s.get("description", ""),
            str(s.get("iterations", 0)),
            ", ".join(s.get("flags", [])) or "-",
            s.get("created_at", "")[:19],
        )

    _console.print(table)


# ------------------------------------------------------------------
# Replay
# ------------------------------------------------------------------


def cmd_replay(args: argparse.Namespace) -> None:
    """Replay a saved session step by step."""
    from config import load_config
    from utils.session_manager import SessionManager

    config = load_config()
    mgr = SessionManager(session_dir=config.log.session_dir)
    data = mgr.load(args.replay)

    if data is None:
        _console.print(f"[error]Session {args.replay} not found.[/error]")
        sys.exit(1)

    speed = args.speed if args.speed is not None else 0.5

    _console.print(Panel(
        f"[bold]{data.description[:120]}[/bold]\n\n"
        f"Category: {data.category}  |  Status: {data.status}\n"
        f"Iterations: {data.current_iteration}  |  "
        f"Flags: {', '.join(data.flags) if data.flags else 'None'}",
        title=f"Replay: {args.replay}",
        style="cyan",
    ))

    for step in data.steps:
        event = step.get("event", "?")
        iteration = step.get("iteration", "?")

        if event == "llm_response":
            _console.rule(f"[cyan]Step {iteration}: Agent Thinking[/cyan]")
            content = step.get("content", "")
            if content:
                _console.print(f"[thinking]{content[:2000]}[/thinking]")

        elif event == "tool_call":
            tool = step.get("tool_name", "?")
            tool_args = step.get("tool_args", {})
            output = step.get("tool_output", "")
            _console.rule(f"[yellow]Step {iteration}: Tool `{tool}`[/yellow]")
            _console.print(
                f"[tool_call]Args:[/tool_call] "
                f"{json.dumps(tool_args, ensure_ascii=False)[:300]}"
            )
            if output:
                _console.print(f"[result]{output[:1000]}[/result]")

        elif event == "pivot":
            _console.rule(f"[red]Step {iteration}: Strategy Pivot[/red]")
            _console.print(step.get("content", "Pivot applied."))

        elif event == "summary":
            _console.rule(f"[dim]Step {iteration}: Context Summarized[/dim]")

        if speed > 0:
            time.sleep(speed)

    _console.print()
    if data.flags:
        _console.print(Panel(
            f"[flag]FLAGS: {', '.join(data.flags)}[/flag]",
            title="Result",
            style="bold green",
        ))
    else:
        _console.print(Panel("No flags found.", title="Result", style="bold red"))


# ------------------------------------------------------------------
# Resume
# ------------------------------------------------------------------


def cmd_resume(args: argparse.Namespace) -> None:
    """Resume a paused or failed session from the CLI."""
    from config import load_config
    from utils.logger import setup_logger
    from utils.session_manager import SessionManager

    config = load_config()
    setup_logger(level=config.log.level, log_dir=config.log.log_dir)

    mgr = SessionManager(session_dir=config.log.session_dir)

    # Support --resume latest
    resume_id = args.resume
    if resume_id == "latest":
        sid = mgr.find_latest(status_filter="paused")
        if not sid:
            sid = mgr.find_latest(status_filter="failed")
        if not sid:
            _console.print("[error]No paused or failed sessions to resume.[/error]")
            sys.exit(1)
        resume_id = sid
        _console.print(f"[info]Resuming latest session: {resume_id}[/info]")

    data = mgr.load(resume_id)

    if data is None:
        _console.print(f"[error]Session {resume_id} not found.[/error]")
        sys.exit(1)

    if data.status == "solved":
        _console.print(
            f"[info]Session {resume_id} is already solved. "
            f"Flags: {', '.join(data.flags)}[/info]"
        )
        sys.exit(0)

    _console.print(Panel(
        f"[bold]{data.description[:120]}[/bold]\n\n"
        f"Category: {data.category}  |  Status: {data.status}\n"
        f"Iterations: {data.current_iteration}  |  "
        f"Flags: {', '.join(data.flags) if data.flags else 'None'}",
        title=f"Resuming: {resume_id}",
        style="cyan",
    ))

    docker_mgr = _setup_docker(config) if not args.no_docker else None

    try:
        from agent.orchestrator import Orchestrator

        orch = Orchestrator(
            config=config,
            docker_manager=docker_mgr,
            workspace=Path.cwd(),
            session_manager=mgr,
            hooks_path=args.hooks,
        )

        result = orch.resume(session_id=resume_id)

        _console.print()
        if result.success and result.flags:
            _console.print(Panel(
                f"[flag]FLAGS: {', '.join(result.flags)}[/flag]",
                title="Result",
                style="bold green",
            ))
        elif result.answer:
            _console.print(Panel(
                f"[bold]{result.answer}[/bold]",
                title=f"Answer ({result.answer_confidence})",
                style="green",
            ))
        else:
            _console.print(Panel(
                f"[bold red]{result.summary or 'No flags found.'}[/bold red]",
                title="Result",
                style="red",
            ))

        _console.print(
            f"\nIterations: {result.iterations}  |  "
            f"Cost: ${result.cost_usd:.4f}"
        )
    finally:
        if docker_mgr:
            docker_mgr.stop()


# ------------------------------------------------------------------
# Writeup
# ------------------------------------------------------------------


def cmd_writeup(args: argparse.Namespace) -> None:
    """Export a session as a Markdown writeup."""
    from config import load_config
    from utils.session_manager import SessionManager

    config = load_config()
    mgr = SessionManager(session_dir=config.log.session_dir)
    md = mgr.export_writeup(session_id=args.writeup)

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        _console.print(f"[result]Writeup saved to {args.output}[/result]")
    else:
        _console.print(md)


# ------------------------------------------------------------------
# Build sandbox
# ------------------------------------------------------------------


def cmd_build(args: argparse.Namespace) -> None:
    """Build the Docker sandbox image."""
    import subprocess

    from config import load_config

    _console.print("[info]Building Docker sandbox image...[/info]")
    sandbox_dir = Path(__file__).parent / "sandbox"
    config = load_config()

    result = subprocess.run(
        ["docker", "build", "-t", config.docker.image_name, str(sandbox_dir)],
        capture_output=False,
    )
    if result.returncode == 0:
        _console.print(
            f"[result]Image '{config.docker.image_name}' built successfully.[/result]"
        )
    else:
        _console.print("[error]Docker build failed.[/error]")
        sys.exit(1)


# ------------------------------------------------------------------
# List tools
# ------------------------------------------------------------------


def cmd_tools(args: argparse.Namespace) -> None:
    """List all available tools."""
    from tools.registry import ToolRegistry

    registry = ToolRegistry()
    table = Table(title="Available Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    for name in registry.list_names():
        tool = registry.get(name)
        if tool:
            table.add_row(tool.name, tool.description[:80])

    _console.print(table)


# ------------------------------------------------------------------
# Benchmark
# ------------------------------------------------------------------


def cmd_benchmark(args: argparse.Namespace) -> None:
    """Run benchmark challenges and display results."""
    from benchmark.runner import BenchmarkRunner
    from config import load_config
    from utils.logger import setup_logger

    _console.print(f"[bold]q v{VERSION}[/bold] — Benchmark Mode\n")

    config = load_config()
    setup_logger(level=config.log.level, log_dir=config.log.log_dir)

    runner = BenchmarkRunner(
        challenges_file=args.benchmark,
        budget_override=args.budget,
    )

    results = runner.run()
    summary = runner.summarize(results)

    # Rich table output
    table = Table(title="Benchmark Results")
    table.add_column("ID", style="dim")
    table.add_column("Name", max_width=30)
    table.add_column("Category")
    table.add_column("Passed")
    table.add_column("Budget")
    table.add_column("Steps", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Answer", max_width=30)

    for r in results:
        pass_style = "green" if r.passed else "red"
        budget_style = "green" if r.within_budget else "yellow"
        table.add_row(
            r.id,
            r.name,
            r.category,
            f"[{pass_style}]{'PASS' if r.passed else 'FAIL'}[/{pass_style}]",
            f"[{budget_style}]{'OK' if r.within_budget else 'OVER'}[/{budget_style}]",
            f"{r.steps}/{r.max_steps}",
            f"${r.cost:.4f}",
            f"{r.duration:.1f}s",
            (r.answer[:28] + "..") if len(r.answer) > 30 else r.answer,
        )

    _console.print(table)
    _console.print(
        f"\nPassed: {summary['passed']}/{summary['total_challenges']}  |  "
        f"Pass rate: {summary['pass_rate']}  |  "
        f"Total cost: ${summary['total_cost_usd']:.4f}  |  "
        f"Duration: {summary['total_duration_s']:.1f}s"
    )


# ------------------------------------------------------------------
# Docker helper
# ------------------------------------------------------------------


def _setup_docker(config) -> Optional[object]:
    """Attempt to set up the Docker sandbox."""
    try:
        from sandbox.docker_manager import DockerSandbox

        mgr = DockerSandbox(config=config)
        if mgr.start():
            _console.print("[result]Docker sandbox started.[/result]")
            return mgr
        else:
            _console.print(
                "[info]Docker unavailable - running tools locally.[/info]"
            )
            return None
    except Exception as exc:
        _console.print(
            f"[info]Docker setup failed ({exc}) - running locally.[/info]"
        )
        return None


# ------------------------------------------------------------------
# Argument parser
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ctf-agent",
        description="AI-powered CTF challenge solver. "
        "Launches interactive chat mode by default.",
    )
    parser.add_argument(
        "--version", action="version", version=f"ctf-agent {VERSION}"
    )

    # Utility commands (mutually exclusive)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--batch",
        metavar="FILE",
        help="Solve multiple challenges from a JSON file.",
    )
    group.add_argument(
        "--sessions",
        action="store_true",
        help="List all saved sessions.",
    )
    group.add_argument(
        "--replay",
        metavar="ID",
        help="Replay a saved session step by step.",
    )
    group.add_argument(
        "--resume",
        metavar="ID",
        help="Resume a paused or failed session.",
    )
    group.add_argument(
        "--writeup",
        metavar="ID",
        help="Export a session as a Markdown writeup.",
    )
    group.add_argument(
        "--build",
        action="store_true",
        help="Build the Docker sandbox image.",
    )
    group.add_argument(
        "--tools",
        action="store_true",
        help="List all available agent tools.",
    )
    group.add_argument(
        "--benchmark",
        metavar="FILE",
        help="Run benchmark challenges from a JSON file.",
    )

    # Options for batch/replay/writeup
    parser.add_argument(
        "--no-docker",
        action="store_true",
        default=False,
        help="Disable Docker sandbox (batch mode).",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Override max cost per challenge in USD (batch mode).",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=None,
        help="Seconds between steps in replay (0 = instant).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file path for writeup.",
    )
    parser.add_argument(
        "--config", "-c",
        metavar="FILE",
        default=None,
        help="Path to YAML config file (see configs/example.yaml).",
    )
    parser.add_argument(
        "--repo",
        metavar="PATH",
        default=None,
        help="Path to target app source code for white-box analysis.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable verbose output (full LLM thinking and tool output).",
    )
    # Browser watch mode (browser is always headful now)
    parser.add_argument(
        "--watch",
        action="store_true",
        default=False,
        help="Live Rich dashboard with 2x2 panel layout",
    )

    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Reindex knowledge base entries into vector store",
    )

    parser.add_argument(
        "--hooks",
        metavar="FILE",
        default=None,
        help="Path to hooks YAML configuration file.",
    )

    parser.add_argument(
        "--team",
        action="store_true",
        default=False,
        help="Enable team mode (multiple agents collaborate to solve).",
    )

    # --mode kept for backward compat but ignored (always single agent)
    parser.add_argument(
        "--mode",
        choices=["auto", "single", "multi"],
        default=None,
        help=argparse.SUPPRESS,  # hidden — single agent only now
    )

    return parser


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


def main() -> None:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.reindex:
        from knowledge.base import KnowledgeBase
        from knowledge.embeddings import EmbeddingStore
        kb = KnowledgeBase()
        store = EmbeddingStore()
        if not store.available():
            print("ChromaDB not available. Install: pip install chromadb sentence-transformers")
            return
        count = store.reindex_all(kb._entries)
        print(f"Reindexed {count} entries into vector store")
        return

    # Dispatch to subcommands
    if args.batch:
        cmd_batch(args)
    elif args.sessions:
        cmd_sessions(args)
    elif args.replay:
        cmd_replay(args)
    elif args.resume:
        cmd_resume(args)
    elif args.writeup:
        cmd_writeup(args)
    elif args.build:
        cmd_build(args)
    elif args.tools:
        cmd_tools(args)
    elif args.benchmark:
        cmd_benchmark(args)
    else:
        # Default: interactive chat mode
        from ui.chat import chat_loop

        chat_loop(
            verbose=args.verbose,
            repo_path=args.repo,
            config_path=args.config,
            watch=args.watch,
            team=args.team,
        )


if __name__ == "__main__":
    main()
