"""Team-aware callbacks that forward agent events to the team infrastructure."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.orchestrator import AgentCallbacks
from agent.team.messages import MessageBus
from agent.team.taskboard import TaskBoard
from utils.logger import get_logger

if TYPE_CHECKING:
    pass

_log = get_logger()


class TeamCallbacks(AgentCallbacks):
    """Callbacks for a teammate agent.

    Forwards important events (flags, answers, discoveries) to the
    MessageBus so the team leader can react. Minimal logging for
    non-critical events.
    """

    def __init__(
        self,
        name: str,
        msgbus: MessageBus,
        taskboard: TaskBoard,
        verbose: bool = False,
    ) -> None:
        self._name = name
        self._msgbus = msgbus
        self._taskboard = taskboard
        self._verbose = verbose

    # ── Critical events → forward to lead ──────────────────────────

    def on_flag_found(self, flag: str) -> None:
        self._msgbus.send(self._name, "lead", flag, "flag")
        self._msgbus.broadcast(self._name, f"FLAG: {flag}", "flag")

    def on_answer(self, answer: str, confidence: str, flag: str | None) -> None:
        content = f"Answer ({confidence}): {answer}"
        if flag:
            content += f" | Flag: {flag}"
        self._msgbus.send(self._name, "lead", content, "discovery")

    def on_error(self, message: str) -> None:
        self._msgbus.send(self._name, "lead", f"Error: {message}", "info")

    # ── Tool events → forward discoveries ──────────────────────────

    def on_tool_result(self, tool_name: str, output: str, success: bool) -> None:
        if not success:
            return
        # Forward significant findings to lead
        if tool_name in ("recon", "shell", "network", "browser", "code_analyzer"):
            if len(output) > 50:
                self._msgbus.send(
                    self._name, "lead",
                    f"[{tool_name}] {output[:2000]}",
                    "discovery",
                )

    # ── Informational events → log only ────────────────────────────

    def on_thinking(self, text: str) -> None:
        if self._verbose:
            _log.debug(f"[{self._name}] thinking: {text[:200]}")

    def on_tool_call(self, tool_name: str, args: dict) -> None:
        _log.debug(f"[{self._name}] tool: {tool_name}")

    def on_status(
        self, step: int, max_steps: int, tokens: int, cost: float, model: str
    ) -> None:
        _log.debug(f"[{self._name}] step {step}/{max_steps} ${cost:.4f}")

    def on_phase(self, phase: str, detail: str) -> None:
        self._msgbus.send(self._name, "lead", f"{phase}: {detail}", "info")

    def on_pivot(self, level_name: str, pivot_count: int) -> None:
        self._msgbus.send(
            self._name, "lead",
            f"Pivot #{pivot_count}: {level_name}",
            "info",
        )

    def on_model_change(self, old_model: str, new_model: str) -> None:
        pass

    def on_context_summary(self) -> None:
        pass

    def on_budget_warning(self, warning: str) -> None:
        self._msgbus.send(self._name, "lead", warning, "info")

    def on_iteration(self, current: int, total: int) -> None:
        pass

    def on_thinking_delta(self, delta: str) -> None:
        pass

    def on_ask_user(self, prompt: str) -> str:
        # Teammates can't ask the user — return empty hint
        return ""
