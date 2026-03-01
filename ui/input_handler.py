"""Interactive input handler using prompt_toolkit.

Replaces raw input() with a full-featured line editor that supports:
- Arrow key navigation (no more [D, [A escape codes)
- Slash command autocomplete with descriptions
- Persistent command history (~/.q_history)
- Ctrl+R history search
- Home/End, Ctrl+A/E cursor movement
- Graceful Ctrl+C / Ctrl+D handling
"""

from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style


# ------------------------------------------------------------------
# Slash command completer
# ------------------------------------------------------------------


class SlashCommandCompleter(Completer):
    """Show command suggestions when user types /."""

    _cache: dict[str, str] | None = None

    def _get_commands(self) -> dict[str, str]:
        if self._cache is None:
            try:
                from ui.commands import COMMAND_HELP
                result = {}
                for key, desc in COMMAND_HELP.items():
                    for part in key.replace(",", " ").split():
                        if part.startswith("/") and part not in result:
                            result[part] = desc
                self._cache = result
            except Exception:
                self._cache = {}
        return self._cache

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        if not text.lstrip().startswith("/"):
            return

        word = text.lstrip()

        # Don't complete if user is already typing arguments
        if " " in word:
            return

        for cmd, desc in sorted(self._get_commands().items()):
            if cmd.startswith(word):
                yield Completion(
                    cmd,
                    start_position=-len(word),
                    display=cmd,
                    display_meta=desc,
                )


# ------------------------------------------------------------------
# Style — green capybara theme
# ------------------------------------------------------------------

Q_STYLE = Style.from_dict({
    "prompt": "#00ff00 bold",
    "completion-menu": "bg:#1a1a2e #e0e0e0",
    "completion-menu.completion": "bg:#1a1a2e #e0e0e0",
    "completion-menu.completion.current": "bg:#00ff00 #000000",
    "completion-menu.meta.completion": "bg:#1a1a2e #888888",
    "completion-menu.meta.completion.current": "bg:#00ff00 #333333",
    "scrollbar.background": "bg:#1a1a2e",
    "scrollbar.button": "bg:#00ff00",
})


# ------------------------------------------------------------------
# QInput — main input handler
# ------------------------------------------------------------------


class QInput:
    """Interactive input handler with autocomplete, history, and arrow keys.

    Features:
    - Arrow keys work properly (no more [D / [A escape codes)
    - Tab / auto-complete for slash commands
    - Up/Down arrow for command history
    - Ctrl+R for reverse history search
    - Home/End to jump to start/end of line
    - Ctrl+C returns sentinel, Ctrl+D returns /exit
    """

    # Sentinel value returned on Ctrl+C
    CTRL_C = "__CTRL_C__"

    def __init__(self, history_file: str = "~/.q/history") -> None:
        history_path = os.path.expanduser(history_file)
        # Ensure parent directory exists
        Path(history_path).parent.mkdir(parents=True, exist_ok=True)

        self._session: PromptSession = PromptSession(
            completer=SlashCommandCompleter(),
            history=FileHistory(history_path),
            style=Q_STYLE,
            complete_while_typing=True,
            complete_in_thread=True,
            enable_history_search=True,
            reserve_space_for_menu=8,
        )

    def get_input(self, prompt_text: str = "> ") -> str | None:
        """Read one line of input with full line-editing support.

        Returns:
            User input string (stripped).
            CTRL_C sentinel on Ctrl+C.
            None on Ctrl+D (EOF).
        """
        try:
            result = self._session.prompt(
                HTML(f"<prompt>{prompt_text}</prompt>")
            )
            return result.strip()
        except KeyboardInterrupt:
            return self.CTRL_C
        except EOFError:
            return None

    def get_continuation(self, prompt_text: str = "... ") -> str | None:
        """Read a continuation line (for multi-line input).

        No completer active — just basic line editing.

        Returns:
            Line string, or None on EOF/interrupt.
        """
        try:
            result = self._session.prompt(
                HTML(f"<prompt>{prompt_text}</prompt>"),
                completer=None,
            )
            return result
        except (KeyboardInterrupt, EOFError):
            return None
