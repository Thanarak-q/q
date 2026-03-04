"""Minimal display rendering for ctf-agent interactive mode.

Handles the welcome box, answer/flag output, command tables, and
session summaries.  The solve-loop rendering is handled by the
TaskTree in ui/tree.py — this module covers everything else.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

VERSION = "0.8.0"

# Simplified theme — only the styles still needed
CHAT_THEME = Theme(
    {
        "error": "bold red",
        "flag": "bold green",
        "info": "dim white",
        "prompt": "bold white",
        "command": "dim",
        "success": "bold green",
        "warning": "bold yellow",
        "idle": "yellow",
    }
)


class Display:
    """Handles Rich rendering for the interactive chat UI."""

    def __init__(self) -> None:
        self.console = Console(theme=CHAT_THEME)

    # ------------------------------------------------------------------
    # Welcome screen
    # ------------------------------------------------------------------

    # Capybara mascot visible width (constant across all expressions).
    _CAPY_W = 16

    def show_banner(
        self,
        model: str,
        sandbox: str = "local",
        workspace: str = "~",
        first_run: bool = False,
    ) -> None:
        """Display the startup box with capybara mascot."""
        from ui.mascot import CAPYBARA

        home = str(Path.home())
        short_ws = workspace.replace(home, "~") if home in workspace else workspace

        capy_lines = CAPYBARA.split("\n")

        # Get stats summary if available
        stats_line = ""
        try:
            from stats.tracker import StatsTracker
            stats_line = StatsTracker().get_summary_line() or ""
        except Exception:
            pass

        # Right-side info — each entry is (text, Rich style).
        greeting = "Welcome to q!" if first_run else "Welcome back!"
        right: list[tuple[str, str]] = [
            (greeting, "bold white"),
            ("", ""),
        ]
        if stats_line and not first_run:
            right.append((stats_line, "dim"))
        else:
            right.append(("q is a green capybara CTF solver", "dim"))
        right.extend([
            (short_ws, "dim"),
            ("", ""),
            ("Tips: /help - /stats - /knowledge", "dim"),
        ])

        # Dimensions
        gap = 4
        right_w = max((len(t) for t, _ in right), default=0)
        right_w = max(right_w, 16)
        inner_w = self._CAPY_W + gap + right_w
        box_w = inner_w + 4  # "│ " + content + " │"

        BOX = "rgb(45,138,78)"

        # Header
        title = f" q v{VERSION} "
        dashes = max(0, box_w - 3 - len(title))
        hdr = Text()
        hdr.append(f"\u256d\u2500{title}{'\u2500' * dashes}\u256e", style=BOX)
        self.console.print(hdr)

        # Content lines
        n = max(len(capy_lines), len(right))
        for i in range(n):
            line = Text()
            line.append("\u2502 ", style=BOX)

            # Capybara column
            if i < len(capy_lines):
                line.append_text(Text.from_ansi(capy_lines[i]))
            else:
                line.append(" " * self._CAPY_W)

            line.append(" " * gap)

            # Text column
            if i < len(right):
                txt, sty = right[i]
                pad = right_w - len(txt)
                if txt:
                    line.append(txt, style=sty)
                line.append(" " * pad)
            else:
                line.append(" " * right_w)

            line.append(" \u2502", style=BOX)
            self.console.print(line)

        # Footer
        ftr = Text()
        ftr.append(f"\u2570{'\u2500' * (box_w - 2)}\u256f", style=BOX)
        self.console.print(ftr)
        self.console.print()

    # ------------------------------------------------------------------
    # Answer / flag / done — called after solve
    # ------------------------------------------------------------------

    def show_answer(self, answer: str, confidence: str) -> None:
        """Display the agent's answer in bold green."""
        self.console.print(f"\n[bold green]Answer:[/bold green] {answer}")
        if confidence and confidence != "high":
            self.console.print(f"[dim](confidence: {confidence})[/dim]")

    def show_flag(self, flag: str) -> None:
        """Display a found flag — single line, no panel."""
        self.console.print(f"[bold green]\U0001f6a9 Flag: {flag}[/bold green]")

    def show_done(self, steps: int, tokens: int, cost: float) -> None:
        """Display the final summary line."""
        tokens_str = f"{tokens / 1000:.1f}k" if tokens >= 1000 else str(tokens)
        self.console.print(
            f"[dim]Done ({steps} steps \u00b7 {tokens_str} tokens \u00b7 ${cost:.2f})[/dim]"
        )

    # ------------------------------------------------------------------
    # Mascot result displays — capybara + result side by side
    # ------------------------------------------------------------------

    def _mascot_side_by_side(
        self,
        mascot: str,
        info: list[tuple[str, str]],
    ) -> None:
        """Print mascot art and info lines side by side."""
        capy_lines = mascot.split("\n")
        gap = 3
        n = max(len(capy_lines), len(info))

        self.console.print()
        for i in range(n):
            line = Text()
            line.append(" ")
            if i < len(capy_lines):
                line.append_text(Text.from_ansi(capy_lines[i]))
            else:
                line.append(" " * self._CAPY_W)
            line.append(" " * gap)
            if i < len(info):
                txt, sty = info[i]
                if txt:
                    line.append(txt, style=sty)
            self.console.print(line)
        self.console.print()

    def show_flag_result(
        self,
        flag: str,
        steps: int,
        tokens: int,
        cost: float,
        answer: str | None = None,
        confidence: str = "",
    ) -> None:
        """Display flag found with happy capybara."""
        from ui.mascot import CAPYBARA_HAPPY

        tokens_str = f"{tokens / 1000:.1f}k" if tokens >= 1000 else str(tokens)
        info: list[tuple[str, str]] = [
            ("", ""),
            (f"\U0001f6a9 Flag: {flag}", "bold green"),
        ]
        if answer:
            info.append((answer, "green"))
        info.append(("", ""))
        info.append(
            (f"Done ({steps} steps \u00b7 {tokens_str} tokens \u00b7 ${cost:.2f})", "dim")
        )
        # Pad to capybara height (6 lines)
        while len(info) < 6:
            info.append(("", ""))

        self._mascot_side_by_side(CAPYBARA_HAPPY, info)

    def show_fail_result(
        self,
        steps: int,
        tokens: int,
        cost: float,
    ) -> None:
        """Display solve failure with sad capybara."""
        from ui.mascot import CAPYBARA_SAD

        tokens_str = f"{tokens / 1000:.1f}k" if tokens >= 1000 else str(tokens)
        info: list[tuple[str, str]] = [
            ("", ""),
            ("\u2717 Could not find flag", "bold red"),
            ("", ""),
            (f"Done ({steps} steps \u00b7 {tokens_str} tokens \u00b7 ${cost:.2f})", "dim"),
            ("Try /hint or rephrase", "dim"),
            ("", ""),
        ]
        self._mascot_side_by_side(CAPYBARA_SAD, info)

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
        """Compatibility wrapper — delegates to show_done."""
        self.show_done(iterations, tokens, cost)

    # ------------------------------------------------------------------
    # Errors and info — used during solve and by commands
    # ------------------------------------------------------------------

    def show_plan(self, plan: str, category: str) -> None:
        """Display attack plan panel and prompt hint for user approval."""
        from rich.panel import Panel

        lines = [ln for ln in plan.strip().splitlines() if ln.strip()]
        body = "\n".join(f"  {ln}" for ln in lines)
        self.console.print()
        self.console.print(
            Panel(
                body,
                title=f"[bold]Attack Plan[/bold]  [dim]{category}[/dim]",
                border_style="cyan",
                padding=(0, 1),
            )
        )
        self.console.print()

    def show_error(self, message: str) -> None:
        """Display an error message."""
        self.console.print(f"[error]{message}[/error]")

    def show_info(self, message: str) -> None:
        """Display an informational message."""
        self.console.print(f"[info]{message}[/info]")

    def show_pivot(self, level_name: str, pivot_count: int) -> None:
        """Display a strategy pivot notification."""
        self.console.print(
            f"[warning]Strategy pivot #{pivot_count}: {level_name}[/warning]"
        )

    def show_model_change(self, old_model: str, new_model: str) -> None:
        """Display model change notification."""
        self.console.print(f"[info]Model: {old_model} \u2192 {new_model}[/info]")

    def show_context_summary(self) -> None:
        """Display context summarization notice."""
        self.console.print("[info]Context summarized to free space.[/info]")

    def show_budget_warning(self, warning: str) -> None:
        """Display budget warning."""
        self.console.print(f"[warning]{warning}[/warning]")

    # ------------------------------------------------------------------
    # Command displays — help, config, history, sessions, cost
    # ------------------------------------------------------------------

    def show_help(self, commands: dict[str, str]) -> None:
        """Display help with all available commands."""
        table = Table(show_header=False)
        table.add_column("Command", style="command", min_width=20)
        table.add_column("Description")

        for cmd, desc in commands.items():
            table.add_row(cmd, desc)

        self.console.print(table)
        self.console.print(
            "\n[dim]Or just type a challenge description to start solving.[/dim]\n"
        )

    def show_config(self, config_data: dict) -> None:
        """Display current configuration."""
        table = Table(title="Configuration")
        table.add_column("Setting", style="dim")
        table.add_column("Value")

        for key, val in config_data.items():
            table.add_row(key, str(val))

        self.console.print(table)

    def show_history(self, results: list[dict]) -> None:
        """Display solve history for this session."""
        if not results:
            self.console.print("[info]No challenges solved yet.[/info]")
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

    def show_cost_summary(self, cost_data: dict) -> None:
        """Display cost breakdown table."""
        table = Table(title="Cost Summary")
        table.add_column("Model", style="dim")
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

    def show_sessions_list(self, sessions: list[dict]) -> None:
        """Display saved sessions list."""
        if not sessions:
            self.console.print("[info]No saved sessions found.[/info]")
            return

        table = Table(title="Saved Sessions")
        table.add_column("Session ID", style="dim")
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

    # ------------------------------------------------------------------
    # Goodbye / clear
    # ------------------------------------------------------------------

    def show_goodbye(self, total_cost: float, challenges_solved: int) -> None:
        """Display exit summary — single line."""
        self.console.print(
            f"\n[dim]Session: {challenges_solved} challenges \u00b7 "
            f"${total_cost:.4f} total. Goodbye![/dim]\n"
        )

    def show_team_status(self, team_info: dict) -> None:
        """Display team status summary."""
        table = Table(title="Team Status")
        table.add_column("Agent", style="cyan")
        table.add_column("Role")
        table.add_column("Status")
        table.add_column("Task")

        for mate in team_info.get("teammates", []):
            status_style = {
                "running": "green",
                "done": "dim",
                "waiting": "yellow",
                "idle": "yellow",
            }.get(mate.get("status", ""), "dim")
            table.add_row(
                mate.get("name", "?"),
                mate.get("role", "?"),
                f"[{status_style}]{mate.get('status', '?')}[/{status_style}]",
                mate.get("task", "-")[:50],
            )

        self.console.print(table)

    def show_setup_needed(self) -> None:
        """Display first-run setup instructions when no API key is set."""
        self.console.print(
            "\n[bold yellow]Setup required[/bold yellow]\n\n"
            "  No API key found. Set one to start solving:\n\n"
            "  [bold]/settings openai_api_key sk-...[/bold]       OpenAI\n"
            "  [bold]/settings anthropic_api_key sk-ant-...[/bold]  Anthropic\n\n"
            "  Get keys at:\n"
            "    OpenAI    → [dim]platform.openai.com/api-keys[/dim]\n"
            "    Anthropic → [dim]console.anthropic.com/settings/keys[/dim]\n"
        )

    def clear(self) -> None:
        """Clear the screen."""
        self.console.clear()
