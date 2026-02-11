"""Multi-agent pipeline coordinator.

Orchestrates the Recon → Analyst → Solver → Reporter pipeline.
Supports fast-path (skip analyst for easy challenges) and parallel
solving (multiple hypotheses tested concurrently).
"""

from __future__ import annotations

import json
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from config import AppConfig
from openai import OpenAI
from report.generator import generate_report, save_report
from utils.audit_log import AuditLogger
from utils.cost_tracker import CostTracker
from utils.flag_extractor import extract_flags
from utils.logger import get_logger
from utils.session_manager import SessionManager, StepRecord

from agent.agents.analyst_agent import AnalystAgent
from agent.agents.recon_agent import ReconAgent
from agent.agents.reporter_agent import ReporterAgent
from agent.agents.solver_agent import SolverAgent
from agent.base_agent import AgentResult
from agent.classifier import (
    Category,
    IntentResult,
    UserIntent,
    classify_challenge,
    classify_intent,
    get_playbook,
    max_steps_for_intent,
)
from agent.orchestrator import AgentCallbacks, NullCallbacks, SolveResult
from agent.planner import create_plan


@dataclass
class PipelineState:
    """Tracks deliverables and metadata across pipeline phases."""

    session_id: str = ""
    category: str = "misc"
    intent: str = "find_flag"
    stop_criteria: str = "Find the flag."
    specific_question: str = ""
    plan: str = ""
    fast_path: bool = False
    difficulty: str = "medium"

    # Deliverables from each phase
    recon_deliverable: dict[str, Any] = field(default_factory=dict)
    analyst_deliverable: dict[str, Any] = field(default_factory=dict)
    solver_deliverable: dict[str, Any] = field(default_factory=dict)
    reporter_deliverable: dict[str, Any] = field(default_factory=dict)


