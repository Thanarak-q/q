"""Single-agent ReAct loop (orchestrator).

Coordinates the classify -> solve loop, dispatching tool calls
and managing the agent's state until a flag is found, the agent calls
answer_user, or limits are hit.

Architecture: Classifier -> Single Agent (with skill cheat sheet) -> Auto Report
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from openai import APIError, OpenAI, RateLimitError

from agent.classifier import (
    Category,
    IntentResult,
    UserIntent,
    classify_challenge,
    classify_intent,
    max_steps_for_intent,
)
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
from report.generator import generate_report, save_report
from tools.code_analyzer import CodeAnalyzer
from tools.error_analyzer import ErrorAnalyzer
from tools.evidence_tracker import EvidenceTracker, extract_claims
from tools.output_summarizer import OutputSummarizer
from tools.registry import ToolRegistry
from tools.response_parser import ResponseParser
from tools.web_state import WebState
from utils.audit_log import AuditLogger
from utils.cost_tracker import CostTracker
from utils.dashboard import Dashboard
from utils.flag_extractor import extract_flags
from utils.logger import console, get_logger
from utils.session_manager import SessionManager, StepRecord, WorkflowState


# ------------------------------------------------------------------
# Callback interface for UI integration
# ------------------------------------------------------------------


class AgentCallbacks(ABC):
    """Abstract callback interface for agent UI integration.

    Implement this to receive real-time events from the orchestrator.
    The interactive chat UI implements these to render output with Rich.
    """

    @abstractmethod
    def on_thinking(self, text: str) -> None:
        """Called when the agent produces reasoning text."""

    @abstractmethod
    def on_tool_call(self, tool_name: str, args: dict) -> None:
        """Called when a tool is about to be executed."""

    @abstractmethod
    def on_tool_result(self, tool_name: str, output: str, success: bool) -> None:
        """Called when a tool finishes execution."""

    @abstractmethod
    def on_flag_found(self, flag: str) -> None:
        """Called when a flag is discovered."""

    @abstractmethod
    def on_answer(self, answer: str, confidence: str, flag: str | None) -> None:
        """Called when the agent calls answer_user."""

    @abstractmethod
    def on_error(self, message: str) -> None:
        """Called when an error occurs."""

    @abstractmethod
    def on_status(
        self,
        step: int,
        max_steps: int,
        tokens: int,
        cost: float,
        model: str,
    ) -> None:
        """Called to update the status bar after each iteration."""

    @abstractmethod
    def on_phase(self, phase: str, detail: str) -> None:
        """Called during pipeline phases (classifying, planning, solving)."""

    @abstractmethod
    def on_pivot(self, level_name: str, pivot_count: int) -> None:
        """Called when a strategy pivot occurs."""

    @abstractmethod
    def on_model_change(self, old_model: str, new_model: str) -> None:
        """Called when the model is escalated."""

    @abstractmethod
    def on_context_summary(self) -> None:
        """Called when context is summarized."""

    @abstractmethod
    def on_budget_warning(self, warning: str) -> None:
        """Called when approaching budget limits."""

    @abstractmethod
    def on_iteration(self, current: int, total: int) -> None:
        """Called at the start of each iteration."""

    def on_report_saved(self, path: str) -> None:
        """Called when a solve report is saved to disk."""

    def on_ask_user(self, prompt: str) -> str:
        """Called when the agent needs a hint from the user.

        Default implementation reads from console.
        """
        return console.input("[bold]Your hint> [/bold]")


class NullCallbacks(AgentCallbacks):
    """No-op callback implementation for headless/batch mode.

    Falls through to console output.
    """

    def on_thinking(self, text: str) -> None:
        console.print(f"[thinking]{text}[/thinking]")

    def on_tool_call(self, tool_name: str, args: dict) -> None:
        console.print(
            f"[tool_call]Tool: {tool_name}[/tool_call]  "
            f"args={json.dumps(args, ensure_ascii=False)[:200]}"
        )

    def on_tool_result(self, tool_name: str, output: str, success: bool) -> None:
        if success:
            console.print(f"[result]{output[:500]}[/result]")
        else:
            console.print(f"[error]{output}[/error]")

    def on_flag_found(self, flag: str) -> None:
        console.print(f"\n[flag]FLAG FOUND: {flag}[/flag]")

    def on_answer(self, answer: str, confidence: str, flag: str | None) -> None:
        console.print(f"\n[bold green]ANSWER ({confidence}):[/bold green] {answer}")
        if flag:
            console.print(f"[flag]FLAG: {flag}[/flag]")

    def on_error(self, message: str) -> None:
        console.print(f"[error]{message}[/error]")

    def on_status(
        self, step: int, max_steps: int, tokens: int, cost: float, model: str
    ) -> None:
        pass

    def on_phase(self, phase: str, detail: str) -> None:
        console.print(f"\n[step]{phase}:[/step] {detail}", style="bold")

    def on_pivot(self, level_name: str, pivot_count: int) -> None:
        console.print(
            f"[info]Strategy pivot #{pivot_count}: {level_name}[/info]"
        )

    def on_model_change(self, old_model: str, new_model: str) -> None:
        console.print(f"[info]Model: {old_model} -> {new_model}[/info]")

    def on_context_summary(self) -> None:
        console.print("[info]Summarizing context...[/info]")

    def on_budget_warning(self, warning: str) -> None:
        console.print(f"[info]{warning}[/info]")

    def on_iteration(self, current: int, total: int) -> None:
        console.rule(f"[step]Iteration {current}/{total}[/step]")

    def on_report_saved(self, path: str) -> None:
        console.print(f"[result]Report saved: {path}[/result]")


# ------------------------------------------------------------------
# SolveResult
# ------------------------------------------------------------------


@dataclass
class SolveResult:
    """Result of a solve attempt."""

    success: bool
    flags: list[str] = field(default_factory=list)
    answer: str = ""
    answer_confidence: str = ""
    iterations: int = 0
    category: str = "unknown"
    intent: str = "find_flag"
    summary: str = ""
    session_id: str = ""
    cost_usd: float = 0.0
    total_tokens: int = 0


# ------------------------------------------------------------------
# Orchestrator
# ------------------------------------------------------------------


class Orchestrator:
    """Single-agent CTF solver.

    Implements the observe-think-act loop with automatic tool dispatch,
    context management, graduated strategy pivoting, multi-model
    selection, cost tracking, session persistence, and callback-driven
    UI integration.

    Architecture: Classifier -> Single Agent (with skill cheat sheet) -> Auto Report
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        docker_manager: Optional[Any] = None,
        workspace: Path | None = None,
        session_manager: SessionManager | None = None,
        dashboard: Dashboard | None = None,
        enable_dashboard: bool = False,
        callbacks: AgentCallbacks | None = None,
        cost_tracker: CostTracker | None = None,
        repo_path: str | None = None,
        yaml_config_path: str | None = None,
    ) -> None:
        self._config = config or load_config()
        self._client = OpenAI(api_key=self._config.model.api_key)
        self._workspace = workspace or Path.cwd()
        self._docker = docker_manager
        self._registry = ToolRegistry(
            docker_manager=docker_manager,
            workspace=self._workspace,
        )
        self._context = ContextManager(self._client, self._config)
        self._log = get_logger()
        self._iteration = 0
        self._found_flags: list[str] = []
        self._custom_flag_pattern: str | None = None
        self._cancelled = False
        self._intent: IntentResult | None = None
        self._start_time: float = 0.0
        self._audit: AuditLogger | None = None

        # Evidence tracking (anti-hallucination)
        self._evidence = EvidenceTracker()

        # Error analysis and output summarization
        self._error_analyzer = ErrorAnalyzer()
        self._output_summarizer = OutputSummarizer()
        self._thinking_warnings = 0

        # Web state tracking (multi-step exploit state)
        self._web_state = WebState()
        self._response_parser = ResponseParser()

        # Source code analysis (white-box mode)
        self._repo_path: str | None = repo_path

        # YAML config (for target info, parallel settings, etc.)
        self._yaml_config_path: str | None = yaml_config_path
        self._yaml_config: Any = None
        if yaml_config_path:
            try:
                from config_yaml.loader import load_yaml_config
                self._yaml_config = load_yaml_config(yaml_config_path)
            except Exception:
                pass

        # Callbacks (use NullCallbacks for backward compat)
        self._cb: AgentCallbacks = callbacks or NullCallbacks()

        # --- Advanced features ---
        self._pivot = PivotManager(
            stall_threshold=self._config.agent.stall_threshold,
        )
        self._cost = cost_tracker or CostTracker(
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

    @property
    def cost_tracker(self) -> CostTracker:
        """Access the cost tracker."""
        return self._cost

    @property
    def current_model(self) -> str:
        """Current model being used."""
        return self._current_model

    @current_model.setter
    def current_model(self, model: str) -> None:
        """Override the current model."""
        self._current_model = model

    def cancel(self) -> None:
        """Cancel the current solve loop (called from Ctrl+C handler)."""
        self._cancelled = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(
        self,
        description: str,
        files: list[Path] | None = None,
        target_url: str | None = None,
        flag_pattern: str | None = None,
        forced_category: str | None = None,
    ) -> SolveResult:
        """Solve a CTF challenge.

        This is the main entry point. It classifies the challenge,
        then enters the single-agent ReAct loop with skill-based prompts.

        Args:
            description: Challenge description text.
            files: Optional list of challenge file paths.
            target_url: Optional target service URL.
            flag_pattern: Optional custom flag regex pattern.
            forced_category: Optional forced category string.

        Returns:
            SolveResult with success status and found flags.
        """
        self._custom_flag_pattern = flag_pattern
        self._cancelled = False
        self._start_time = time.time()
        self._evidence = EvidenceTracker()  # reset for each solve
        self._web_state = WebState()  # reset for each solve
        self._error_analyzer.reset()  # reset for each solve
        self._thinking_warnings = 0
        if target_url:
            self._web_state.base_url = target_url

        # Create session
        sid = self._session.new_session(
            description=description,
            target_url=target_url or "",
            files=[str(f) for f in files] if files else [],
            flag_pattern=flag_pattern or "",
        )

        # Create audit logger
        self._audit = AuditLogger(
            session_id=sid,
            session_dir=self._config.log.session_dir,
        )
        self._audit.log_session_start(
            challenge=description,
            files=[str(f) for f in files] if files else [],
            target_url=target_url or "",
        )

        # Start dashboard
        if self._dashboard:
            self._dashboard.start()

        try:
            result = self._run_pipeline(
                description, files, target_url, flag_pattern, forced_category,
            )
        except KeyboardInterrupt:
            self._cb.on_error("Interrupted by user.")
            self._session.transition(WorkflowState.PAUSED, "Interrupted by user")
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
        final_status = "solved" if result.success else "failed"
        result.session_id = sid
        result.cost_usd = self._cost.total_cost
        result.total_tokens = self._cost.total_tokens
        self._session.update(
            status=final_status,
            flags=result.flags,
            cost=self._cost.to_dict(),
            model_used=self._current_model,
        )
        self._session.save()

        # Audit: session end
        if self._audit:
            self._audit.log_session_end(
                status=final_status,
                total_steps=result.iterations,
                total_tokens=self._cost.total_tokens,
                total_cost=self._cost.total_cost,
            )
            self._audit.close()

        # Generate and save report
        self._generate_and_save_report(result)

        # Record to knowledge base + stats
        self._record_knowledge_and_stats(description, result)

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
            self._cb.on_error(f"Session {session_id} not found.")
            return SolveResult(success=False, summary="Session not found.")

        self._custom_flag_pattern = flag_pattern or data.flag_pattern or None
        self._iteration = data.current_iteration
        self._found_flags = list(data.flags)
        self._cancelled = False
        self._start_time = time.time()

        # Create audit logger (append to existing)
        self._audit = AuditLogger(
            session_id=session_id,
            session_dir=self._config.log.session_dir,
        )
        self._audit.log("session_resume", iteration=self._iteration)

        # Restore messages
        self._context._messages = list(data.messages)  # noqa: SLF001

        # Determine category
        category = Category.MISC
        for cat in Category:
            if cat.value == data.category:
                category = cat
                break

        self._cb.on_phase("Resume", f"Session {session_id} at iteration {self._iteration}")

        self._session.update(status="in_progress")
        result = self._react_loop(category)
        result.session_id = session_id
        result.cost_usd = self._cost.total_cost
        result.total_tokens = self._cost.total_tokens

        final_status = "solved" if result.success else "failed"
        self._session.update(
            status=final_status,
            flags=result.flags,
            cost=self._cost.to_dict(),
            model_used=self._current_model,
        )
        self._session.save()

        # Audit: session end
        if self._audit:
            self._audit.log_session_end(
                status=final_status,
                total_steps=result.iterations,
                total_tokens=self._cost.total_tokens,
                total_cost=self._cost.total_cost,
            )
            self._audit.close()

        # Generate and save report
        self._generate_and_save_report(result)

        return result

    # ------------------------------------------------------------------
    # Single-agent pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        description: str,
        files: list[Path] | None,
        target_url: str | None,
        flag_pattern: str | None,
        forced_category: str | None = None,
    ) -> SolveResult:
        """Run the classify -> solve pipeline (single agent).

        Args:
            description: Challenge description.
            files: Challenge files.
            target_url: Target URL.
            flag_pattern: Custom flag regex.
            forced_category: Optional forced category.

        Returns:
            SolveResult from the ReAct loop.
        """
        # --- Phase 0: Intent classification ---
        self._cb.on_phase("Intent", "Classifying user intent...")
        self._session.transition(WorkflowState.CLASSIFYING, "Intent classification")
        self._intent = classify_intent(description, self._client, self._config)
        self._cb.on_phase(
            "Intent",
            f"{self._intent.intent.value} — {self._intent.stop_criteria}",
        )

        # --- Phase 1: Category classification ---
        self._cb.on_phase("Classifying", "Detecting challenge category...")
        file_info = self._gather_file_info(files)

        if forced_category:
            category = Category.MISC
            for cat in Category:
                if cat.value == forced_category:
                    category = cat
                    break
            self._cb.on_phase("Category", f"{category.value} (forced)")
        else:
            category = classify_challenge(
                description, file_info, self._client, self._config
            )
            self._cb.on_phase("Category", category.value)

        self._session.update(category=category.value)

        # Audit: classify
        if self._audit:
            intent_str = self._intent.intent.value if self._intent else "find_flag"
            self._audit.log_classify(category=category.value, intent=intent_str)

        # --- Phase 2: Planning ---
        self._session.transition(WorkflowState.PLANNING, f"Category: {category.value}")
        self._cb.on_phase("Planning", "Creating attack plan...")
        plan = create_plan(
            description, category, file_info, self._client, self._config
        )
        self._cb.on_thinking(plan)
        self._session.update(plan=plan)

        # Audit: plan
        if self._audit:
            self._audit.log_plan(model=self._config.model.fast_model, plan=plan)

        # Select initial model
        self._current_model = select_model_for_task(
            category, self._config, is_escalated=False
        )
        self._log.info(f"Initial model: {self._current_model}")

        # --- Phase 2.5: Knowledge base hints ---
        knowledge_hint = self._get_knowledge_hints(description, category.value)

        # --- Phase 2.6: Source code analysis (white-box) ---
        code_hints = self._run_code_analysis()

        # --- Phase 3: Setup context with skill-based prompt ---
        intent_context = self._build_intent_context()
        extra_ctx = self._build_extra_context(target_url, file_info)
        if code_hints:
            extra_ctx += "\n" + code_hints

        # Inject target config from YAML
        if self._yaml_config:
            try:
                from config_yaml.loader import inject_target_to_prompt
                target_prompt = inject_target_to_prompt(self._yaml_config)
                if target_prompt:
                    extra_ctx += "\n" + target_prompt
            except Exception:
                pass

        # Build scope lock to prevent agent from drifting
        scope = {
            "challenge": description[:200],
            "category": category.value,
            "goal": self._intent.intent.value if self._intent else "find_flag",
            "files": [f.name for f in files] if files else [],
        }
        if target_url:
            scope["files"].append(target_url)

        system_prompt = build_system_prompt(
            category=category.value,
            extra_context=extra_ctx,
            intent_context=intent_context,
            scope=scope,
        )
        self._context.set_system_prompt(system_prompt)

        initial_message = f"Challenge description:\n{description}"
        if target_url:
            initial_message += f"\n\nTarget URL: {target_url}"
        if file_info:
            initial_message += f"\n\nFiles:\n{file_info}"
        initial_message += f"\n\nAttack plan:\n{plan}"

        if knowledge_hint:
            initial_message += knowledge_hint

        # Tailor the initial instruction based on intent
        if self._intent.intent == UserIntent.FIND_FLAG:
            initial_message += (
                "\n\nBegin solving. Start with step 1 of the plan. "
                "Think step by step, use tools, and find the flag. "
                "When you find it, call answer_user with the flag."
            )
        elif self._intent.intent == UserIntent.ANSWER_QUESTION:
            initial_message += (
                f"\n\nThe user wants to know: {self._intent.specific_question}\n"
                f"Find the answer efficiently and call answer_user when ready. "
                f"Do not search for a flag unless the answer IS a flag."
            )
        elif self._intent.intent == UserIntent.ANALYZE:
            initial_message += (
                "\n\nPerform a thorough analysis and call answer_user with "
                "your findings when done."
            )
        else:  # HELP_SOLVE
            initial_message += (
                "\n\nProvide guidance and call answer_user with your "
                "recommendations when ready."
            )

        self._context.add_user_message(initial_message)

        # Dashboard update
        if self._dashboard:
            self._dashboard.set_challenge(description, category.value)

        # Save initial messages for resume support
        self._session.update(messages=self._context.messages)

        # --- Phase 4: ReAct loop ---
        # Determine step budget based on intent
        intent_max = max_steps_for_intent(self._intent.intent, category)
        effective_max = min(self._config.agent.max_iterations, intent_max)
        self._session.transition(WorkflowState.SOLVING, f"Max {effective_max} steps")
        self._cb.on_phase(
            "Solving",
            f"Entering solve loop (max {effective_max} steps)...",
        )
        result = self._react_loop(category, max_iterations_override=effective_max)

        # --- Phase 5: Parallel fallback (if primary solve failed) ---
        if not result.success and self._should_try_parallel(category):
            parallel_result = self._try_parallel_solve(
                description, category, files, target_url, flag_pattern,
            )
            if parallel_result is not None and parallel_result.success:
                return parallel_result

        return result

    def _react_loop(
        self,
        category: Category,
        max_iterations_override: int | None = None,
    ) -> SolveResult:
        """Execute the main ReAct (Reason-Act-Observe) loop.

        Args:
            category: The classified challenge category.
            max_iterations_override: Optional override for max iterations.

        Returns:
            SolveResult after the loop terminates.
        """
        max_iter = max_iterations_override or self._config.agent.max_iterations

        while self._iteration < max_iter:
            # Check cancellation
            if self._cancelled:
                self._cb.on_error("Cancelled by user.")
                break

            self._iteration += 1
            self._cb.on_iteration(self._iteration, max_iter)

            # --- Budget check ---
            warning = self._cost.budget_warning()
            if warning:
                self._cb.on_budget_warning(warning)
            if self._cost.is_over_budget():
                self._cb.on_error("Budget limit reached. Stopping.")
                break

            # --- Context window check ---
            if self._context.needs_summarization():
                self._cb.on_context_summary()
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

            # --- Early stop nudge for answer_question intent ---
            if (
                self._intent
                and self._intent.intent == UserIntent.ANSWER_QUESTION
                and self._iteration >= 3
                and self._iteration % 3 == 0
            ):
                self._context.add_user_message(
                    "You seem to have gathered information. If you have enough "
                    "to answer the user's question, call answer_user now. "
                    "Be efficient — do not keep exploring if you already know "
                    "the answer."
                )

            # --- Final attempt prompt ---
            if self._iteration == max_iter - 3:
                self._context.add_user_message(FINAL_ATTEMPT_PROMPT)

            # --- LAST STEP: force answer ---
            if self._iteration >= max_iter - 1:
                self._context.add_user_message(
                    "LAST STEP. You MUST call answer_user NOW with your best "
                    "answer. Do not run any more commands — just answer."
                )

            # --- Call LLM ---
            cost_records_before = len(self._cost.records)
            response_message = self._call_llm()
            if response_message is None:
                continue

            # Capture token/cost info from the new cost record (if any)
            llm_tokens = 0
            llm_cost = 0.0
            if len(self._cost.records) > cost_records_before:
                rec = self._cost.records[-1]
                llm_tokens = rec.prompt_tokens + rec.completion_tokens
                llm_cost = rec.cost_usd

            self._context.add_assistant_message(response_message)

            # --- Process text content ---
            text_content = response_message.get("content", "") or ""
            if text_content:
                self._cb.on_thinking(text_content)
                if self._dashboard:
                    self._dashboard.set_thinking(text_content)

                self._session.add_step(StepRecord(
                    iteration=self._iteration,
                    timestamp=time.time(),
                    event="llm_response",
                    model=self._current_model,
                    content=text_content,
                    tokens_used=llm_tokens,
                    cost_usd=llm_cost,
                ))

                flags = extract_flags(text_content, self._custom_flag_pattern)
                if flags:
                    return self._flag_found(flags, category, text_content)

            # --- Thinking validation ---
            thinking_warning = self._validate_thinking(
                text_content, self._iteration - 1,
            )
            if thinking_warning == "__SHOULD_STOP__":
                # Agent thinks it's done but didn't call answer_user
                self._context.add_user_message(
                    "Your <think> says you're done. "
                    "Call answer_user NOW with your answer."
                )
                continue
            elif thinking_warning and self._thinking_warnings < 2:
                self._context.add_user_message(thinking_warning)
                self._thinking_warnings += 1
                continue

            # --- Process tool calls ---
            tool_calls = response_message.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    if self._cancelled:
                        break

                    # Check if this is an answer_user call
                    func = tc.get("function", {})
                    if func.get("name") == "answer_user":
                        return self._handle_answer_user(tc, category)

                    flags = self._execute_tool_call(tc)
                    if flags:
                        return self._flag_found(flags, category)
            elif not text_content:
                self._log.warning("Empty response from LLM")

            # --- Status update ---
            self._cb.on_status(
                step=self._iteration,
                max_steps=max_iter,
                tokens=self._cost.total_tokens,
                cost=self._cost.total_cost,
                model=self._current_model,
            )

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

        # Exhausted iterations or cancelled
        if self._cancelled:
            summary = "Cancelled by user."
        else:
            summary = (
                "Exhausted maximum iterations. "
                "Here is what was discovered so far."
            )
            self._session.transition(WorkflowState.FAILED, summary)
        self._cb.on_error(summary)
        return SolveResult(
            success=bool(self._found_flags),
            flags=self._found_flags,
            iterations=self._iteration,
            category=category.value,
            intent=self._intent.intent.value if self._intent else "find_flag",
            summary=summary,
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
                    self._cb.on_error(f"API error after 3 retries: {exc}")
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
            self._cb.on_error(error_msg)
            self._context.add_tool_result(tc_id, error_msg)
            return []

        self._cb.on_tool_call(name, args)

        # Audit: tool call
        if self._audit:
            self._audit.log_tool_call(
                step=self._iteration, tool=name, args=args,
            )

        result = self._registry.execute(name, args)

        output = result.output if result.success else f"[ERROR] {result.error}"

        # Record evidence for anti-hallucination tracking (raw output)
        command_str = json.dumps(args, ensure_ascii=False)[:300]
        self._evidence.add(tool=name, command=command_str, output=output)

        # Summarize long outputs to save context tokens
        summarized_output = self._output_summarizer.summarize(
            tool=name, command=command_str, output=output,
        )

        # Smart response parsing for web tools (network, browser, recon)
        enriched_output = summarized_output
        if result.success and name in ("network", "browser", "recon"):
            enriched_output = self._enrich_web_output(name, args, summarized_output)

        # Error analysis and adaptation guidance
        error_info = self._error_analyzer.analyze(output)
        if error_info:
            self._error_analyzer.track_failure(
                f"{name}: {command_str[:100]} → {error_info['error_type']}"
            )
            enriched_output = (
                f"{enriched_output}\n\n"
                f"⚠️ ERROR DETECTED: {error_info['error_type']}\n"
                f"SUGGESTION: {error_info['suggestion']}\n"
                f"{self._error_analyzer.get_failure_context()}\n"
                f"Think about WHY this failed and try a DIFFERENT approach."
            )

        self._cb.on_tool_result(name, output, result.success)

        # Audit: tool result
        if self._audit:
            if result.success:
                self._audit.log_tool_result(
                    step=self._iteration, tool=name,
                    success=True, output_length=len(result.output),
                )
            else:
                self._audit.log_tool_error(
                    step=self._iteration, tool=name,
                    error=result.error or output[:300],
                )

        if result.success:
            self._pivot.record_progress(self._iteration)

        self._context.add_tool_result(tc_id, enriched_output)

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
            for f in flags:
                self._cb.on_flag_found(f)
            if self._dashboard:
                for f in flags:
                    self._dashboard.add_flag(f)

            # Inject stop nudge into context so model knows to call answer_user
            flag_str = ", ".join(flags)
            self._context.add_user_message(
                f"FLAG DETECTED: {flag_str}\n"
                f"You MUST call answer_user NOW with this flag. "
                f"Do NOT run any more commands. Mission complete."
            )
        return flags

    # ------------------------------------------------------------------
    # answer_user handling
    # ------------------------------------------------------------------

    def _handle_answer_user(
        self,
        tool_call: dict[str, Any],
        category: Category,
    ) -> SolveResult:
        """Handle the answer_user tool call and terminate the loop.

        Args:
            tool_call: The answer_user tool call dict.
            category: Challenge category.

        Returns:
            SolveResult with the answer.
        """
        func = tool_call["function"]
        tc_id = tool_call["id"]

        try:
            args = json.loads(func["arguments"])
        except json.JSONDecodeError:
            args = {"answer": func.get("arguments", ""), "confidence": "low"}

        answer = args.get("answer", "")
        confidence = args.get("confidence", "medium")
        flag = args.get("flag", "") or ""

        # --- Evidence validation (anti-hallucination) ---
        claims = extract_claims(answer)
        if claims:
            _, unverified = self._evidence.verify_claims(claims)
            if unverified:
                self._log.info(
                    f"Unverified claims in answer: {unverified}"
                )
                # Re-prompt the agent to fix unverified claims
                self._context.add_tool_result(
                    tc_id,
                    f"WARNING: Your answer contains data not found in any "
                    f"tool output: {unverified}. Remove these claims or "
                    f"provide the tool command that produced this data. "
                    f"Call answer_user again with a corrected answer.",
                )
                # Give the agent one more chance to correct
                corrected_msg = self._call_llm()
                if corrected_msg is not None:
                    self._context.add_assistant_message(corrected_msg)
                    # Check if the corrected response calls answer_user
                    tc_list = corrected_msg.get("tool_calls", [])
                    for corrected_tc in tc_list:
                        cfunc = corrected_tc.get("function", {})
                        if cfunc.get("name") == "answer_user":
                            try:
                                cargs = json.loads(cfunc["arguments"])
                            except json.JSONDecodeError:
                                cargs = {}
                            answer = cargs.get("answer", answer)
                            confidence = cargs.get("confidence", confidence)
                            flag = cargs.get("flag", "") or flag
                            tc_id = corrected_tc["id"]
                            break

        # Execute the tool so it produces output for logging
        result = self._registry.execute("answer_user", args)
        self._context.add_tool_result(tc_id, result.output)

        self._cb.on_answer(answer, confidence, flag if flag else None)

        # Audit: answer
        if self._audit:
            self._audit.log_answer(answer=answer, confidence=confidence, flag=flag)

        # If a flag was provided, add it to found flags
        if flag:
            if flag not in self._found_flags:
                self._found_flags.append(flag)
                self._cb.on_flag_found(flag)
            if self._dashboard:
                self._dashboard.add_flag(flag)

        # Session step
        self._session.add_step(StepRecord(
            iteration=self._iteration,
            timestamp=time.time(),
            event="tool_call",
            model=self._current_model,
            tool_name="answer_user",
            tool_args=args,
            tool_output=result.output[:2000],
            flags_found=[flag] if flag else [],
        ))

        self._session.transition(WorkflowState.SOLVED, f"Answer: {answer[:80]}")

        return SolveResult(
            success=True,
            flags=self._found_flags,
            answer=answer,
            answer_confidence=confidence,
            iterations=self._iteration,
            category=category.value,
            intent=self._intent.intent.value if self._intent else "find_flag",
            summary=answer,
        )

    # ------------------------------------------------------------------
    # Pivot handling
    # ------------------------------------------------------------------

    def _handle_pivot(self, level: PivotLevel) -> None:
        """Apply a strategy pivot at the given level."""
        self._cb.on_pivot(level.name, self._pivot.pivot_count)

        # Audit: pivot
        if self._audit:
            self._audit.log_pivot(level=level.name, pivot_count=self._pivot.pivot_count)

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
            self._cb.on_model_change(old_model, self._current_model)
            if self._audit:
                self._audit.log_model_switch(old_model, self._current_model)

        # Ask-user level
        if level == PivotLevel.ASK_USER:
            hint = self._cb.on_ask_user(
                "The agent is stuck and needs a hint. "
                "Please provide guidance:"
            )
            if hint and hint.strip():
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
        """Handle found flags and return a success result."""
        for f in flags:
            if f not in self._found_flags:
                self._found_flags.append(f)
                self._cb.on_flag_found(f)
                if self._audit:
                    self._audit.log_flag_found(f)

        if self._dashboard:
            for f in flags:
                self._dashboard.add_flag(f)

        self._session.transition(
            WorkflowState.SOLVED, f"Flags: {', '.join(flags)}"
        )

        return SolveResult(
            success=True,
            flags=self._found_flags,
            iterations=self._iteration,
            category=category.value,
            intent=self._intent.intent.value if self._intent else "find_flag",
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _generate_and_save_report(self, result: SolveResult) -> None:
        """Generate a Markdown report and save it to ./reports/."""
        try:
            session_data = self._session.get_session_data()
            if session_data is None:
                return

            duration = time.time() - self._start_time if self._start_time else 0.0
            report_md = generate_report(
                session_data=asdict(session_data),
                cost_data=self._cost.to_dict(),
                duration_s=duration,
                evidence_tracker=self._evidence,
                answer=result.answer,
            )
            report_path = save_report(
                report_md=report_md,
                session_id=result.session_id,
            )
            self._cb.on_report_saved(str(report_path))
        except Exception as exc:
            self._log.debug(f"Report generation failed: {exc}")

    # ------------------------------------------------------------------
    # Thinking validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_thinking(response_text: str, step: int) -> str | None:
        """Check if the agent is thinking before acting.

        Returns:
            Warning message if not thinking, "__SHOULD_STOP__" if agent
            says it's done, or None if everything is fine.
        """
        import re

        has_think = "<think>" in response_text

        if not has_think and step == 0:
            return (
                "You must plan first. Use <think> to write: "
                "GOAL, PLAN, SCOPE, DONE WHEN before your first action."
            )

        if not has_think and step > 0:
            return (
                "Think before acting. Use <think> to write: "
                "LEARNED, HYPOTHESIS, NEXT, DONE? "
                "before every tool call."
            )

        # Check for "DONE? yes" pattern — agent should stop
        if has_think:
            think_match = re.search(
                r'<think>(.*?)</think>', response_text, re.DOTALL,
            )
            if think_match:
                content = think_match.group(1).lower()
                if 'done?' in content and 'yes' in content:
                    return "__SHOULD_STOP__"

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_try_parallel(self, category: Category) -> bool:
        """Check whether parallel solving should be attempted."""
        # Check YAML config
        if self._yaml_config:
            if not self._yaml_config.parallel_enabled:
                return False

        # Check pipeline config
        if not self._config.pipeline.fast_path_enabled:
            return False

        # Only try for categories that have defined approaches
        from agent.parallel import CATEGORY_APPROACHES
        return category.value in CATEGORY_APPROACHES

    def _try_parallel_solve(
        self,
        description: str,
        category: Category,
        files: list[Path] | None,
        target_url: str | None,
        flag_pattern: str | None,
    ) -> SolveResult | None:
        """Try multiple approaches in parallel as a fallback."""
        from agent.parallel import ParallelSolver

        self._cb.on_phase(
            "Parallel",
            f"Primary solve failed — trying parallel approaches for {category.value}...",
        )

        max_parallel = 3
        if self._yaml_config:
            max_parallel = self._yaml_config.parallel_max

        solver = ParallelSolver(
            config=self._config,
            docker_manager=self._docker,
            workspace=self._workspace,
            max_parallel=max_parallel,
            callbacks=self._cb,
        )

        attempt = solver.solve_parallel(
            description=description,
            category=category.value,
            files=files,
            target_url=target_url,
            flag_pattern=flag_pattern,
        )

        if attempt is None:
            return None

        if attempt.success:
            self._cb.on_phase("Parallel", f"'{attempt.approach}' succeeded!")
            if attempt.flags:
                self._found_flags.extend(attempt.flags)
                for f in attempt.flags:
                    self._cb.on_flag_found(f)

            return SolveResult(
                success=True,
                flags=attempt.flags or self._found_flags,
                answer=attempt.answer,
                iterations=self._iteration + attempt.steps,
                category=category.value,
                intent=self._intent.intent.value if self._intent else "find_flag",
                summary=f"Solved via parallel approach: {attempt.approach}",
            )

        self._cb.on_phase("Parallel", "All parallel approaches failed")
        return None

    def _run_code_analysis(self) -> str:
        """Run static code analysis if a repo path was provided.

        Returns:
            Formatted findings string for the system prompt, or "".
        """
        if not self._repo_path or not Path(self._repo_path).is_dir():
            return ""

        try:
            analyzer = CodeAnalyzer()
            analysis = analyzer.analyze_directory(self._repo_path)

            if analysis["findings"]:
                summary = analyzer.summary(analysis)
                self._cb.on_phase("Code Analysis", summary)
                self._log.info(summary)

                if self._audit:
                    self._audit.log(
                        "code_analysis",
                        language=analysis["language"],
                        files_scanned=analysis["files_scanned"],
                        findings_count=len(analysis["findings"]),
                    )

                return analyzer.format_for_prompt(analysis)
            else:
                self._cb.on_phase(
                    "Code Analysis",
                    f"Scanned {analysis['files_scanned']} files — no patterns found",
                )
                return ""
        except Exception as exc:
            self._log.debug(f"Code analysis failed: {exc}")
            return ""

    def _enrich_web_output(
        self, tool_name: str, args: dict[str, Any], output: str
    ) -> str:
        """Parse web tool output and append CTF-relevant findings.

        Also updates web state (cookies, tech stack, endpoints) and
        suggests exploit templates when indicators are found.

        Args:
            tool_name: The tool that produced the output.
            args: Tool arguments.
            output: Raw tool output.

        Returns:
            Enriched output with findings appended.
        """
        try:
            parsed = self._response_parser.parse(output)

            # Update web state from parsed response
            if parsed.cookies:
                self._web_state.set_cookies(parsed.cookies)
            if parsed.tech_stack:
                for t in parsed.tech_stack:
                    if t not in self._web_state.tech_stack:
                        self._web_state.tech_stack.append(t)
            if parsed.interesting_paths:
                for p in parsed.interesting_paths[:10]:
                    self._web_state.add_endpoint(p)

            # Format findings
            findings = self._response_parser.format_findings(parsed)
            if not findings:
                return output

            # Suggest exploit templates based on findings
            template_hint = ""
            try:
                from knowledge.exploit_templates import (
                    format_templates_for_prompt,
                    suggest_templates,
                )

                indicators = {
                    "sql_errors": parsed.sql_errors,
                    "ssti_indicators": parsed.ssti_indicators,
                    "jwt_tokens": parsed.jwt_tokens,
                    "tech_stack": parsed.tech_stack,
                    "status_code": parsed.status_code,
                }
                templates = suggest_templates(indicators=indicators)
                if templates:
                    template_hint = "\n" + format_templates_for_prompt(
                        templates[:3]
                    )
            except Exception:
                pass

            enriched = output + "\n\n" + findings
            if template_hint:
                enriched += "\n" + template_hint

            # Add web state summary periodically (every 3 iterations)
            if self._iteration % 3 == 0:
                state_summary = self._web_state.summary()
                if state_summary:
                    enriched += "\n\n" + state_summary

            return enriched
        except Exception:
            return output

    def _build_intent_context(self) -> str:
        """Build intent-specific context for the system prompt."""
        if self._intent is None:
            return ""

        intent = self._intent
        lines = [f"User intent: {intent.intent.value}"]
        if intent.specific_question:
            lines.append(f"User wants to know: {intent.specific_question}")
        lines.append(f"Stop criteria: {intent.stop_criteria}")

        if intent.intent == UserIntent.ANSWER_QUESTION:
            lines.append(
                "IMPORTANT: Answer the specific question above. "
                "Do not search for a flag unless the question IS about a flag."
            )
        elif intent.intent == UserIntent.ANALYZE:
            lines.append(
                "Provide a thorough analysis. Call answer_user with your "
                "findings when done."
            )
        elif intent.intent == UserIntent.HELP_SOLVE:
            lines.append(
                "Provide guidance and hints. Do not solve autonomously. "
                "Call answer_user with your recommendations."
            )

        return "\n".join(lines)

    def _gather_file_info(self, files: list[Path] | None) -> str:
        """Gather type information about provided challenge files."""
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
        """Build additional context string for the system prompt."""
        parts: list[str] = []
        parts.append(f"Working directory: {self._workspace}")
        if target_url:
            parts.append(f"Target URL: {target_url}")
        if file_info:
            parts.append(f"Provided files:\n{file_info}")
        parts.append(
            f"Available tools: {', '.join(self._registry.list_names())}"
        )
        return "\n".join(parts)

    def _get_knowledge_hints(self, description: str, category: str) -> str:
        """Search the knowledge base for similar past solves.

        Returns:
            Hint string to append to the initial message, or empty.
        """
        try:
            from knowledge.base import KnowledgeBase

            kb = KnowledgeBase()
            similar = kb.search(description, category=category, limit=2)
            if not similar:
                return ""

            lines = ["\n\n## Hints from similar past solves:"]
            for s in similar:
                lines.append(f"- \"{s['challenge'][:100]}\"")
                cmds = s.get("commands", [])[:2]
                if cmds:
                    lines.append(f"  Used: {', '.join(cmds)}")
                techs = s.get("techniques", [])
                if techs:
                    lines.append(f"  Techniques: {', '.join(techs[:3])}")
                lines.append(f"  Solved in {s.get('steps', '?')} steps")
            return "\n".join(lines)
        except Exception:
            return ""

    def _record_knowledge_and_stats(
        self, description: str, result: SolveResult
    ) -> None:
        """Save solve data to the knowledge base and stats tracker."""
        try:
            from knowledge.base import KnowledgeBase
            from knowledge.extractor import extract_from_solve

            session_data = self._session.get_session_data()
            steps_log = session_data.steps if session_data else []

            entry = extract_from_solve(
                challenge=description,
                category=result.category,
                steps_log=steps_log,
                answer=result.answer,
                flag=result.flags[0] if result.flags else None,
                cost=result.cost_usd,
            )
            KnowledgeBase().add(entry)
        except Exception as exc:
            self._log.debug(f"Knowledge save failed: {exc}")

        try:
            from stats.tracker import StatsTracker

            duration = time.time() - self._start_time if self._start_time else 0.0
            StatsTracker().record({
                "session_id": result.session_id,
                "challenge": description[:200],
                "category": result.category,
                "intent": result.intent,
                "success": result.success,
                "steps": result.iterations,
                "tokens": result.total_tokens,
                "cost": round(result.cost_usd, 4),
                "duration": round(duration, 1),
                "model": self._current_model,
            })
        except Exception as exc:
            self._log.debug(f"Stats save failed: {exc}")
