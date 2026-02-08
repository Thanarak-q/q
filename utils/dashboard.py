"""Rich Live dashboard for real-time agent monitoring.

Provides a split-panel layout showing challenge info, agent thinking,
tool outputs, and progress stats simultaneously.
"""

from __future__ import annotations

import time
from typing import Any

from rich.columns import Columns
from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from utils.logger import console


class Dashboard:
    """Real-time CLI dashboard using Rich Live.

    Displays a four-panel layout:
    - TOP: Challenge info + category
    - LEFT: Agent thinking (latest reasoning)
    - RIGHT: Tool outputs (latest results)
    - BOTTOM: Progress bar + stats
    """

    def __init__(self) -> None:
        """Initialise dashboard state."""
        self._challenge_info: str = ""
        self._category: str = ""
        self._thinking: str = ""
        self._tool_output: str = ""
        self._iteration: int = 0
        self._max_iterations: int = 30
        self._tokens: int = 0
        self._cost: float = 0.0
        self._start_time: float = time.monotonic()
        self._flags: list[str] = []
        self._current_model: str = ""
        self._tool_history: list[str] = []
        self._live: Live | None = None

    def start(self) -> None:
        """Start the live dashboard."""
        self._start_time = time.monotonic()
        self._live = Live(
            self._build_layout(),
            console=console,
            refresh_per_second=4,
            screen=False,
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the live dashboard."""
        if self._live:
            self._live.stop()
            self._live = None

    def set_challenge(self, description: str, category: str) -> None:
        """Update the challenge info panel.

        Args:
            description: Challenge description text.
            category: Classified category.
        """
        self._challenge_info = description[:200]
        self._category = category
        self._refresh()

    def set_thinking(self, text: str) -> None:
        """Update the agent thinking panel.

        Args:
            text: Latest reasoning text from the agent.
        """
        self._thinking = text[-1500:]  # keep last 1500 chars
        self._refresh()

    def set_tool_output(self, tool_name: str, output: str) -> None:
        """Update the tool output panel.

        Args:
            tool_name: Name of the tool that produced output.
            output: The tool's output text.
        """
        entry = f"[{tool_name}] {output[:500]}"
        self._tool_history.append(entry)
        # Keep last 5 entries
        self._tool_history = self._tool_history[-5:]
        self._tool_output = "\n---\n".join(self._tool_history)
        self._refresh()

    def set_progress(
        self,
        iteration: int,
        max_iterations: int,
        tokens: int,
        cost: float,
        model: str = "",
    ) -> None:
        """Update progress stats.

        Args:
            iteration: Current iteration.
            max_iterations: Maximum iterations.
            tokens: Total tokens used.
            cost: Total cost in USD.
            model: Current model name.
        """
        self._iteration = iteration
        self._max_iterations = max_iterations
        self._tokens = tokens
        self._cost = cost
        if model:
            self._current_model = model
        self._refresh()

    def add_flag(self, flag: str) -> None:
        """Record a found flag.

        Args:
            flag: The flag string.
        """
        self._flags.append(flag)
        self._refresh()

    def _refresh(self) -> None:
        """Rebuild and push the layout to the live display."""
        if self._live:
            self._live.update(self._build_layout())

    def _build_layout(self) -> Layout:
        """Construct the full dashboard layout.

        Returns:
            Rich Layout object.
        """
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=5),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=5),
        )
        layout["body"].split_row(
            Layout(name="thinking", ratio=1),
            Layout(name="tools", ratio=1),
        )

        # Header — challenge info
        flags_text = f"  |  FLAG: {', '.join(self._flags)}" if self._flags else ""
        header_text = Text.from_markup(
            f"[bold]{self._challenge_info}[/bold]\n"
            f"Category: [cyan]{self._category}[/cyan]  "
            f"Model: [yellow]{self._current_model}[/yellow]"
            f"{flags_text}"
        )
        layout["header"].update(Panel(header_text, title="Challenge", border_style="blue"))

        # Left — thinking
        layout["thinking"].update(
            Panel(
                Text(self._thinking or "(waiting for agent...)", overflow="fold"),
                title="Agent Thinking",
                border_style="cyan",
            )
        )

        # Right — tool outputs
        layout["tools"].update(
            Panel(
                Text(self._tool_output or "(no tool calls yet)", overflow="fold"),
                title="Tool Outputs",
                border_style="yellow",
            )
        )

        # Footer — stats
        elapsed = time.monotonic() - self._start_time
        mins, secs = divmod(int(elapsed), 60)
        pct = (self._iteration / max(self._max_iterations, 1)) * 100

        bar = f"[{'#' * int(pct // 5)}{'.' * (20 - int(pct // 5))}]"

        stats = (
            f"Step {self._iteration}/{self._max_iterations}  "
            f"{bar} {pct:.0f}%  |  "
            f"Tokens: {self._tokens:,}  |  "
            f"Cost: ${self._cost:.4f}  |  "
            f"Time: {mins}m{secs:02d}s"
        )
        layout["footer"].update(
            Panel(Text(stats), title="Progress", border_style="green")
        )

        return layout

    def __enter__(self) -> "Dashboard":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        """Context manager exit."""
        self.stop()
