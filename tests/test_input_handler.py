"""Tests for slash command completion behavior."""

from __future__ import annotations

import unittest

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from ui.input_handler import QInput, SlashCommandCompleter


class SlashCompletionTests(unittest.TestCase):
    def test_slash_root_lists_core_commands(self) -> None:
        completer = SlashCommandCompleter()
        completions = list(
            completer.get_completions(
                Document(text="/", cursor_position=1),
                CompleteEvent(completion_requested=True),
            )
        )
        items = {c.text for c in completions}
        self.assertIn("/settings", items)
        self.assertIn("/config", items)
        self.assertIn("/model", items)

    def test_non_slash_input_has_no_command_completions(self) -> None:
        completer = SlashCommandCompleter()
        completions = list(
            completer.get_completions(
                Document(text="hello", cursor_position=5),
                CompleteEvent(completion_requested=True),
            )
        )
        self.assertEqual(completions, [])

    def test_prefix_a_keeps_audit_completion(self) -> None:
        completer = SlashCommandCompleter()
        completions = list(
            completer.get_completions(
                Document(text="/a", cursor_position=2),
                CompleteEvent(completion_requested=True),
            )
        )
        items = {c.text for c in completions}
        self.assertIn("/audit", items)

    def test_should_show_slash_menu_helper(self) -> None:
        self.assertTrue(QInput._should_show_slash_completions("/"))
        self.assertTrue(QInput._should_show_slash_completions("/set"))
        self.assertFalse(QInput._should_show_slash_completions("/set value"))
        self.assertFalse(QInput._should_show_slash_completions("hello"))


if __name__ == "__main__":
    unittest.main()
