"""Rich Live dashboard for watch mode."""
from __future__ import annotations

import sys
from typing import Any

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class WatchDisplay:
    """2x2 Rich Live dashboard: Thinking, Tool Output, Progress Tree, Stats."""

    def __init__(self):
        if not HAS_RICH:
            raise RuntimeError("Rich is required for watch mode")
        self._console = Console()
        self._live: Live | None = None
        self._layout = self._build_layout()
        self._thinking_text = ""
        self._tool_output = ""
        self._tree_text = ""
        self._stats_text = ""

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="top", ratio=2),
            Layout(name="bottom", ratio=1),
        )
        layout["top"].split_row(
            Layout(name="thinking"),
            Layout(name="tool_output"),
        )
        layout["bottom"].split_row(
            Layout(name="tree"),
            Layout(name="stats"),
        )
        self._update_panels()
        return layout

    def _update_panels(self) -> None:
        # Thinking panel — show last 30 lines
        thinking_lines = self._thinking_text.split("\n")
        thinking_display = "\n".join(thinking_lines[-30:])
        self._layout["thinking"].update(
            Panel(thinking_display or "Waiting...", title="[bold cyan]Thinking[/]", border_style="cyan")
        )

        # Tool output panel — show last 25 lines
        tool_lines = self._tool_output.split("\n")
        tool_display = "\n".join(tool_lines[-25:])
        self._layout["tool_output"].update(
            Panel(tool_display or "No output yet", title="[bold yellow]Tool Output[/]", border_style="yellow")
        )

        # Tree panel
        self._layout["tree"].update(
            Panel(self._tree_text or "No tasks yet", title="[bold green]Progress[/]", border_style="green")
        )

        # Stats panel
        self._layout["stats"].update(
            Panel(self._stats_text or "Starting...", title="[bold magenta]Stats[/]", border_style="magenta")
        )

    def update_thinking(self, text: str) -> None:
        self._thinking_text = text
        self._refresh()

    def update_thinking_delta(self, delta: str) -> None:
        self._thinking_text += delta
        self._refresh()

    def update_tool_output(self, name: str, output: str) -> None:
        # Truncate long outputs
        lines = output.split("\n")
        if len(lines) > 25:
            output = "\n".join(lines[:25]) + f"\n... ({len(lines) - 25} more lines)"
        self._tool_output = f"[{name}]\n{output}"
        self._refresh()

    def update_tree(self, text: str) -> None:
        self._tree_text = text
        self._refresh()

    def update_stats(
        self,
        step: int,
        max_steps: int,
        cost: float,
        tokens: int,
        model: str,
    ) -> None:
        self._stats_text = (
            f"Step: {step}/{max_steps}\n"
            f"Model: {model}\n"
            f"Tokens: {tokens:,}\n"
            f"Cost: ${cost:.4f}"
        )
        self._refresh()

    def _refresh(self) -> None:
        self._update_panels()
        if self._live:
            self._live.refresh()

    def __enter__(self):
        self._live = Live(
            self._layout,
            console=self._console,
            screen=True,
            refresh_per_second=8,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args):
        if self._live:
            self._live.__exit__(*args)
            self._live = None


class WatchCallbacks:
    """Callbacks that route updates to WatchDisplay panels.

    Extends ChatCallbacks — must be initialized with a ChatCallbacks parent
    to delegate non-watch behavior.
    """

    def __init__(self, parent_callbacks, watch_display: WatchDisplay, tree):
        self._parent = parent_callbacks
        self._watch = watch_display
        self._tree = tree

        # Copy attributes from parent that orchestrator expects
        self._found_flag = parent_callbacks._found_flag
        self._found_answer = parent_callbacks._found_answer
        self._answer_confidence = parent_callbacks._answer_confidence

    def __getattr__(self, name):
        """Delegate any unhandled callback to parent."""
        return getattr(self._parent, name)

    def on_thinking(self, text: str) -> None:
        self._parent.on_thinking(text)
        self._watch.update_thinking(text)
        self._update_tree()

    def on_thinking_delta(self, delta: str) -> None:
        self._watch.update_thinking_delta(delta)

    def on_tool_call(self, name: str, args: dict[str, Any]) -> None:
        self._parent.on_tool_call(name, args)
        self._update_tree()

    def on_tool_result(self, name: str, output: str, success: bool) -> None:
        self._parent.on_tool_result(name, output, success)
        self._watch.update_tool_output(name, output)
        self._update_tree()

    def on_status(self, step: int, max_steps: int, tokens: int, cost: float, model: str) -> None:
        self._parent.on_status(step, max_steps, tokens, cost, model)
        self._watch.update_stats(step, max_steps, cost, tokens, model)

    def on_flag_found(self, flag: str) -> None:
        self._parent.on_flag_found(flag)
        self._found_flag = self._parent._found_flag

    def on_answer(self, answer: str, confidence: float, flag: str | None) -> None:
        self._parent.on_answer(answer, confidence, flag)
        self._found_answer = self._parent._found_answer
        self._answer_confidence = self._parent._answer_confidence
        self._found_flag = self._parent._found_flag

    def _update_tree(self) -> None:
        try:
            tree_str = self._tree.render_to_string()
            self._watch.update_tree(tree_str)
        except Exception:
            pass
