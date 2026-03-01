"""Team leader — coordinates multiple teammate agents to solve a CTF challenge."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from agent.orchestrator import AgentCallbacks, NullCallbacks, Orchestrator, SolveResult
from agent.team.callbacks import TeamCallbacks
from agent.team.messages import MessageBus
from agent.team.roles import TEAM_PRESETS, TeammateConfig
from agent.team.taskboard import TaskBoard
from config import AppConfig, load_config
from utils.cost_tracker import CostTracker
from utils.logger import get_logger

_log = get_logger()


class TeamLeader:
    """Orchestrates a team of agents to solve a CTF challenge.

    Lifecycle:
        1. Select teammates based on category (from presets or custom)
        2. Create TaskBoard + MessageBus
        3. Create tasks (phase 1: recon/analysis, phase 2: exploit/solve)
        4. Spawn teammate threads
        5. Monitor progress: flag found, all done, budget, timeout
        6. Collect and synthesize results
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        callbacks: AgentCallbacks | None = None,
        docker_manager: Any = None,
        workspace: Path | None = None,
        hooks_path: str | None = None,
    ) -> None:
        self._config = config or load_config()
        self._cb = callbacks or NullCallbacks()
        self._docker = docker_manager
        self._workspace = workspace or Path.cwd()
        self._hooks_path = hooks_path
        self._cancel_event = threading.Event()
        self._cost = CostTracker(
            budget_limit=self._config.agent.max_cost_per_challenge * 2.0,
        )

    def solve_with_team(
        self,
        description: str,
        category: str,
        files: list[Path] | None = None,
        target_url: str | None = None,
        flag_pattern: str | None = None,
        teammates: list[TeammateConfig] | None = None,
    ) -> SolveResult:
        """Run the full team solve lifecycle."""
        self._cb.on_phase("Team", f"Starting team solve ({category})")

        # 1. Select teammates
        mates = teammates or TEAM_PRESETS.get(category, TEAM_PRESETS.get("misc", []))
        if not mates:
            self._cb.on_error("No team preset for this category. Falling back to single agent.")
            return self._fallback_single(description, files, target_url, flag_pattern)

        mate_names = [m.name for m in mates]
        self._cb.on_phase("Team", f"Teammates: {', '.join(mate_names)}")

        # 2. Create infrastructure
        taskboard = TaskBoard()
        msgbus = MessageBus()
        msgbus.register("lead")
        for m in mates:
            msgbus.register(m.name)

        # 3. Create tasks — phase 1 (recon/analysis) and phase 2 (exploit/solve)
        phase1_tasks = []
        phase2_tasks = []

        for i, mate in enumerate(mates):
            if i == 0:
                # First agent = recon/analysis (no dependencies)
                task = taskboard.create(
                    subject=f"{mate.role}: {description[:80]}",
                    description=(
                        f"Challenge: {description}\n\n"
                        f"Your role: {mate.role}\n"
                        f"Instructions: {mate.prompt}"
                    ),
                    assignee=mate.name,
                )
                phase1_tasks.append(task)
            else:
                # Subsequent agents = exploit/solve (blocked by phase 1)
                task = taskboard.create(
                    subject=f"{mate.role}: exploit/solve",
                    description=(
                        f"Challenge: {description}\n\n"
                        f"Your role: {mate.role}\n"
                        f"Instructions: {mate.prompt}\n\n"
                        "Wait for recon/analysis results before starting."
                    ),
                    blocked_by=[t.id for t in phase1_tasks],
                    assignee=mate.name,
                )
                phase2_tasks.append(task)

        self._cb.on_phase("Team", f"Created {len(phase1_tasks) + len(phase2_tasks)} tasks")

        # 4. Spawn teammate threads
        threads: dict[str, threading.Thread] = {}
        results: dict[str, SolveResult] = {}
        results_lock = threading.Lock()

        for mate in mates:
            t = threading.Thread(
                target=self._run_teammate,
                args=(
                    mate, description, taskboard, msgbus,
                    files, target_url, flag_pattern,
                    results, results_lock,
                ),
                name=f"team-{mate.name}",
                daemon=True,
            )
            threads[mate.name] = t

        # Start all threads
        for t in threads.values():
            t.start()

        # 5. Monitor loop
        result = self._monitor_loop(
            taskboard, msgbus, threads, results, results_lock,
        )

        # 6. Cleanup
        self._cancel_event.set()
        for t in threads.values():
            t.join(timeout=10)

        return result

    def _run_teammate(
        self,
        mate: TeammateConfig,
        description: str,
        taskboard: TaskBoard,
        msgbus: MessageBus,
        files: list[Path] | None,
        target_url: str | None,
        flag_pattern: str | None,
        results: dict[str, SolveResult],
        results_lock: threading.Lock,
    ) -> None:
        """Run a single teammate in its own thread."""
        try:
            # Wait for a task, retry if claim races with another agent
            task = None
            while not self._cancel_event.is_set():
                task = self._wait_for_task(mate.name, taskboard, msgbus)
                if not task:
                    return
                if taskboard.claim(task.id, mate.name):
                    break
                _log.debug(f"[{mate.name}] Claim race on {task.id}, retrying...")
                task = None

            self._cb.on_phase("Team", f"[{mate.name}] Started: {task.subject[:60]}")

            # Collect context from completed tasks (phase 1 results for phase 2 agents)
            prior_results = taskboard.get_completed_results()
            discoveries = msgbus.get_discoveries()

            context_block = ""
            if prior_results:
                context_block += "\n\n--- TEAM FINDINGS ---\n"
                for tid, res in prior_results.items():
                    t = taskboard.get(tid)
                    label = t.subject if t else tid
                    context_block += f"\n[{label}]\n{res}\n"

            if discoveries:
                context_block += "\n\n--- DISCOVERIES ---\n"
                for msg in discoveries[-20:]:
                    context_block += f"[{msg.sender}] {msg.content}\n"

            # Build enriched description
            enriched_desc = (
                f"{description}\n\n"
                f"YOUR ROLE: {mate.role}\n"
                f"{mate.prompt}"
                f"{context_block}"
            )

            # Create orchestrator for this teammate
            callbacks = TeamCallbacks(mate.name, msgbus, taskboard)
            orch = Orchestrator(
                config=self._config,
                docker_manager=self._docker,
                workspace=self._workspace,
                callbacks=callbacks,
                hooks_path=self._hooks_path,
            )
            orch._cancel_event = self._cancel_event

            result = orch.solve(
                description=enriched_desc,
                files=files,
                target_url=target_url,
                flag_pattern=flag_pattern,
            )

            # Store result
            with results_lock:
                results[mate.name] = result

            # Build comprehensive task result for next-phase agents to read
            parts = []
            if result.flags:
                parts.append(f"FLAGS FOUND: {result.flags}")
            if result.answer:
                parts.append(f"Answer: {result.answer}")
            if result.summary:
                parts.append(result.summary)
            task_result = "\n".join(parts) if parts else "No definitive results."
            taskboard.complete(task.id, task_result[:4000])

            self._cb.on_phase("Team", f"[{mate.name}] Done: {'solved' if result.success else 'no flag'}")

        except Exception as exc:
            _log.error(f"[{mate.name}] Error: {exc}")
            msgbus.send(mate.name, "lead", f"Error: {exc}", "info")

    def _wait_for_task(
        self,
        name: str,
        taskboard: TaskBoard,
        msgbus: MessageBus,
        timeout: float | None = None,
    ):
        """Wait until a task is available for this agent."""
        if timeout is None:
            timeout = float(self._config.team.task_timeout)
        start = time.time()
        while not self._cancel_event.is_set():
            available = taskboard.list_available(for_agent=name)
            if available:
                return available[0]

            # Check for shutdown
            msgs = msgbus.receive(name)
            for m in msgs:
                if m.msg_type == "shutdown":
                    return None

            if time.time() - start > timeout:
                return None

            time.sleep(1.0)
        return None

    def _monitor_loop(
        self,
        taskboard: TaskBoard,
        msgbus: MessageBus,
        threads: dict[str, threading.Thread],
        results: dict[str, SolveResult],
        results_lock: threading.Lock,
    ) -> SolveResult:
        """Monitor team progress until flag found or all done."""
        while not self._cancel_event.is_set():
            # Check for flag in messages
            msgs = msgbus.receive("lead")
            for msg in msgs:
                if msg.msg_type == "flag":
                    self._cb.on_flag_found(msg.content)
                    self._cancel_event.set()
                    with results_lock:
                        return self._build_result(results, taskboard, found_flag=msg.content)

                # Log other messages to UI
                elif msg.msg_type == "discovery":
                    self._cb.on_phase("Team", f"[{msg.sender}] {msg.content[:200]}")

            # Check if all tasks done
            if taskboard.all_done():
                self._cb.on_phase("Team", "All tasks completed")
                with results_lock:
                    return self._build_result(results, taskboard)

            # Check if all threads dead
            alive = [t for t in threads.values() if t.is_alive()]
            if not alive:
                with results_lock:
                    return self._build_result(results, taskboard)

            time.sleep(1.0)

        # Cancelled
        with results_lock:
            return self._build_result(results, taskboard)

    def _build_result(
        self,
        results: dict[str, SolveResult],
        taskboard: TaskBoard,
        found_flag: str | None = None,
    ) -> SolveResult:
        """Synthesize results from all teammates into one SolveResult."""
        all_flags = []
        total_cost = 0.0
        total_tokens = 0
        total_iters = 0
        best_answer = ""
        best_confidence = ""
        category = ""

        for name, r in results.items():
            all_flags.extend(r.flags)
            total_cost += r.cost_usd
            total_tokens += r.total_tokens
            total_iters += r.iterations
            if not category and r.category:
                category = r.category
            if r.answer and not best_answer:
                best_answer = r.answer
                best_confidence = r.answer_confidence

        if found_flag and found_flag not in all_flags:
            all_flags.insert(0, found_flag)

        success = bool(all_flags)

        summary_parts = [f"Team solve ({len(results)} agents)"]
        for name, r in results.items():
            status = "solved" if r.success else "no flag"
            summary_parts.append(f"  {name}: {status} ({r.iterations} steps, ${r.cost_usd:.4f})")
        summary_parts.append(f"Tasks:\n{taskboard.summary()}")

        return SolveResult(
            success=success,
            flags=all_flags,
            answer=best_answer,
            answer_confidence=best_confidence,
            iterations=total_iters,
            category=category,
            intent="find_flag",
            summary="\n".join(summary_parts),
            session_id="",
            cost_usd=total_cost,
            total_tokens=total_tokens,
        )

    def _fallback_single(
        self,
        description: str,
        files: list[Path] | None,
        target_url: str | None,
        flag_pattern: str | None,
    ) -> SolveResult:
        """Fall back to single-agent solve."""
        orch = Orchestrator(
            config=self._config,
            docker_manager=self._docker,
            workspace=self._workspace,
            callbacks=self._cb,
            hooks_path=self._hooks_path,
        )
        return orch.solve(
            description=description,
            files=files,
            target_url=target_url,
            flag_pattern=flag_pattern,
        )

    def cancel(self) -> None:
        """Cancel all teammates."""
        self._cancel_event.set()
