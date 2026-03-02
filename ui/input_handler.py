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
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style

# ------------------------------------------------------------------
# Slash command completer
# ------------------------------------------------------------------


class SlashCommandCompleter(Completer):
    """Show command suggestions when user types /."""

    def __init__(self) -> None:
        self._commands: dict[str, str] = self._load_commands()

    def _load_commands(self) -> dict[str, str]:
        try:
            from ui.commands import COMMAND_HELP

            result = {}
            for key, desc in COMMAND_HELP.items():
                for part in key.replace(",", " ").split():
                    if part.startswith("/") and part not in result:
                        result[part] = desc
            return result
        except Exception:
            return {}

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        if not text.lstrip().startswith("/"):
            return

        word = text.lstrip()

        # Don't complete if user is already typing arguments
        if " " in word:
            return

        for cmd, desc in sorted(self._commands.items()):
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

Q_STYLE = Style.from_dict(
    {
        # Minimal dark style inspired by Claude Code's slash list.
        "prompt": "#8bd5ca bold",
        "completion-menu": "bg:#000000 #d1d5db",
        "completion-menu.completion": "bg:#000000 #d1d5db",
        "completion-menu.completion.current": "bg:#111827 #f3f4f6",
        "completion-menu.meta.completion": "bg:#000000 #6b7280",
        "completion-menu.meta.completion.current": "bg:#111827 #9ca3af",
        "scrollbar.background": "bg:#000000",
        "scrollbar.button": "bg:#374151",
    }
)


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
        key_bindings = self._build_key_bindings()

        self._session: PromptSession = PromptSession(
            completer=SlashCommandCompleter(),
            history=FileHistory(history_path),
            style=Q_STYLE,
            key_bindings=key_bindings,
            complete_while_typing=False,
            complete_in_thread=False,
            complete_style=CompleteStyle.COLUMN,
            enable_history_search=True,
            reserve_space_for_menu=12,
        )
        # Keep slash-command suggestions alive while typing (/a, /se, ...).
        self._session.default_buffer.on_text_changed += self._on_text_changed

    @staticmethod
    def _should_show_slash_completions(text_before_cursor: str) -> bool:
        token = text_before_cursor.lstrip()
        return token.startswith("/") and " " not in token

    @staticmethod
    def _build_key_bindings() -> KeyBindings:
        """Create key bindings to force slash-command suggestions open quickly."""
        kb = KeyBindings()

        @kb.add("/")
        def _slash(event) -> None:  # type: ignore[no-untyped-def]
            buf = event.app.current_buffer
            buf.insert_text("/")
            # If user is typing a slash command token, pop completion menu now.
            token = buf.document.text_before_cursor.lstrip()
            if token.startswith("/") and " " not in token:
                buf.start_completion(
                    select_first=False,
                    complete_event=CompleteEvent(completion_requested=True),
                )

        @kb.add("c-space")
        def _manual_complete(event) -> None:  # type: ignore[no-untyped-def]
            buf = event.app.current_buffer
            token = buf.document.text_before_cursor.lstrip()
            if token.startswith("/") and " " not in token:
                buf.start_completion(
                    select_first=False,
                    complete_event=CompleteEvent(completion_requested=True),
                )

        return kb

    def _on_text_changed(self, buffer) -> None:  # type: ignore[no-untyped-def]
        """Refresh slash-command menu on every text change."""
        if self._should_show_slash_completions(buffer.document.text_before_cursor):
            buffer.start_completion(
                select_first=False,
                complete_event=CompleteEvent(completion_requested=True),
            )

    def get_input(self, prompt_text: str = "> ") -> str | None:
        """Read one line of input with full line-editing support.

        Returns:
            User input string (stripped).
            CTRL_C sentinel on Ctrl+C.
            None on Ctrl+D (EOF).
        """
        try:
            result = self._session.prompt(HTML(f"<prompt>{prompt_text}</prompt>"))
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