class Pipeline:
    """Multi-agent pipeline coordinator.

    Runs: classify → recon → [analyst] → solver(s) → reporter.
    """

    def __init__(
        self,
        config: AppConfig,
        docker_manager: Optional[Any] = None,
        workspace: Path | None = None,
        callbacks: AgentCallbacks | None = None,
        cost_tracker: CostTracker | None = None,
        session_manager: SessionManager | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._config = config
        self._client = OpenAI(api_key=config.model.api_key)
        self._docker = docker_manager
        self._workspace = workspace or Path.cwd()
        self._cb: AgentCallbacks = callbacks or NullCallbacks()
        self._cost = cost_tracker or CostTracker(
            budget_limit=config.agent.max_cost_per_challenge,
        )
        self._session = session_manager or SessionManager(
            session_dir=config.log.session_dir,
        )
        self._audit = audit
        self._log = get_logger()
        self._state = PipelineState()
        self._start_time = time.time()
        self._total_iterations = 0
        self._found_flags: list[str] = []

    def run(
        self,
        description: str,
        files: list[Path] | None = None,
        target_url: str | None = None,
        flag_pattern: str | None = None,
        forced_category: str | None = None,
    ) -> SolveResult:
        """Execute the full multi-agent pipeline.

        Args:
            description: Challenge description.
            files: Optional challenge file paths.
            target_url: Optional target service URL.
            flag_pattern: Optional custom flag regex.
            forced_category: Optional forced category.

        Returns:
            SolveResult with success status and found flags.
        """
        # Gather file info
        file_info = self._gather_file_info(files)

        # Build shared context that grows with each phase
        context: dict[str, Any] = {
            "description": description,
            "files": [str(f) for f in files] if files else [],
            "file_info": file_info,
            "target_url": target_url,
            "flag_pattern": flag_pattern,
            "workspace": str(self._workspace),
        }

        # ---- Phase 0: Classification ----
        self._cb.on_pipeline_phase("classify", "Detecting category and intent...")

        intent_result = classify_intent(description, self._client, self._config)
        self._state.intent = intent_result.intent.value
        self._state.stop_criteria = intent_result.stop_criteria
        self._state.specific_question = intent_result.specific_question
        context["intent"] = intent_result.intent.value
        context["stop_criteria"] = intent_result.stop_criteria
        context["specific_question"] = intent_result.specific_question

        if forced_category:
            category = Category.MISC
            for cat in Category:
                if cat.value == forced_category:
                    category = cat
                    break
            self._state.category = category.value
        else:
            category = classify_challenge(
                description, file_info, self._client, self._config
            )
            self._state.category = category.value

        context["category"] = self._state.category

        # Create attack plan
        plan = create_plan(description, category, file_info, self._client, self._config)
        self._state.plan = plan
        context["plan"] = plan

        self._cb.on_pipeline_phase(
            "classify",
            f"{self._state.category} | {self._state.intent} | plan ready",
        )

        # Audit
        if self._audit:
            self._audit.log_classify(
                category=self._state.category, intent=self._state.intent
            )
            self._audit.log_plan(model=self._config.model.fast_model, plan=plan)

        # ---- Phase 1: Recon ----
        recon_result = self._run_recon(context, flag_pattern)
        self._total_iterations += recon_result.iterations
        self._collect_flags(recon_result.flags)

        if recon_result.success:
            self._state.recon_deliverable = recon_result.deliverable
            context["recon_deliverable"] = recon_result.deliverable

            # Update category from recon if it detected one
            recon_cat = recon_result.deliverable.get("category")
            if recon_cat and recon_cat != self._state.category:
                self._state.category = recon_cat
                context["category"] = recon_cat

            # Determine difficulty and fast-path
            self._state.difficulty = recon_result.deliverable.get(
                "difficulty_estimate", "medium"
            )

        # Check if we already found the flag
        if self._found_flags:
            return self._build_result(success=True)

        # ---- Phase 2: Analysis (skipped on fast path) ----
        fast_path = self._should_fast_path()
        self._state.fast_path = fast_path

        if fast_path:
            self._cb.on_pipeline_phase(
                "analyst", "Skipped (fast path — easy challenge)", is_fast_path=True
            )
        else:
            analyst_result = self._run_analyst(context, flag_pattern)
            self._total_iterations += analyst_result.iterations
            self._collect_flags(analyst_result.flags)

            if analyst_result.success:
                self._state.analyst_deliverable = analyst_result.deliverable
                context["analyst_deliverable"] = analyst_result.deliverable

            # Check if we already found the flag
            if self._found_flags:
                return self._build_result(success=True)

        # ---- Phase 3: Solve ----
        solver_result = self._run_solvers(context, flag_pattern)
        self._total_iterations += solver_result.iterations
        self._collect_flags(solver_result.flags)

        if solver_result.success:
            self._state.solver_deliverable = solver_result.deliverable
            context["solver_deliverable"] = solver_result.deliverable

        # ---- Phase 4: Report ----
        context["flags"] = self._found_flags
        context["answer"] = solver_result.deliverable.get("answer", "")
        reporter_result = self._run_reporter(context, flag_pattern)
        self._total_iterations += reporter_result.iterations

        if reporter_result.success:
            self._state.reporter_deliverable = reporter_result.deliverable
            # Save report markdown
            report_md = reporter_result.deliverable.get("report_markdown", "")
            if report_md and self._state.session_id:
                try:
                    report_path = save_report(report_md, self._state.session_id)
                    self._cb.on_report_saved(str(report_path))
                except Exception as exc:
                    self._log.debug(f"Report save failed: {exc}")

        # Build final result
        success = bool(self._found_flags) or solver_result.success
        return self._build_result(success=success, solver_result=solver_result)

    # ------------------------------------------------------------------
    # Phase runners
    # ------------------------------------------------------------------

    def _run_recon(
        self, context: dict[str, Any], flag_pattern: str | None
    ) -> AgentResult:
        """Run the recon agent."""
        self._cb.on_pipeline_phase("recon", "Starting reconnaissance...")

        agent = ReconAgent(
            config=self._config,
            client=self._client,
            docker_manager=self._docker,
            workspace=self._workspace,
            callbacks=self._cb,
            cost_tracker=self._cost,
            flag_pattern=flag_pattern,
        )
        result = agent.run(context)

        self._save_deliverable("recon", result.deliverable)
        self._record_step("recon", result)
        return result

    def _run_analyst(
        self, context: dict[str, Any], flag_pattern: str | None
    ) -> AgentResult:
        """Run the analyst agent."""
        self._cb.on_pipeline_phase("analyst", "Analyzing challenge...")

        agent = AnalystAgent(
            config=self._config,
            client=self._client,
            docker_manager=self._docker,
            workspace=self._workspace,
            callbacks=self._cb,
            cost_tracker=self._cost,
            flag_pattern=flag_pattern,
        )
        result = agent.run(context)

        self._save_deliverable("analyst", result.deliverable)
        self._record_step("analyst", result)
        return result

    def _run_solvers(
        self, context: dict[str, Any], flag_pattern: str | None
    ) -> AgentResult:
        """Run solver agent(s), potentially in parallel."""
        # Extract hypotheses from analyst deliverable
        hypotheses = self._state.analyst_deliverable.get("hypotheses", [])

        # If no hypotheses or only one, run a single solver
        if len(hypotheses) <= 1:
            return self._run_single_solver(
                context, flag_pattern, hypotheses[0] if hypotheses else None
            )

        # Multiple hypotheses — try parallel solving
        max_parallel = min(
            len(hypotheses),
            self._config.pipeline.max_parallel_solvers,
        )
        return self._run_parallel_solvers(
            context, flag_pattern, hypotheses[:max_parallel]
        )

    def _run_single_solver(
        self,
        context: dict[str, Any],
        flag_pattern: str | None,
        hypothesis: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Run a single solver agent."""
        self._cb.on_pipeline_phase("solve", "Solving challenge...")

        agent = SolverAgent(
            hypothesis=hypothesis,
            config=self._config,
            client=self._client,
            docker_manager=self._docker,
            workspace=self._workspace,
            callbacks=self._cb,
            cost_tracker=self._cost,
            flag_pattern=flag_pattern,
        )
        agent.set_difficulty(self._state.difficulty)
        result = agent.run(context)

        self._save_deliverable("solver", result.deliverable)
        self._record_step("solver", result)
        return result

    def _run_parallel_solvers(
        self,
        context: dict[str, Any],
        flag_pattern: str | None,
        hypotheses: list[dict[str, Any]],
    ) -> AgentResult:
        """Run multiple solver agents in parallel.

        First successful result wins; others are cancelled.
        """
        count = len(hypotheses)
        self._cb.on_parallel_start(count)
        self._cb.on_pipeline_phase("solve", f"Trying {count} approaches in parallel...")

        all_results: list[AgentResult] = []

        with ThreadPoolExecutor(max_workers=count) as pool:
            futures: dict[Future[AgentResult], int] = {}

            for i, hyp in enumerate(hypotheses):
                # Each parallel solver gets its own OpenAI client
                solver = SolverAgent(
                    hypothesis=hyp,
                    config=self._config,
                    client=OpenAI(api_key=self._config.model.api_key),
                    docker_manager=self._docker,
                    workspace=self._workspace,
                    callbacks=self._cb,
                    cost_tracker=self._cost,  # Shared, thread-safe
                    flag_pattern=flag_pattern,
                )
                solver.set_difficulty(self._state.difficulty)
                fut = pool.submit(solver.run, context)
                futures[fut] = i

            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    result = fut.result()
                except Exception as exc:
                    self._log.error(f"Solver #{idx + 1} failed: {exc}")
                    self._cb.on_parallel_result(idx + 1, False, str(exc))
                    continue

                all_results.append(result)
                self._cb.on_parallel_result(idx + 1, result.success, result.summary)

                if result.success:
                    # Cancel remaining futures
                    for other_fut in futures:
                        if other_fut is not fut and not other_fut.done():
                            other_fut.cancel()

                    self._save_deliverable("solver", result.deliverable)
                    self._record_step("solver", result)
                    return result

        # None succeeded — return the best partial result
        if all_results:
            best = max(all_results, key=lambda r: len(r.flags))
            self._save_deliverable("solver", best.deliverable)
            self._record_step("solver", best)
            return best

        return AgentResult(
            success=False,
            summary="All parallel solvers failed.",
        )

    def _run_reporter(
        self, context: dict[str, Any], flag_pattern: str | None
    ) -> AgentResult:
        """Run the reporter agent."""
        self._cb.on_pipeline_phase("report", "Generating report...")

        agent = ReporterAgent(
            config=self._config,
            client=self._client,
            docker_manager=self._docker,
            workspace=self._workspace,
            callbacks=self._cb,
            cost_tracker=self._cost,
            flag_pattern=flag_pattern,
        )
        result = agent.run(context)

        self._save_deliverable("reporter", result.deliverable)
        self._record_step("reporter", result)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_fast_path(self) -> bool:
        """Determine if analyst phase should be skipped."""
        if not self._config.pipeline.fast_path_enabled:
            return False
        return self._state.difficulty == "easy"

    def _collect_flags(self, flags: list[str]) -> None:
        """Add newly found flags to the master list."""
        for f in flags:
            if f not in self._found_flags:
                self._found_flags.append(f)

    def _build_result(
        self,
        success: bool,
        solver_result: AgentResult | None = None,
    ) -> SolveResult:
        """Build the final SolveResult from pipeline state."""
        answer = ""
        confidence = ""
        if solver_result and solver_result.deliverable:
            answer = solver_result.deliverable.get("answer", "")
            confidence = solver_result.deliverable.get("confidence", "")

        return SolveResult(
            success=success,
            flags=self._found_flags,
            answer=answer,
            answer_confidence=confidence,
            iterations=self._total_iterations,
            category=self._state.category,
            intent=self._state.intent,
            summary=answer
            or (f"Flags: {', '.join(self._found_flags)}" if self._found_flags else ""),
            session_id=self._state.session_id,
            cost_usd=self._cost.total_cost,
            total_tokens=self._cost.total_tokens,
        )

    def _save_deliverable(self, agent_role: str, deliverable: dict[str, Any]) -> None:
        """Save a deliverable to the session directory."""
        if not self._state.session_id or not deliverable:
            return

        session_dir = self._config.log.session_dir / self._state.session_id
        deliverable_dir = session_dir / "deliverables"
        deliverable_dir.mkdir(parents=True, exist_ok=True)

        path = deliverable_dir / f"{agent_role}.json"
        try:
            path.write_text(
                json.dumps(deliverable, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            self._log.debug(f"Failed to save deliverable {agent_role}: {exc}")

    def _record_step(self, agent_role: str, result: AgentResult) -> None:
        """Record an agent run as a session step."""
        if self._audit:
            self._audit.log(
                f"agent_{agent_role}_done",
                success=result.success,
                iterations=result.iterations,
                summary=result.summary[:200],
            )

    def _gather_file_info(self, files: list[Path] | None) -> str:
        """Gather type information about challenge files."""
        if not files:
            return ""

        try:
            from utils.file_detector import detect_file_type
        except ImportError:
            return "\n".join(f"- {f.name}" for f in files if f.exists())

        lines: list[str] = []
        for f in files:
            if not f.exists():
                continue
            ftype = detect_file_type(f)
            size = f.stat().st_size
            lines.append(f"- {f.name} ({ftype}, {size} bytes)")
        return "\n".join(lines)
