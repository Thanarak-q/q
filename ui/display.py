"""Rich display rendering for ctf-agent interactive mode.

Handles banner, thinking output, tool calls, flag celebrations,
status bar, and all visual formatting.
"""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Theme for the interactive UI
CHAT_THEME = Theme(
    {
        "thinking": "cyan",
        "tool_call": "bold yellow",
        "tool_args": "dim",
        "result": "green",
        "error": "bold red",
        "flag": "bold green",
        "info": "dim white",
        "prompt": "bold white",
        "banner": "bold cyan",
        "status": "dim cyan",
        "command": "bold magenta",
        "success": "bold green",
        "warning": "bold yellow",
        "header": "bold white on blue",
    }
)

BANNER = r"""
   _____ _______ ______            _____            _
  / ____|__   __|  ____|     /\   / ____|          | |
 | |       | |  | |__       /  \ | |  __  ___ _ __ | |_
 | |       | |  |  __|     / /\ \| | |_ |/ _ \ '_ \| __|
 | |____   | |  | |       / ____ \ |__| |  __/ | | | |_
  \_____|  |_|  |_|      /_/    \_\_____|\___|_| |_|\__|
"""

VERSION = "0.3.0"


class Display:
    """Handles all Rich rendering for the interactive chat UI."""

    def __init__(self) -> None:
        self.console = Console(theme=CHAT_THEME)

    def show_banner(self, model: str) -> None:
        """Display the startup banner with version and model info."""
        self.console.print(Text(BANNER, style="banner"))
        self.console.print(
            f"  [bold]CTF Agent[/bold] v{VERSION}  |  "
            f"Model: [cyan]{model}[/cyan]  |  "
            f"Type [command]/help[/command] for commands\n"
        )

    def show_welcome(self) -> None:
        """Display the welcome box with usage instructions."""
        self.console.print(
            Panel(
                "[bold]Welcome to CTF Agent Interactive Mode[/bold]\n\n"
                "  Describe a CTF challenge and I'll solve it for you.\n\n"
                "  [dim]Examples:[/dim]\n"
                '  [dim]>[/dim] This RSA challenge uses e=3 with small n\n'
                '  [dim]>[/dim] Web login bypass at http://target:8080\n'
                '  [dim]>[/dim] /file challenge.zip  [dim](load file first)[/dim]\n'
                '  [dim]>[/dim] /help  [dim](see all commands)[/dim]\n\n'
                "  [dim]Use triple quotes for multi-line input:[/dim]\n"
                '  [dim]>[/dim] """\n'
                "  [dim]   n = 12345...\n"
                '     e = 3\n'
                '     """[/dim]',
                style="cyan",
                title="[bold]CTF Agent[/bold]",
                border_style="cyan",
            )
        )

    def show_thinking(self, text: str) -> None:
        """Display agent thinking/reasoning text."""
        self.console.print(f"  [thinking]{text}[/thinking]")

    def show_thinking_start(self) -> None:
        """Display the thinking indicator."""
        self.console.print("  [thinking]Thinking...[/thinking]")

    def show_tool_call(self, tool_name: str, args: dict) -> None:
        """Display a tool call with its arguments."""
        import json

        args_str = json.dumps(args, ensure_ascii=False)
        if len(args_str) > 300:
            args_str = args_str[:300] + "..."
        self.console.print(f"\n  [tool_call]Tool: {tool_name}[/tool_call]")
        self.console.print(f"  [tool_args]{args_str}[/tool_args]")

    def show_tool_result(self, output: str, success: bool = True) -> None:
        """Display the result of a tool execution."""
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"
        style = "result" if success else "error"
        prefix = " " if success else " "
        self.console.print(f"  [{style}]{prefix}{output}[/{style}]")

    def show_error(self, message: str) -> None:
        """Display an error message."""
        self.console.print(f"\n  [error]{message}[/error]")

    def show_flag(self, flag: str) -> None:
        """Display a found flag with celebration."""
        self.console.print()
        self.console.print(
            Panel(
                f"[flag]FLAG FOUND: {flag}[/flag]",
                style="bold green",
                title="[bold green]Captured![/bold green]",
                border_style="green",
            )
        )

    def show_solve_complete(
        self,
        success: bool,
        flags: list[str],
        iterations: int,
        cost: float,
        tokens: int,
        category: str,
        session_id: str,
    ) -> None:
        """Display the solve result summary."""
        if success:
            self.console.print(
                Panel(
                    f"[flag]Flags: {', '.join(flags)}[/flag]\n"
                    f"Category: {category}  |  Steps: {iterations}\n"
                    f"Cost: ${cost:.4f}  |  Tokens: {tokens:,}\n"
                    f"Session: {session_id}",
                    title="[bold green]Challenge Solved![/bold green]",
                    style="green",
                    border_style="green",
                )
            )
        else:
            self.console.print(
                Panel(
                    f"Could not find the flag after {iterations} steps.\n"
                    f"Category: {category}  |  Cost: ${cost:.4f}\n"
                    f"Session: {session_id}",
                    title="[bold red]Solve Failed[/bold red]",
                    style="red",
                    border_style="red",
                )
            )
        self.console.print()

    def show_status_bar(
        self,
        model: str,
        step: int,
        max_steps: int,
        tokens: int,
        cost: float,
    ) -> None:
        """Display the status bar at the bottom."""
        tokens_str = f"{tokens / 1000:.1f}k" if tokens >= 1000 else str(tokens)
        self.console.print(
            f"  [status]Model: {model}  |  "
            f"Steps: {step}/{max_steps}  |  "
            f"Tokens: {tokens_str}  |  "
            f"Cost: ${cost:.4f}[/status]"
        )

    def show_info(self, message: str) -> None:
        """Display an informational message."""
        self.console.print(f"  [info]{message}[/info]")

    def show_pivot(self, level_name: str, pivot_count: int) -> None:
        """Display a strategy pivot notification."""
        self.console.print(
            f"\n  [warning]Strategy Pivot #{pivot_count}: "
            f"{level_name}[/warning]"
        )

    def show_model_change(self, old_model: str, new_model: str) -> None:
        """Display model change notification."""
        self.console.print(
            f"  [info]Model: {old_model} -> {new_model}[/info]"
        )

    def show_iteration_header(self, current: int, total: int) -> None:
        """Display the iteration separator."""
        self.console.rule(
            f"[bold]Step {current}/{total}[/bold]", style="dim"
        )

    def show_context_summary(self) -> None:
        """Display context summarization notice."""
        self.console.print("  [info]Context summarized to free space.[/info]")

    def show_budget_warning(self, warning: str) -> None:
        """Display budget warning."""
        self.console.print(f"  [warning]{warning}[/warning]")

    def show_cost_summary(self, cost_data: dict) -> None:
        """Display cost breakdown table."""
        table = Table(title="Cost Summary")
        table.add_column("Model", style="cyan")
        table.add_column("Calls", justify="right")
        table.add_column("Input Tokens", justify="right")
        table.add_column("Output Tokens", justify="right")
        table.add_column("Cost", justify="right", style="green")

        per_model = cost_data.get("per_model", {})
        for model_name, stats in per_model.items():
            table.add_row(
                model_name,
                str(stats.get("calls", 0)),
                f"{stats.get('prompt_tokens', 0):,}",
                f"{stats.get('completion_tokens', 0):,}",
                f"${stats.get('cost_usd', 0):.4f}",
            )

        table.add_section()
        table.add_row(
            "[bold]Total[/bold]",
            str(cost_data.get("call_count", 0)),
            f"{cost_data.get('total_prompt_tokens', 0):,}",
            f"{cost_data.get('total_completion_tokens', 0):,}",
            f"[bold]${cost_data.get('total_cost_usd', 0):.4f}[/bold]",
        )

        self.console.print(table)

    def show_history(self, results: list[dict]) -> None:
        """Display solve history for this session."""
        if not results:
            self.console.print("  [info]No challenges solved yet.[/info]")
            return

        table = Table(title="Session History")
        table.add_column("#", style="dim")
        table.add_column("Description", max_width=50)
        table.add_column("Status")
        table.add_column("Category")
        table.add_column("Flags")
        table.add_column("Steps", justify="right")
        table.add_column("Cost", justify="right")

        for i, r in enumerate(results, 1):
            status = r.get("status", "?")
            style = "green" if status == "solved" else "red"
            table.add_row(
                str(i),
                r.get("description", "?")[:50],
                f"[{style}]{status}[/{style}]",
                r.get("category", "?"),
                ", ".join(r.get("flags", [])) or "-",
                str(r.get("iterations", 0)),
                f"${r.get('cost', 0):.4f}",
            )

        self.console.print(table)

    def show_config(self, config_data: dict) -> None:
        """Display current configuration."""
        table = Table(title="Current Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value")

        for key, val in config_data.items():
            table.add_row(key, str(val))

        self.console.print(table)

    def show_sessions_list(self, sessions: list[dict]) -> None:
        """Display saved sessions list."""
        if not sessions:
            self.console.print("  [info]No saved sessions found.[/info]")
            return

        table = Table(title="Saved Sessions")
        table.add_column("Session ID", style="cyan")
        table.add_column("Status")
        table.add_column("Category")
        table.add_column("Description", max_width=40)
        table.add_column("Flags")

        for s in sessions:
            status = s.get("status", "?")
            style = {"solved": "green", "failed": "red", "paused": "yellow"}.get(
                status, "dim"
            )
            table.add_row(
                s.get("session_id", "?"),
                f"[{style}]{status}[/{style}]",
                s.get("category", "?"),
                s.get("description", "")[:40],
                ", ".join(s.get("flags", [])) or "-",
            )

        self.console.print(table)

    def show_help(self, commands: dict[str, str]) -> None:
        """Display help with all available commands."""
        table = Table(title="Available Commands", show_header=False)
        table.add_column("Command", style="command", min_width=20)
        table.add_column("Description")

        for cmd, desc in commands.items():
            table.add_row(cmd, desc)

        self.console.print(table)
        self.console.print(
            "\n  [dim]Or just type a challenge description to start solving.[/dim]\n"
        )

    def clear(self) -> None:
        """Clear the screen."""
        self.console.clear()

    def show_goodbye(self, total_cost: float, challenges_solved: int) -> None:
        """Display exit summary."""
        self.console.print(
            Panel(
                f"Challenges solved: {challenges_solved}\n"
                f"Total session cost: ${total_cost:.4f}\n\n"
                "[dim]Goodbye![/dim]",
                title="[bold]Session Summary[/bold]",
                style="cyan",
                border_style="cyan",
            )
        )
