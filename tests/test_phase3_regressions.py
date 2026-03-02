"""Regression tests for Phase 3 stability/quality fixes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.classifier import Category
from agent.orchestrator import SolveResult
from config import AppConfig, ModelConfig
from config_yaml.loader import QConfig, apply_yaml_to_appconfig
from tools.file_manager import FileManagerTool
from ui.chat import ChatState, _run_team_solve, run_chat_turn
from ui.commands import _cmd_model
from utils.cost_tracker import CostTracker


class _DummyConsole:
    def print(self, *args, **kwargs) -> None:
        return None


class _DummyDisplay:
    def __init__(self) -> None:
        self.console = _DummyConsole()
        self.errors: list[str] = []
        self.done: list[dict] = []
        self.model_changes: list[tuple[str, str]] = []

    def show_error(self, message: str) -> None:
        self.errors.append(message)

    def show_info(self, message: str) -> None:
        return None

    def show_answer(self, answer: str, confidence: str) -> None:
        return None

    def show_done(self, steps: int, tokens: int, cost: float) -> None:
        self.done.append({"steps": steps, "tokens": tokens, "cost": cost})

    def show_flag_result(self, **kwargs) -> None:
        return None

    def show_fail_result(self, **kwargs) -> None:
        return None

    def show_model_change(self, old_model: str, new_model: str) -> None:
        self.model_changes.append((old_model, new_model))


class _DummyCallbacks:
    def __init__(self) -> None:
        self._found_flag = None
        self._found_answer = ""
        self._answer_confidence = "medium"

    def reset_for_new_solve(self) -> None:
        return None

    def set_spinner(self, _spinner) -> None:
        return None


class _DummySpinner:
    def __init__(self, *_args, **_kwargs) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def set_phase(self, *_args, **_kwargs) -> None:
        return None

    def reset(self) -> None:
        return None


class _FakeOrchestrator:
    def __init__(self, **kwargs) -> None:
        self._cb = kwargs.get("callbacks")
        self._cost = kwargs["cost_tracker"]
        self._turn_calls = 0

    def cancel(self) -> None:
        return None

    def chat_turn(self, _message: str) -> SolveResult:
        self._turn_calls += 1
        self._cost._total_cost += 0.10
        self._cost._total_prompt += 100
        return SolveResult(
            success=True,
            answer="ok",
            answer_confidence="high",
            iterations=1,
            category="misc",
            cost_usd=self._cost.total_cost,
            total_tokens=self._cost.total_tokens,
        )


class _FakeTeamLeader:
    last_category: str | None = None

    def __init__(self, **_kwargs) -> None:
        return None

    def cancel(self) -> None:
        return None

    def solve_with_team(self, **kwargs) -> SolveResult:
        _FakeTeamLeader.last_category = kwargs.get("category")
        return SolveResult(
            success=True,
            answer="done",
            iterations=1,
            category=str(kwargs.get("category", "misc")),
            summary="team complete",
            cost_usd=0.05,
            total_tokens=120,
        )


class Phase3RegressionTests(unittest.TestCase):
    def test_yaml_overlay_preserves_model_and_app_fields(self) -> None:
        base = AppConfig(
            model=ModelConfig(
                default_model="gpt-4o",
                api_key="openai-key",
                anthropic_api_key="anthropic-key",
                google_api_key="google-key",
                fallback_model="old-fallback",
                brave_api_key="brave-key",
            ),
            plan_mode=True,
        )
        qcfg = QConfig(
            model="gpt-4o-mini",
            fallback_model="claude-sonnet-4-5",
            max_steps=7,
            max_cost_per_challenge=1.25,
            session_dir="sessions_override",
        )

        merged = apply_yaml_to_appconfig(qcfg, base)

        self.assertEqual(merged.model.default_model, "gpt-4o-mini")
        self.assertEqual(merged.model.fallback_model, "claude-sonnet-4-5")
        self.assertEqual(merged.model.anthropic_api_key, "anthropic-key")
        self.assertEqual(merged.model.google_api_key, "google-key")
        self.assertTrue(merged.plan_mode)
        self.assertEqual(merged.agent.max_iterations, 7)

    def test_file_manager_blocks_prefix_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "work"
            sibling = root / "work2"
            workspace.mkdir()
            sibling.mkdir()

            fm = FileManagerTool(workspace=workspace)
            with self.assertRaises(ValueError):
                fm._resolve("../work2/secret.txt")

    @patch("ui.chat.signal.signal", lambda *_args, **_kwargs: None)
    @patch("ui.chat.signal.getsignal", lambda *_args, **_kwargs: None)
    @patch("ui.chat.PhaseSpinner", _DummySpinner)
    @patch("agent.providers.create_provider", lambda _cfg: object())
    @patch("agent.classifier.classify_challenge", lambda **_kwargs: Category.FORENSICS)
    @patch("agent.team.leader.TeamLeader", _FakeTeamLeader)
    def test_team_mode_uses_classified_category_value(self) -> None:
        state = ChatState(
            config=AppConfig(
                model=ModelConfig(default_model="gpt-4o", api_key="test-key")
            ),
            current_model="gpt-4o",
            workspace=Path.cwd(),
        )
        display = _DummyDisplay()
        callbacks = _DummyCallbacks()

        result = _run_team_solve(
            "Analyze this pcap challenge", state, display, callbacks
        )

        self.assertIsNotNone(result)
        self.assertEqual(_FakeTeamLeader.last_category, "forensics")

    @patch("ui.chat.signal.signal", lambda *_args, **_kwargs: None)
    @patch("ui.chat.signal.getsignal", lambda *_args, **_kwargs: None)
    @patch("ui.chat.PhaseSpinner", _DummySpinner)
    @patch("ui.chat.Orchestrator", _FakeOrchestrator)
    def test_chat_turn_cost_is_not_double_counted(self) -> None:
        state = ChatState(
            config=AppConfig(
                model=ModelConfig(default_model="gpt-4o", api_key="test-key")
            ),
            current_model="gpt-4o",
            workspace=Path.cwd(),
            session_cost_tracker=CostTracker(budget_limit=100.0),
        )
        display = _DummyDisplay()
        callbacks = _DummyCallbacks()

        run_chat_turn("first", state, display, callbacks)
        run_chat_turn("second", state, display, callbacks)

        self.assertAlmostEqual(state.total_session_cost, 0.20, places=6)
        self.assertEqual(len(display.done), 2)
        self.assertAlmostEqual(display.done[0]["cost"], 0.10, places=6)
        self.assertAlmostEqual(display.done[1]["cost"], 0.10, places=6)

    @patch("agent.providers.create_provider")
    def test_model_command_syncs_persistent_chat_orchestrator(
        self, mock_create_provider
    ) -> None:
        provider = object()
        mock_create_provider.return_value = provider

        state = ChatState(
            config=AppConfig(
                model=ModelConfig(default_model="gpt-4o", api_key="test-key")
            ),
            current_model="gpt-4o",
            workspace=Path.cwd(),
        )
        fake_context = SimpleNamespace(_client=None, _config=None, _model="gpt-4o")
        fake_orch = SimpleNamespace(
            _config=state.config,
            _provider=None,
            _current_model="gpt-4o",
            _context=fake_context,
        )
        state._chat_orchestrator = fake_orch
        display = _DummyDisplay()

        _cmd_model("gpt-4o-mini", state, display)

        self.assertEqual(state.current_model, "gpt-4o-mini")
        self.assertEqual(fake_orch._current_model, "gpt-4o-mini")
        self.assertIs(fake_orch._provider, provider)
        self.assertEqual(fake_orch._context._model, "gpt-4o-mini")
        self.assertEqual(display.model_changes[-1], ("gpt-4o", "gpt-4o-mini"))


if __name__ == "__main__":
    unittest.main()
