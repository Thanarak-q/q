"""CLI entry point for ctf-agent.

Provides a Rich-powered command-line interface for solving CTF
challenges, batch processing, session replay, and writeup export.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import load_config
from utils.logger import console, setup_logger

BANNER = r"""
   _____ _______ ______            _____            _
  / ____|__   __|  ____|     /\   / ____|          | |
 | |       | |  | |__       /  \ | |  __  ___ _ __ | |_
 | |       | |  |  __|     / /\ \| | |_ |/ _ \ '_ \| __|
 | |____   | |  | |       / ____ \ |__| |  __/ | | | |_
  \_____|  |_|  |_|      /_/    \_\_____|\___|_| |_|\__|
"""


@click.group()
@click.version_option(version="0.2.0", prog_name="ctf-agent")
def cli() -> None:
    """AI-powered CTF challenge solver."""
    pass


# ------------------------------------------------------------------
# solve — main solve command
# ------------------------------------------------------------------

@cli.command()
@click.argument("description", required=False)
@click.option("--file", "-f", "files", multiple=True, type=click.Path(exists=True), help="Challenge file(s) to analyse.")
@click.option("--url", "-u", "target_url", default=None, help="Target service URL (e.g. http://host:port).")
@click.option("--flag-format", default=None, help="Custom flag regex pattern.")
@click.option("--model", default=None, help="Override default LLM model.")
@click.option("--no-docker", is_flag=True, default=False, help="Disable Docker sandbox.")
@click.option("--interactive", "-i", is_flag=True, default=False, help="Interactive mode.")
@click.option("--max-iter", default=None, type=int, help="Override max iterations.")
@click.option("--dashboard", "enable_dashboard", is_flag=True, default=False, help="Enable Rich live dashboard.")
@click.option("--budget", default=None, type=float, help="Override max cost per challenge (USD).")
@click.option("--resume", "resume_id", default=None, help="Resume a paused session by ID.")
def solve(
    description: Optional[str],
    files: tuple[str, ...],
    target_url: Optional[str],
    flag_format: Optional[str],
    model: Optional[str],
    no_docker: bool,
    interactive: bool,
    max_iter: Optional[int],
    enable_dashboard: bool,
    budget: Optional[float],
    resume_id: Optional[str],
) -> None:
    """Solve a CTF challenge.

    Provide a DESCRIPTION as a positional argument, or use --interactive
    to enter details step by step.

    Examples:

        python main.py solve "RSA challenge with small e"

        python main.py solve --file chall.zip --url http://target:8080

        python main.py solve --interactive

        python main.py solve --resume 20250101_120000_abc123
    """
    console.print(Text(BANNER, style="bold cyan"))
    console.print(Panel("AI-Powered CTF Challenge Solver", style="bold"))

    config = load_config()
    log = setup_logger(level=config.log.level, log_dir=config.log.log_dir)

    # Override config if CLI flags provided
    if model:
        config = _override_model(config, model)
    if max_iter:
        config = _override_max_iter(config, max_iter)
    if budget is not None:
        config = _override_budget(config, budget)

    # Docker sandbox setup
    docker_mgr = None
    if not no_docker:
        docker_mgr = _setup_docker(config)

    # Workspace
    file_paths = [Path(f) for f in files] if files else None
    workspace = Path.cwd()
    if file_paths:
        workspace = file_paths[0].parent

    from agent.orchestrator import Orchestrator

    orch = Orchestrator(
        config=config,
        docker_manager=docker_mgr,
        workspace=workspace,
        enable_dashboard=enable_dashboard,
    )

    try:
        # Resume mode
        if resume_id:
            result = orch.resume(
                session_id=resume_id,
                flag_pattern=flag_format,
            )
        else:
            # Interactive mode
            if interactive:
                description, files, target_url, flag_format = _interactive_prompt(
                    description, files, target_url, flag_format
                )

            if not description:
                console.print(
                    "[error]No challenge description provided. "
                    "Use --interactive or pass a description.[/error]"
                )
                sys.exit(1)

            result = orch.solve(
                description=description,
                files=file_paths,
                target_url=target_url,
                flag_pattern=flag_format,
            )
    except KeyboardInterrupt:
        console.print("\n[error]Interrupted by user.[/error]")
        result = None
    finally:
        if docker_mgr:
            docker_mgr.stop()

    # Display results
    _display_result(result)


# ------------------------------------------------------------------
# batch — solve multiple challenges from a JSON file
# ------------------------------------------------------------------

@cli.command()
@click.argument("challenges_file", type=click.Path(exists=True))
@click.option("--no-docker", is_flag=True, default=False, help="Disable Docker sandbox.")
@click.option("--dashboard", "enable_dashboard", is_flag=True, default=False, help="Enable Rich live dashboard.")
@click.option("--budget", default=None, type=float, help="Override max cost per challenge (USD).")
def batch(
    challenges_file: str,
    no_docker: bool,
    enable_dashboard: bool,
    budget: Optional[float],
) -> None:
    """Solve multiple challenges from a JSON file.

    The JSON file should be an array of objects, each with:
      - description (required)
      - files (optional, list of paths)
      - url (optional)
      - flag_format (optional)

    Example:

        python main.py batch challenges.json
    """
    console.print(Text(BANNER, style="bold cyan"))
    console.print(Panel("Batch Mode", style="bold"))

    config = load_config()
    log = setup_logger(level=config.log.level, log_dir=config.log.log_dir)
    if budget is not None:
        config = _override_budget(config, budget)

    # Load challenges
    try:
        with open(challenges_file, encoding="utf-8") as fh:
            challenges = json.load(fh)
    except Exception as exc:
        console.print(f"[error]Failed to load {challenges_file}: {exc}[/error]")
        sys.exit(1)

    if not isinstance(challenges, list):
        console.print("[error]JSON file must contain an array of challenge objects.[/error]")
        sys.exit(1)

    # Docker setup (shared across all challenges)
    docker_mgr = None
    if not no_docker:
        docker_mgr = _setup_docker(config)

    results: list[dict] = []
    total_cost = 0.0
    solved_count = 0

    try:
        for idx, chall in enumerate(challenges, 1):
            console.rule(f"[bold]Challenge {idx}/{len(challenges)}[/bold]")

            desc = chall.get("description", "")
            if not desc:
                console.print(f"[error]Challenge {idx} has no description, skipping.[/error]")
                results.append({"index": idx, "status": "skipped", "reason": "no description"})
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
                enable_dashboard=enable_dashboard,
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

            console.print()
    finally:
        if docker_mgr:
            docker_mgr.stop()

    # Summary table
    console.print()
    console.rule("[bold]Batch Results[/bold]")
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

    console.print(table)
    console.print(
        f"\nSolved: {solved_count}/{len(challenges)}  |  "
        f"Total cost: ${total_cost:.4f}"
    )


# ------------------------------------------------------------------
# sessions — list saved sessions
# ------------------------------------------------------------------

@cli.command()
def sessions() -> None:
    """List all saved sessions."""
    from utils.session_manager import SessionManager

    config = load_config()
    mgr = SessionManager(session_dir=config.log.session_dir)
    sess_list = mgr.list_sessions()

    if not sess_list:
        console.print("[info]No sessions found.[/info]")
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
        status_style = {"solved": "green", "failed": "red", "paused": "yellow"}.get(status, "dim")
        table.add_row(
            s.get("session_id", "?"),
            f"[{status_style}]{status}[/{status_style}]",
            s.get("category", "?"),
            s.get("description", ""),
            str(s.get("iterations", 0)),
            ", ".join(s.get("flags", [])) or "-",
            s.get("created_at", "")[:19],
        )

    console.print(table)


# ------------------------------------------------------------------
# replay — replay a session step by step
# ------------------------------------------------------------------

@cli.command()
@click.argument("session_id")
@click.option("--speed", default=0.5, type=float, help="Seconds between steps (0 = instant).")
def replay(session_id: str, speed: float) -> None:
    """Replay a saved session step by step.

    Example:

        python main.py replay 20250101_120000_abc123

        python main.py replay 20250101_120000_abc123 --speed 0
    """
    from utils.session_manager import SessionManager

    config = load_config()
    mgr = SessionManager(session_dir=config.log.session_dir)
    data = mgr.load(session_id)

    if data is None:
        console.print(f"[error]Session {session_id} not found.[/error]")
        sys.exit(1)

    console.print(Panel(
        f"[bold]{data.description[:120]}[/bold]\n\n"
        f"Category: {data.category}  |  Status: {data.status}\n"
        f"Iterations: {data.current_iteration}  |  "
        f"Flags: {', '.join(data.flags) if data.flags else 'None'}",
        title=f"Replay: {session_id}",
        style="cyan",
    ))

    for step in data.steps:
        event = step.get("event", "?")
        iteration = step.get("iteration", "?")

        if event == "llm_response":
            console.rule(f"[cyan]Step {iteration}: Agent Thinking[/cyan]")
            content = step.get("content", "")
            if content:
                console.print(f"[thinking]{content[:2000]}[/thinking]")

        elif event == "tool_call":
            tool = step.get("tool_name", "?")
            args = step.get("tool_args", {})
            output = step.get("tool_output", "")
            console.rule(f"[yellow]Step {iteration}: Tool `{tool}`[/yellow]")
            console.print(f"[tool_call]Args:[/tool_call] {json.dumps(args, ensure_ascii=False)[:300]}")
            if output:
                console.print(f"[result]{output[:1000]}[/result]")

        elif event == "pivot":
            console.rule(f"[red]Step {iteration}: Strategy Pivot[/red]")
            console.print(step.get("content", "Pivot applied."))

        elif event == "summary":
            console.rule(f"[dim]Step {iteration}: Context Summarized[/dim]")

        if speed > 0:
            time.sleep(speed)

    console.print()
    if data.flags:
        console.print(Panel(
            f"[flag]FLAGS: {', '.join(data.flags)}[/flag]",
            title="Result",
            style="bold green",
        ))
    else:
        console.print(Panel("No flags found.", title="Result", style="bold red"))


# ------------------------------------------------------------------
# writeup — export a session as markdown
# ------------------------------------------------------------------

@cli.command()
@click.argument("session_id")
@click.option("--output", "-o", default=None, help="Output file path (default: stdout).")
def writeup(session_id: str, output: Optional[str]) -> None:
    """Export a session as a Markdown writeup.

    Example:

        python main.py writeup 20250101_120000_abc123

        python main.py writeup 20250101_120000_abc123 -o writeup.md
    """
    from utils.session_manager import SessionManager

    config = load_config()
    mgr = SessionManager(session_dir=config.log.session_dir)
    md = mgr.export_writeup(session_id=session_id)

    if output:
        Path(output).write_text(md, encoding="utf-8")
        console.print(f"[result]Writeup saved to {output}[/result]")
    else:
        console.print(md)


# ------------------------------------------------------------------
# build-sandbox — build the Docker image
# ------------------------------------------------------------------

@cli.command()
def build_sandbox() -> None:
    """Build the Docker sandbox image."""
    import subprocess

    console.print("[info]Building Docker sandbox image...[/info]")
    sandbox_dir = Path(__file__).parent / "sandbox"
    config = load_config()

    result = subprocess.run(
        ["docker", "build", "-t", config.docker.image_name, str(sandbox_dir)],
        capture_output=False,
    )
    if result.returncode == 0:
        console.print(
            f"[result]Image '{config.docker.image_name}' built successfully.[/result]"
        )
    else:
        console.print("[error]Docker build failed.[/error]")
        sys.exit(1)


# ------------------------------------------------------------------
# list-tools — show available tools
# ------------------------------------------------------------------

@cli.command()
def list_tools() -> None:
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

    console.print(table)


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------


def _display_result(result) -> None:
    """Display the solve result to the console.

    Args:
        result: SolveResult or None.
    """
    if result is None:
        sys.exit(1)

    console.print()
    if result.success:
        console.print(Panel(
            f"[flag]FLAG: {', '.join(result.flags)}[/flag]\n\n"
            f"Category: {result.category}\n"
            f"Iterations: {result.iterations}\n"
            f"Cost: ${result.cost_usd:.4f}\n"
            f"Tokens: {result.total_tokens:,}\n"
            f"Session: {result.session_id}",
            title="Challenge Solved!",
            style="bold green",
        ))
    else:
        console.print(Panel(
            f"Could not find the flag after {result.iterations} iterations.\n"
            f"Category: {result.category}\n"
            f"Cost: ${result.cost_usd:.4f}\n"
            f"Tokens: {result.total_tokens:,}\n"
            f"Session: {result.session_id}\n"
            f"Summary: {result.summary}",
            title="Solve Failed",
            style="bold red",
        ))
        sys.exit(1)


def _interactive_prompt(
    description: Optional[str],
    files: tuple[str, ...],
    target_url: Optional[str],
    flag_format: Optional[str],
) -> tuple[str, tuple[str, ...], Optional[str], Optional[str]]:
    """Prompt the user interactively for challenge details.

    Args:
        description: Pre-filled description or None.
        files: Pre-filled files tuple.
        target_url: Pre-filled URL or None.
        flag_format: Pre-filled flag format or None.

    Returns:
        Tuple of (description, files, target_url, flag_format).
    """
    console.print("\n[bold]Interactive Challenge Setup[/bold]\n")

    if not description:
        description = click.prompt("Challenge description", type=str)

    if not files:
        raw = click.prompt(
            "Challenge file paths (comma-separated, or empty)",
            default="",
            show_default=False,
        )
        if raw.strip():
            files = tuple(f.strip() for f in raw.split(","))

    if not target_url:
        target_url = (
            click.prompt("Target URL (or empty)", default="", show_default=False)
            or None
        )

    if not flag_format:
        flag_format = (
            click.prompt(
                "Custom flag format regex (or empty)",
                default="",
                show_default=False,
            )
            or None
        )

    return description, files, target_url, flag_format


def _setup_docker(config) -> Optional[object]:
    """Attempt to set up the Docker sandbox.

    Args:
        config: Application configuration.

    Returns:
        DockerSandbox instance if successful, None otherwise.
    """
    try:
        from sandbox.docker_manager import DockerSandbox

        mgr = DockerSandbox(config=config)
        if mgr.start():
            console.print("[result]Docker sandbox started.[/result]")
            return mgr
        else:
            console.print(
                "[info]Docker sandbox unavailable — running tools locally.[/info]"
            )
            return None
    except Exception as exc:
        console.print(
            f"[info]Docker setup failed ({exc}) — running tools locally.[/info]"
        )
        return None


def _override_model(config, model: str):
    """Create a new config with an overridden default model.

    Args:
        config: Original configuration.
        model: New model name.

    Returns:
        New AppConfig with the model overridden.
    """
    from config import AppConfig, ModelConfig

    return AppConfig(
        model=ModelConfig(
            fast_model=config.model.fast_model,
            default_model=model,
            reasoning_model=config.model.reasoning_model,
            api_key=config.model.api_key,
            temperature=config.model.temperature,
            max_tokens=config.model.max_tokens,
        ),
        agent=config.agent,
        tool=config.tool,
        docker=config.docker,
        log=config.log,
        sandbox_mode=config.sandbox_mode,
    )


def _override_max_iter(config, max_iter: int):
    """Create a new config with overridden max iterations.

    Args:
        config: Original configuration.
        max_iter: New max iteration count.

    Returns:
        New AppConfig with max_iterations overridden.
    """
    from config import AgentConfig, AppConfig

    return AppConfig(
        model=config.model,
        agent=AgentConfig(
            max_iterations=max_iter,
            stall_threshold=config.agent.stall_threshold,
            context_limit_percent=config.agent.context_limit_percent,
            tool_output_max_chars=config.agent.tool_output_max_chars,
            max_cost_per_challenge=config.agent.max_cost_per_challenge,
        ),
        tool=config.tool,
        docker=config.docker,
        log=config.log,
        sandbox_mode=config.sandbox_mode,
    )


def _override_budget(config, budget: float):
    """Create a new config with overridden cost budget.

    Args:
        config: Original configuration.
        budget: New budget limit in USD.

    Returns:
        New AppConfig with max_cost_per_challenge overridden.
    """
    from config import AgentConfig, AppConfig

    return AppConfig(
        model=config.model,
        agent=AgentConfig(
            max_iterations=config.agent.max_iterations,
            stall_threshold=config.agent.stall_threshold,
            context_limit_percent=config.agent.context_limit_percent,
            tool_output_max_chars=config.agent.tool_output_max_chars,
            max_cost_per_challenge=budget,
        ),
        tool=config.tool,
        docker=config.docker,
        log=config.log,
        sandbox_mode=config.sandbox_mode,
    )


if __name__ == "__main__":
    cli()
