"""Main ReAct agent loop (orchestrator).

Coordinates the classify -> plan -> solve loop, dispatching tool calls
and managing the agent's state until a flag is found or limits are hit.

Integrates: multi-model selection, graduated pivot system, cost tracking,
session persistence, and optional Rich live dashboard.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from openai import APIError, OpenAI, RateLimitError

from agent.classifier import Category, classify_challenge, get_playbook
from agent.context_manager import ContextManager
from agent.planner import (
    PivotLevel,
    PivotManager,
    create_plan,
    select_model_for_task,
)
from config import AppConfig, load_config
from prompts.strategies import FINAL_ATTEMPT_PROMPT
from prompts.system import build_system_prompt
from tools.registry import ToolRegistry
from utils.cost_tracker import CostTracker
from utils.dashboard import Dashboard
from utils.flag_extractor import extract_flags
from utils.logger import console, get_logger
from utils.session_manager import SessionManager, StepRecord


@dataclass
class SolveResult:
    """Result of a solve attempt."""

    success: bool
    flags: list[str] = field(default_factory=list)
    iterations: int = 0
    category: str = "unknown"
    summary: str = ""
    session_id: str = ""
    cost_usd: float = 0.0
    total_tokens: int = 0


class Orchestrator:
    """The main ReAct agent that solves CTF challenges.

    Implements the observe-think-act loop with automatic tool dispatch,
    context management, graduated strategy pivoting, multi-model
    selection, cost tracking, session persistence, and an optional
    Rich live dashboard.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        docker_manager: Optional[Any] = None,
        workspace: Path | None = None,
        session_manager: SessionManager | None = None,
        dashboard: Dashboard | None = None,
        enable_dashboard: bool = False,
    ) -> None:
        """Initialise the orchestrator.

        Args:
            config: Application configuration (loaded from env if None).
            docker_manager: Optional Docker sandbox manager.
            workspace: Workspace directory for file operations.
            session_manager: Optional session persistence manager.
            dashboard: Optional pre-built dashboard instance.
            enable_dashboard: If True and no dashboard given, create one.
        """
        self._config = config or load_config()
        self._client = OpenAI(api_key=self._config.model.api_key)
        self._workspace = workspace or Path.cwd()
        self._registry = ToolRegistry(
            docker_manager=docker_manager,
            workspace=self._workspace,
        )
        self._context = ContextManager(self._client, self._config)
        self._log = get_logger()
        self._iteration = 0
        self._found_flags: list[str] = []
        self._custom_flag_pattern: str | None = None

        # --- Advanced features ---
        self._pivot = PivotManager(
            stall_threshold=self._config.agent.stall_threshold,
        )
        self._cost = CostTracker(
            budget_limit=self._config.agent.max_cost_per_challenge,
        )
        self._session = session_manager or SessionManager(
            session_dir=self._config.log.session_dir,
        )
        self._current_model: str = self._config.model.default_model

        # Dashboard
        if dashboard is not None:
            self._dashboard: Dashboard | None = dashboard
        elif enable_dashboard:
            self._dashboard = Dashboard()
        else:
            self._dashboard = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(
        self,
        description: str,
        files: list[Path] | None = None,
        target_url: str | None = None,
        flag_pattern: str | None = None,
    ) -> SolveResult:
        """Solve a CTF challenge.

        This is the main entry point.  It classifies the challenge,
        creates a plan, then enters the ReAct loop.

        Args:
            description: Challenge description text.
            files: Optional list of challenge file paths.
            target_url: Optional target service URL.
            flag_pattern: Optional custom flag regex pattern.

        Returns:
            SolveResult with success status and found flags.
        """
        self._custom_flag_pattern = flag_pattern

        # Create session
        sid = self._session.new_session(
            description=description,
            target_url=target_url or "",
            files=[str(f) for f in files] if files else [],
            flag_pattern=flag_pattern or "",
        )

        # Start dashboard
        if self._dashboard:
            self._dashboard.start()

        try:
            result = self._run_pipeline(
                description, files, target_url, flag_pattern
            )
        except KeyboardInterrupt:
            console.print("\n[error]Interrupted by user.[/error]")
            self._session.update(status="paused")
            self._session.save()
            result = SolveResult(
                success=False,
                flags=self._found_flags,
                iterations=self._iteration,
                summary="Interrupted by user.",
                session_id=sid,
            )
        finally:
            if self._dashboard:
                self._dashboard.stop()

        # Finalise session
        result.session_id = sid
        result.cost_usd = self._cost.total_cost
        result.total_tokens = self._cost.total_tokens
        self._session.update(
            status="solved" if result.success else "failed",
            flags=result.flags,
            cost=self._cost.to_dict(),
            model_used=self._current_model,
        )
        self._session.save()
        return result

    def resume(
        self,
        session_id: str,
        flag_pattern: str | None = None,
    ) -> SolveResult:
        """Resume a previously-paused session.

        Args:
            session_id: The session ID to resume.
            flag_pattern: Optional custom flag regex.

        Returns:
            SolveResult from continued solving.
        """
        data = self._session.load(session_id)
        if data is None:
            console.print(f"[error]Session {session_id} not found.[/error]")
            return SolveResult(success=False, summary="Session not found.")

        self._custom_flag_pattern = flag_pattern or data.flag_pattern or None
        self._iteration = data.current_iteration
        self._found_flags = list(data.flags)

        # Restore messages
        self._context._messages = list(data.messages)  # noqa: SLF001

        # Determine category
        category = Category.MISC
        for cat in Category:
            if cat.value == data.category:
                category = cat
                break

        console.print(
            f"[info]Resuming session {session_id} "
            f"at iteration {self._iteration}[/info]"
        )

        self._session.update(status="in_progress")
        result = self._react_loop(category)
        result.session_id = session_id
        result.cost_usd = self._cost.total_cost
        result.total_tokens = self._cost.total_tokens

        self._session.update(
            status="solved" if result.success else "failed",
            flags=result.flags,
            cost=self._cost.to_dict(),
            model_used=self._current_model,
        )
        self._session.save()
        return result

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        description: str,
        files: list[Path] | None,
        target_url: str | None,
        flag_pattern: str | None,
    ) -> SolveResult:
        """Run the full classify -> plan -> solve pipeline.

        Args:
            description: Challenge description.
            files: Challenge files.
            target_url: Target URL.
            flag_pattern: Custom flag regex.

        Returns:
            SolveResult from the ReAct loop.
        """
        # --- Phase 1: Reconnaissance ---
        console.print(
            "\n[step]Step 1:[/step] Classifying challenge...", style="bold"
        )
        file_info = self._gather_file_info(files)
        category = classify_challenge(
            description, file_info, self._client, self._config
        )
        console.print(f"  Category: [thinking]{category.value}[/thinking]")
        self._session.update(category=category.value)

        # --- Phase 2: Planning ---
        console.print(
            "\n[step]Step 2:[/step] Creating attack plan...", style="bold"
        )
        playbook = get_playbook(category)
        plan = create_plan(
            description, category, file_info, self._client, self._config
        )
        console.print(f"[thinking]{plan}[/thinking]")
        self._session.update(plan=plan)

        # Select initial model
        self._current_model = select_model_for_task(
            category, self._config, is_escalated=False
        )
        self._log.info(f"Initial model: {self._current_model}")

        # --- Phase 3: Setup context ---
        system_prompt = build_system_prompt(
            category_playbook=playbook,
            extra_context=self._build_extra_context(target_url, file_info),
        )
        self._context.set_system_prompt(system_prompt)

        initial_message = f"Challenge description:\n{description}"
        if target_url:
            initial_message += f"\n\nTarget URL: {target_url}"
        if file_info:
            initial_message += f"\n\nFiles:\n{file_info}"
        initial_message += f"\n\nAttack plan:\n{plan}"
        initial_message += (
            "\n\nBegin solving. Start with step 1 of the plan. "
            "Think step by step, use tools, and find the flag."
        )
        self._context.add_user_message(initial_message)

        # Dashboard update
        if self._dashboard:
            self._dashboard.set_challenge(description, category.value)

        # Save initial messages for resume support
        self._session.update(messages=self._context.messages)

        # --- Phase 4: ReAct loop ---
        console.print(
            f"\n[step]Step 3:[/step] Entering solve loop "
            f"(max {self._config.agent.max_iterations} iterations)...",
            style="bold",
        )
        return self._react_loop(category)

    def _react_loop(self, category: Category) -> SolveResult:
        """Execute the main ReAct (Reason-Act-Observe) loop.

        Args:
            category: The classified challenge category.

        Returns:
            SolveResult after the loop terminates.
        """
        max_iter = self._config.agent.max_iterations

        while self._iteration < max_iter:
            self._iteration += 1
            console.rule(
                f"[step]Iteration {self._iteration}/{max_iter}[/step]"
            )

            # --- Budget check ---
            warning = self._cost.budget_warning()
            if warning:
                console.print(f"[info]{warning}[/info]")
            if self._cost.is_over_budget():
                console.print(
                    "[error]Budget limit reached. Stopping.[/error]"
                )
                break

            # --- Context window check ---
            if self._context.needs_summarization():
                console.print("[info]Summarizing context...[/info]")
                self._context.summarize_history()
                self._session.add_step(StepRecord(
                    iteration=self._iteration,
                    timestamp=time.time(),
                    event="summary",
                    content="Context summarized.",
                ))

            # --- Graduated pivot check ---
            pivot_level = self._pivot.check_stall(self._iteration)
            if pivot_level != PivotLevel.NONE:
                self._handle_pivot(pivot_level)

            # --- Final attempt prompt ---
            if self._iteration == max_iter - 3:
                self._context.add_user_message(FINAL_ATTEMPT_PROMPT)

            # --- Call LLM ---
            response_message = self._call_llm()
            if response_message is None:
                continue

            self._context.add_assistant_message(response_message)

            # --- Process text content ---
            text_content = response_message.get("content", "") or ""
            if text_content:
                console.print(f"[thinking]{text_content}[/thinking]")
                if self._dashboard:
                    self._dashboard.set_thinking(text_content)

                self._session.add_step(StepRecord(
                    iteration=self._iteration,
                    timestamp=time.time(),
                    event="llm_response",
                    model=self._current_model,
                    content=text_content,
                ))

                flags = extract_flags(text_content, self._custom_flag_pattern)
                if flags:
                    return self._flag_found(flags, category, text_content)

            # --- Process tool calls ---
            tool_calls = response_message.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    flags = self._execute_tool_call(tc)
                    if flags:
                        return self._flag_found(flags, category)
            elif not text_content:
                self._log.warning("Empty response from LLM")

            # --- Dashboard progress ---
            if self._dashboard:
                self._dashboard.set_progress(
                    iteration=self._iteration,
                    max_iterations=max_iter,
                    tokens=self._cost.total_tokens,
                    cost=self._cost.total_cost,
                    model=self._current_model,
                )

            # --- Persist messages for resume ---
            self._session.update(messages=self._context.messages)
            self._session.save()

        # Exhausted iterations
        console.print(
            "\n[error]Max iterations reached without finding flag.[/error]"
        )
        return SolveResult(
            success=False,
            flags=self._found_flags,
            iterations=self._iteration,
            category=category.value,
            summary="Exhausted maximum iterations without finding the flag.",
        )

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    def _call_llm(self) -> dict[str, Any] | None:
        """Make an API call to the LLM with retry logic.

        Returns:
            The assistant message dict, or None on failure.
        """
        model = self._current_model
        tools = self._registry.openai_definitions()

        for attempt in range(3):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    temperature=self._config.model.temperature,
                    max_tokens=self._config.model.max_tokens,
                    messages=self._context.messages,
                    tools=tools,
                    tool_choice="auto",
                )
                msg = response.choices[0].message

                # Track cost
                if response.usage:
                    self._cost.record(
                        model=model,
                        usage=response.usage,
                        iteration=self._iteration,
                    )

                # Convert to dict for storage
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
                self._log.warning(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
            except APIError as exc:
                self._log.error(
                    f"API error (attempt {attempt + 1}/3): {exc}"
                )
                if attempt == 2:
                    return None
                time.sleep(2**attempt)

        return None

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool_call(self, tool_call: dict[str, Any]) -> list[str]:
        """Execute a single tool call and add the result to context.

        Args:
            tool_call: Tool call dict with id, function name, and arguments.

        Returns:
            List of flags found in the tool output (empty if none).
        """
        func = tool_call["function"]
        name = func["name"]
        tc_id = tool_call["id"]

        try:
            args = json.loads(func["arguments"])
        except json.JSONDecodeError:
            error_msg = f"Invalid JSON arguments: {func['arguments']}"
            console.print(f"[error]{error_msg}[/error]")
            self._context.add_tool_result(tc_id, error_msg)
            return []

        console.print(
            f"[tool_call]Tool: {name}[/tool_call]  "
            f"args={json.dumps(args, ensure_ascii=False)[:200]}"
        )

        result = self._registry.execute(name, args)

        if result.success:
            console.print(f"[result]{result.output[:500]}[/result]")
            self._pivot.record_progress(self._iteration)
        else:
            console.print(f"[error]{result.error}[/error]")

        output = result.output if result.success else f"[ERROR] {result.error}"
        self._context.add_tool_result(tc_id, output)

        # Dashboard update
        if self._dashboard:
            self._dashboard.set_tool_output(name, output)

        # Session step
        self._session.add_step(StepRecord(
            iteration=self._iteration,
            timestamp=time.time(),
            event="tool_call",
            model=self._current_model,
            tool_name=name,
            tool_args=args,
            tool_output=output[:2000],
        ))

        # Check for flags in tool output
        flags = extract_flags(output, self._custom_flag_pattern)
        if flags:
            self._found_flags.extend(flags)
            console.print(
                f"\n[flag]FLAG FOUND: {', '.join(flags)}[/flag]"
            )
            if self._dashboard:
                for f in flags:
                    self._dashboard.add_flag(f)
        return flags

    # ------------------------------------------------------------------
    # Pivot handling
    # ------------------------------------------------------------------

    def _handle_pivot(self, level: PivotLevel) -> None:
        """Apply a strategy pivot at the given level.

        Args:
            level: The pivot escalation level to apply.
        """
        console.print(
            f"[info]Strategy pivot: {level.name} "
            f"(pivot #{self._pivot.pivot_count})[/info]"
        )

        prompt = self._pivot.get_pivot_prompt(level)
        self._context.add_user_message(prompt)

        # Session step
        self._session.add_step(StepRecord(
            iteration=self._iteration,
            timestamp=time.time(),
            event="pivot",
            content=f"Pivot level: {level.name}",
        ))

        # Model escalation
        if level == PivotLevel.MODEL_ESCALATION:
            old_model = self._current_model
            self._current_model = select_model_for_task(
                Category.MISC, self._config, is_escalated=True
            )
            console.print(
                f"[info]Model escalated: {old_model} -> "
                f"{self._current_model}[/info]"
            )

        # Ask-user level
        if level == PivotLevel.ASK_USER:
            console.print(
                "\n[bold yellow]The agent is stuck and needs a hint.[/bold yellow]"
            )
            hint = console.input("[bold]Your hint> [/bold]")
            if hint.strip():
                self._context.add_user_message(
                    f"User hint: {hint.strip()}"
                )

    # ------------------------------------------------------------------
    # Flag handling
    # ------------------------------------------------------------------

    def _flag_found(
        self,
        flags: list[str],
        category: Category,
        summary: str = "",
    ) -> SolveResult:
        """Handle found flags and return a success result.

        Args:
            flags: List of flag strings just found.
            category: Challenge category.
            summary: Optional summary text.

        Returns:
            Successful SolveResult.
        """
        for f in flags:
            if f not in self._found_flags:
                self._found_flags.append(f)
        console.print(
            f"\n[flag]FLAG FOUND: {', '.join(self._found_flags)}[/flag]"
        )
        if self._dashboard:
            for f in flags:
                self._dashboard.add_flag(f)
        return SolveResult(
            success=True,
            flags=self._found_flags,
            iterations=self._iteration,
            category=category.value,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gather_file_info(self, files: list[Path] | None) -> str:
        """Gather type information about provided challenge files.

        Args:
            files: List of file paths.

        Returns:
            Multi-line string with file name and detected type.
        """
        if not files:
            return ""

        from utils.file_detector import detect_file_type

        lines: list[str] = []
        for f in files:
            ftype = detect_file_type(f)
            size = f.stat().st_size if f.exists() else 0
            lines.append(f"- {f.name} ({ftype}, {size} bytes)")
        return "\n".join(lines)

    def _build_extra_context(
        self, target_url: str | None, file_info: str
    ) -> str:
        """Build additional context string for the system prompt.

        Args:
            target_url: Optional target URL.
            file_info: File information string.

        Returns:
            Extra context string.
        """
        parts: list[str] = []
        if target_url:
            parts.append(f"Target URL: {target_url}")
        if file_info:
            parts.append(f"Provided files:\n{file_info}")
        parts.append(
            f"Available tools: {', '.join(self._registry.list_names())}"
        )
        return "\n".join(parts)
