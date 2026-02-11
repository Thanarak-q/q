"""Base agent class for the multi-agent pipeline.

Extracts the common ReAct loop pattern from Orchestrator into a
reusable base that specialized agents (recon, analyst, solver,
reporter) inherit from.  Each agent runs a constrained loop with
its own system prompt, tool subset, and step budget.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from openai import APIError, OpenAI, RateLimitError

from agent.orchestrator import AgentCallbacks, NullCallbacks
from config import AppConfig
from tools.registry import ToolRegistry
from utils.cost_tracker import CostTracker
from utils.flag_extractor import extract_flags
from utils.logger import get_logger


# ------------------------------------------------------------------
# Result type
# ------------------------------------------------------------------


@dataclass
class AgentResult:
    """Result of a single agent's execution."""

    success: bool
    deliverable: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    iterations: int = 0
    cost_usd: float = 0.0
    total_tokens: int = 0
    summary: str = ""


# ------------------------------------------------------------------
# Base agent
# ------------------------------------------------------------------


class BaseAgent(ABC):
    """Abstract base for all pipeline agents.

    Subclasses define their role, system prompt, allowed tools, and
    step budget.  The ``run()`` method executes a simplified ReAct loop
    that terminates when the agent calls ``submit_deliverable``.
    """

    def __init__(
        self,
        config: AppConfig,
        client: OpenAI | None = None,
        docker_manager: Optional[Any] = None,
        workspace: Path | None = None,
        callbacks: AgentCallbacks | None = None,
        cost_tracker: CostTracker | None = None,
        flag_pattern: str | None = None,
    ) -> None:
        self._config = config
        self._client = client or OpenAI(api_key=config.model.api_key)
        self._workspace = workspace or Path.cwd()
        self._docker = docker_manager
        self._cb: AgentCallbacks = callbacks or NullCallbacks()
        self._cost = cost_tracker or CostTracker(
            budget_limit=config.agent.max_cost_per_challenge,
        )
        self._flag_pattern = flag_pattern
        self._log = get_logger()

        # Per-run state (reset in run())
        self._messages: list[dict[str, Any]] = []
        self._iteration = 0
        self._found_flags: list[str] = []
        self._cancelled = False

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def role(self) -> str:
        """Agent role identifier (e.g. 'recon', 'analyst', 'solver')."""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """Model to use for this agent."""
        ...

    @abstractmethod
    def get_allowed_tools(self) -> list[str]:
        """Tool names this agent is allowed to use."""
        ...

    @abstractmethod
    def get_max_steps(self) -> int:
        """Maximum ReAct loop iterations for this agent."""
        ...

    @abstractmethod
    def build_system_prompt(self, context: dict[str, Any]) -> str:
        """Build the system prompt for this agent given pipeline context."""
        ...

    @abstractmethod
    def build_initial_message(self, context: dict[str, Any]) -> str:
        """Build the initial user message from pipeline context."""
        ...

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Cancel the running agent loop."""
        self._cancelled = True

    def run(self, context: dict[str, Any]) -> AgentResult:
        """Execute this agent's ReAct loop.

        Args:
            context: Pipeline context dict with keys like description,
                     files, target_url, category, recon_deliverable,
                     analyst_deliverable, hypothesis, etc.

        Returns:
            AgentResult with the deliverable and metadata.
        """
        self._messages = []
        self._iteration = 0
        self._found_flags = []
        self._cancelled = False

        # Build filtered tool registry
        registry = ToolRegistry.from_subset(
            self.get_allowed_tools(),
            docker_manager=self._docker,
            workspace=self._workspace,
        )

        # Set up messages
        system_prompt = self.build_system_prompt(context)
        self._messages.append({"role": "system", "content": system_prompt})

        initial_msg = self.build_initial_message(context)
        self._messages.append({"role": "user", "content": initial_msg})

        # Notify callback
        self._cb.on_agent_start(self.role, self.model)

        # Run the loop
        result = self._react_loop(registry)

        # Notify callback
        self._cb.on_agent_done(self.role, result.summary, result.success)

        return result

    # ------------------------------------------------------------------
    # ReAct loop — simplified from Orchestrator._react_loop
    # ------------------------------------------------------------------

    def _react_loop(self, registry: ToolRegistry) -> AgentResult:
        """Execute the ReAct loop until deliverable or max steps."""
        max_steps = self.get_max_steps()
        tools_defs = registry.openai_definitions()

        while self._iteration < max_steps:
            if self._cancelled:
                break

            self._iteration += 1

            # Budget check
            if self._cost.is_over_budget():
                self._cb.on_error(f"[{self.role}] Budget limit reached.")
                break

            # Call LLM
            response_msg = self._call_llm(tools_defs)
            if response_msg is None:
                continue

            self._messages.append(response_msg)

            # Process text content
            text_content = response_msg.get("content", "") or ""
            if text_content:
                self._cb.on_thinking(text_content)

                # Check for flags in reasoning
                flags = extract_flags(text_content, self._flag_pattern)
                if flags:
                    self._found_flags.extend(flags)
                    for f in flags:
                        self._cb.on_flag_found(f)

            # Process tool calls
            tool_calls = response_msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    if self._cancelled:
                        break

                    func = tc.get("function", {})
                    func_name = func.get("name", "")

                    # Intercept submit_deliverable
                    if func_name == "submit_deliverable":
                        return self._handle_submit_deliverable(tc)

                    # Intercept answer_user (solver agent)
                    if func_name == "answer_user":
                        return self._handle_answer_user(tc, registry)

                    # Execute normal tool call
                    self._execute_tool_call(tc, registry)

            elif not text_content:
                self._log.warning(f"[{self.role}] Empty LLM response")

        # Exhausted steps — return partial result
        return AgentResult(
            success=False,
            iterations=self._iteration,
            flags=self._found_flags,
            summary=f"{self.role} exhausted {max_steps} steps without submitting deliverable.",
        )

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    def _call_llm(
        self, tools: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Make an API call with retry logic."""
        for attempt in range(3):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    temperature=self._config.model.temperature,
                    max_tokens=self._config.model.max_tokens,
                    messages=self._messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None,
                )
                msg = response.choices[0].message

                # Track cost
                if response.usage:
                    self._cost.record(
                        model=self.model,
                        usage=response.usage,
                        iteration=self._iteration,
                    )

                # Convert to dict
                msg_dict: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content,
                }
                if msg.tool_calls:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                return msg_dict

            except RateLimitError:
                wait = 2 ** (attempt + 1)
                self._log.warning(
                    f"[{self.role}] Rate limited, waiting {wait}s..."
                )
                time.sleep(wait)
            except APIError as exc:
                self._log.error(
                    f"[{self.role}] API error (attempt {attempt + 1}/3): {exc}"
                )
                if attempt == 2:
                    self._cb.on_error(
                        f"[{self.role}] API error after 3 retries: {exc}"
                    )
                    return None
                time.sleep(2**attempt)

        return None

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        registry: ToolRegistry,
    ) -> list[str]:
        """Execute a tool call and add the result to messages."""
        func = tool_call["function"]
        name = func["name"]
        tc_id = tool_call["id"]

        try:
            args = json.loads(func["arguments"])
        except json.JSONDecodeError:
            error_msg = f"Invalid JSON arguments: {func['arguments']}"
            self._cb.on_error(error_msg)
            self._messages.append(
                {"role": "tool", "tool_call_id": tc_id, "content": error_msg}
            )
            return []

        self._cb.on_tool_call(name, args)

        result = registry.execute(name, args)
        output = result.output if result.success else f"[ERROR] {result.error}"

        self._cb.on_tool_result(name, output, result.success)

        self._messages.append(
            {"role": "tool", "tool_call_id": tc_id, "content": output}
        )

        # Check for flags
        flags = extract_flags(output, self._flag_pattern)
        if flags:
            self._found_flags.extend(flags)
            for f in flags:
                self._cb.on_flag_found(f)

        return flags

    # ------------------------------------------------------------------
    # Deliverable handling
    # ------------------------------------------------------------------

    def _handle_submit_deliverable(
        self, tool_call: dict[str, Any]
    ) -> AgentResult:
        """Handle the submit_deliverable tool call."""
        func = tool_call["function"]
        tc_id = tool_call["id"]

        try:
            args = json.loads(func["arguments"])
        except json.JSONDecodeError:
            args = {"deliverable": "{}", "summary": "parse error"}

        raw_deliverable = args.get("deliverable", "{}")
        summary = args.get("summary", "")

        # Parse the deliverable JSON
        try:
            if isinstance(raw_deliverable, str):
                deliverable = json.loads(raw_deliverable)
            else:
                deliverable = raw_deliverable
        except json.JSONDecodeError:
            deliverable = {"raw": raw_deliverable}

        # Add tool response to messages (for completeness)
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": f"Deliverable accepted: {summary}",
            }
        )

        return AgentResult(
            success=True,
            deliverable=deliverable,
            flags=self._found_flags,
            iterations=self._iteration,
            summary=summary,
        )

    def _handle_answer_user(
        self,
        tool_call: dict[str, Any],
        registry: ToolRegistry,
    ) -> AgentResult:
        """Handle answer_user (used by solver agent)."""
        func = tool_call["function"]
        tc_id = tool_call["id"]

        try:
            args = json.loads(func["arguments"])
        except json.JSONDecodeError:
            args = {"answer": func.get("arguments", ""), "confidence": "low"}

        answer = args.get("answer", "")
        confidence = args.get("confidence", "medium")
        flag = args.get("flag", "") or ""

        # Execute for logging
        result = registry.execute("answer_user", args)
        self._messages.append(
            {"role": "tool", "tool_call_id": tc_id, "content": result.output}
        )

        if flag and flag not in self._found_flags:
            self._found_flags.append(flag)
            self._cb.on_flag_found(flag)

        self._cb.on_answer(answer, confidence, flag if flag else None)

        return AgentResult(
            success=True,
            deliverable={
                "answer": answer,
                "confidence": confidence,
                "flag": flag,
                "method": "direct_solve",
            },
            flags=self._found_flags,
            iterations=self._iteration,
            summary=answer,
        )
