"""Tests for token/cost guardrails (per-turn and per-session)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from agent.orchestrator import SolveResult
from config import AgentConfig, AppConfig, ModelConfig
from ui.chat import ChatState, run_chat_turn
from utils.cost_tracker import CostTracker


class _DummyConsole:
    def print(self, *args, **kwargs) -> None:
        return None


class _DummyDisplay:
    def __init__(self) -> None:
        self.console = _DummyConsole()
        self.errors: list[str] = []

    def show_error(self, message: str) -> None:
        self.errors.append(message)

    def show_answer(self, answer: str, confidence: str) -> None:
        return None

    def show_done(self, steps: int, tokens: int, cost: float) -> None:
        return None


class _DummyCallbacks:
    def __init__(self) -> None:
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


class _GuardrailFakeOrchestrator:
    def __init__(self, **kwargs) -> None:
        self._cost = kwargs["cost_tracker"]

    def cancel(self) -> None:
        return None

    def chat_turn(self, _message: str) -> SolveResult:
        self._cost._total_cost += 0.10
        self._cost._total_prompt += 60
        self._cost._total_completion += 60
        return SolveResult(
            success=True,
            answer="ok",
            answer_confidence="high",
            iterations=1,
            category="misc",
            cost_usd=self._cost.total_cost,
            total_tokens=self._cost.total_tokens,
        )


class GuardrailTests(unittest.TestCase):
    @patch("ui.chat.signal.signal", lambda *_args, **_kwargs: None)
    @patch("ui.chat.signal.getsignal", lambda *_args, **_kwargs: None)
    @patch("ui.chat.PhaseSpinner", _DummySpinner)
    @patch("ui.chat.Orchestrator", _GuardrailFakeOrchestrator)
    def test_session_guardrail_blocks_turn_before_execution(self) -> None:
        cfg = AppConfig(
            model=ModelConfig(default_model="gpt-4o", api_key="test-key"),
            agent=AgentConfig(max_cost_per_session=0.10),
        )
        state = ChatState(
            config=cfg,
            current_model="gpt-4o",
            workspace=Path.cwd(),
            session_cost_tracker=CostTracker(budget_limit=100.0),
            total_session_cost=0.10,
        )
        display = _DummyDisplay()
        callbacks = _DummyCallbacks()

        result = run_chat_turn("hello", state, display, callbacks)

        self.assertIsNone(result)
        self.assertTrue(
            any("Session budget guardrail reached" in e for e in display.errors)
        )

    @patch("ui.chat.signal.signal", lambda *_args, **_kwargs: None)
    @patch("ui.chat.signal.getsignal", lambda *_args, **_kwargs: None)
    @patch("ui.chat.PhaseSpinner", _DummySpinner)
    @patch("ui.chat.Orchestrator", _GuardrailFakeOrchestrator)
    def test_turn_guardrail_warns_when_cost_exceeds_limit(self) -> None:
        cfg = AppConfig(
            model=ModelConfig(default_model="gpt-4o", api_key="test-key"),
            agent=AgentConfig(max_cost_per_turn=0.05, max_tokens_per_turn=100),
        )
        state = ChatState(
            config=cfg,
            current_model="gpt-4o",
            workspace=Path.cwd(),
            session_cost_tracker=CostTracker(budget_limit=100.0),
        )
        display = _DummyDisplay()
        callbacks = _DummyCallbacks()

        run_chat_turn("hello", state, display, callbacks)

        self.assertTrue(any("Turn guardrail exceeded" in e for e in display.errors))
        self.assertTrue(
            any("Turn token guardrail exceeded" in e for e in display.errors)
        )


if __name__ == "__main__":
    unittest.main()
