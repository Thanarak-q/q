"""Team leader — reactive coordinator for multi-agent CTF solving.

Replaces the rigid 2-phase pipeline with a dynamic leader-teammate pattern:
- Leader creates a task DAG with dependencies
- Spawns autonomous teammates that claim/complete tasks independently
- Reacts to events (discoveries, flags, new tasks, idle) dynamically
- Graceful shutdown protocol when done
"""

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
    """Reactive coordinator for a team of CTF-solving agents.

    Lifecycle:
        1. Create initial task DAG from presets (with dependency edges)
        2. Spawn teammates for unblocked tasks
        3. Reactive monitor loop — react to messages/events
        4. Graceful shutdown when flag found or all tasks done
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

        # Shared infrastructure — persisted for UI access
        self._taskboard: TaskBoard | None = None
        self._msgbus: MessageBus | None = None

        # Active teammate tracking
        self._threads: dict[str, threading.Thread] = {}
        self._mate_configs: dict[str, TeammateConfig] = {}
        self._results: dict[str, SolveResult] = {}
        self._results_lock = threading.Lock()

    def solve_with_team(
        self,
        description: str,
        category: str,
        files: list[Path] | None = None,
        target_url: str | None = None,
        flag_pattern: str | None = None,
        teammates: list[TeammateConfig] | None = None,
    ) -> SolveResult:
        """Run the full reactive team solve lifecycle."""
        self._cb.on_phase("Team", f"Starting team solve ({category})")

        # 1. Select teammates
        mates = teammates or TEAM_PRESETS.get(category, TEAM_PRESETS.get("misc", []))
        if not mates:
            self._cb.on_error("No team preset for this category. Falling back to single agent.")
            return self._fallback_single(description, files, target_url, flag_pattern)

        mate_names = [m.name for m in mates]
        self._cb.on_phase("Team", f"Teammates: {', '.join(mate_names)}")

        # Store configs for dynamic spawning
        for m in mates:
            self._mate_configs[m.name] = m

        # 2. Create infrastructure
        self._taskboard = TaskBoard()
        self._msgbus = MessageBus()
        self._msgbus.register("lead")
        for m in mates:
            self._msgbus.register(m.name)

        # 3. Create initial task DAG
        self._create_initial_tasks(description, category, mates)

        # 4. Spawn teammates for unblocked tasks
        self._spawn_initial_teammates(
            mates, description, files, target_url, flag_pattern,
        )

        # 5. Reactive monitor loop
        result = self._reactive_monitor_loop()

        # 6. Cleanup
        self._shutdown_all_teammates()
        self._cancel_event.set()
        for t in self._threads.values():
            t.join(timeout=10)

        return result

    # ── Task DAG Creation ──────────────────────────────────────────

    def _create_initial_tasks(
        self,
        description: str,
        category: str,
        mates: list[TeammateConfig],
    ) -> None:
        """Build initial task DAG from presets.

        Creates tasks with proper dependency edges instead of rigid phases.
        First mate(s) get unblocked tasks; later mates get tasks blocked
        by the earlier ones.
        """
        tb = self._taskboard
        assert tb is not None

        if len(mates) == 1:
            # Single teammate — one task, no dependencies
            tb.create(
                subject=f"{mates[0].role}: {description[:80]}",
                description=(
                    f"Challenge: {description}\n\n"
                    f"Your role: {mates[0].role}\n"
                    f"Instructions: {mates[0].prompt}"
                ),
                assignee=mates[0].name,
                metadata={"phase": "solo"},
            )
            return

        # Multi-teammate: create recon tasks (unblocked) and exploit tasks (blocked)
        recon_task_ids = []

        for i, mate in enumerate(mates):
            if i < len(mates) - 1:
                # Recon/analysis task — no blockers
                task = tb.create(
                    subject=f"{mate.role}: {description[:80]}",
                    description=(
                        f"Challenge: {description}\n\n"
                        f"Your role: {mate.role}\n"
                        f"Instructions: {mate.prompt}\n\n"
                        "Report ALL findings clearly for the team."
                    ),
                    assignee=mate.name,
                    metadata={"phase": "recon"},
                )
                recon_task_ids.append(task.id)
            else:
                # Final agent — exploit/solve, blocked by all recon tasks
                tb.create(
                    subject=f"{mate.role}: exploit/solve",
                    description=(
                        f"Challenge: {description}\n\n"
                        f"Your role: {mate.role}\n"
                        f"Instructions: {mate.prompt}\n\n"
                        "Use findings from completed recon tasks to solve."
                    ),
                    assignee=mate.name,
                    blocked_by=recon_task_ids,
                    metadata={"phase": "exploit"},
                )

        task_count = len(tb.list_all())
        self._cb.on_phase("Team", f"Created {task_count} tasks")

    # ── Teammate Spawning ──────────────────────────────────────────

    def _spawn_initial_teammates(
        self,
        mates: list[TeammateConfig],
        description: str,
        files: list[Path] | None,
        target_url: str | None,
        flag_pattern: str | None,
    ) -> None:
        """Spawn threads for all teammates. Each runs the autonomous loop."""
        for mate in mates:
            self._spawn_teammate(mate, description, files, target_url, flag_pattern)

        # Start all threads
        for t in self._threads.values():
            t.start()

    def _spawn_teammate(
        self,
        mate: TeammateConfig,
        description: str,
        files: list[Path] | None = None,
        target_url: str | None = None,
        flag_pattern: str | None = None,
    ) -> None:
        """Spawn a single teammate thread. Can be called mid-solve."""
        if mate.name in self._threads and self._threads[mate.name].is_alive():
            _log.debug(f"[lead] Teammate {mate.name} already running")
            return

        # Per-teammate workspace isolation
        mate_workspace = self._workspace / f"team_{mate.name}"
        mate_workspace.mkdir(parents=True, exist_ok=True)

        # Symlink challenge files into teammate workspace
        if files:
            for f in files:
                dest = mate_workspace / f.name
                if not dest.exists():
                    try:
                        dest.symlink_to(f.resolve())
                    except OSError:
                        import shutil
                        shutil.copy2(f, dest)

        t = threading.Thread(
            target=self._teammate_loop,
            args=(mate, description, files, target_url, flag_pattern, mate_workspace),
            name=f"team-{mate.name}",
            daemon=True,
        )
        self._threads[mate.name] = t
        self._mate_configs[mate.name] = mate

    # ── Autonomous Teammate Loop ───────────────────────────────────

    def _teammate_loop(
        self,
        mate: TeammateConfig,
        description: str,
        files: list[Path] | None,
        target_url: str | None,
        flag_pattern: str | None,
        workspace: Path | None = None,
    ) -> None:
        """Autonomous teammate loop — claim tasks, solve, repeat."""
        tb = self._taskboard
        mb = self._msgbus
        assert tb is not None and mb is not None

        try:
            while not self._cancel_event.is_set():
                # Check messages first (shutdown? instructions?)
                msgs = mb.receive(mate.name)
                should_stop = False
                for msg in msgs:
                    if msg.msg_type == "shutdown_request":
                        mb.send_shutdown_response(
                            mate.name, "lead", msg.request_id, approved=True,
                        )
                        should_stop = True
                        break
                    elif msg.msg_type == "instruction":
                        _log.debug(f"[{mate.name}] Instruction: {msg.content[:100]}")

                if should_stop:
                    return

                # Try to claim next available task
                task = self._claim_next_task(mate.name, tb)
                if task is None:
                    # No task available — notify leader and wait
                    mb.send(mate.name, "lead", "No available tasks", "idle")
                    # Wait for tasks to unblock or shutdown
                    if not self._wait_for_work(mate.name, tb, mb):
                        return  # shutdown or timeout
                    continue

                self._cb.on_phase("Team", f"[{mate.name}] Started: {task.subject[:60]}")

                # Build enriched context from completed tasks + discoveries
                enriched_desc = self._build_enriched_description(
                    mate, description, tb, mb,
                )

                # Create orchestrator and solve
                callbacks = TeamCallbacks(mate.name, mb, tb)
                mate_ws = workspace or self._workspace
                orch = Orchestrator(
                    config=self._config,
                    docker_manager=self._docker,
                    workspace=mate_ws,
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
                with self._results_lock:
                    self._results[mate.name] = result

                # Complete task on board
                task_result = self._format_task_result(result)
                tb.complete(task.id, task_result[:4000])

                self._cb.on_phase(
                    "Team",
                    f"[{mate.name}] Done: {'solved' if result.success else 'no flag'}",
                )

                # If flag found, we're done — loop will exit via cancel_event
                if result.flags:
                    break

                # Otherwise loop back to claim next task

        except Exception as exc:
            _log.error(f"[{mate.name}] Error: {exc}")
            mb.send(mate.name, "lead", f"Error: {exc}", "info")

    def _claim_next_task(self, name: str, tb: TaskBoard):
        """Try to claim the next available task for this agent."""
        available = tb.list_available(for_agent=name)
        if not available:
            # Also check tasks not assigned to anyone specific
            available = tb.list_available(for_agent="")
            available = [t for t in available if not t.assignee]

        for task in available:
            if tb.claim(task.id, name):
                return task
        return None

    def _wait_for_work(
        self,
        name: str,
        tb: TaskBoard,
        mb: MessageBus,
        timeout: float | None = None,
    ) -> bool:
        """Wait for tasks to become available. Returns False if should stop."""
        if timeout is None:
            timeout = float(self._config.team.task_timeout)
        start = time.time()

        while not self._cancel_event.is_set():
            # Check for available tasks
            available = tb.list_available(for_agent=name)
            if not available:
                available = [t for t in tb.list_available() if not t.assignee]
            if available:
                return True

            # Check for messages (shutdown, etc.)
            msgs = mb.receive(name)
            for msg in msgs:
                if msg.msg_type in ("shutdown_request", "shutdown"):
                    if msg.request_id:
                        mb.send_shutdown_response(
                            name, "lead", msg.request_id, approved=True,
                        )
                    return False

            # Check if all tasks are done (nothing left to do)
            if tb.all_done():
                return False

            if time.time() - start > timeout:
                return False

            time.sleep(1.0)

        return False

    def _build_enriched_description(
        self,
        mate: TeammateConfig,
        description: str,
        tb: TaskBoard,
        mb: MessageBus,
    ) -> str:
        """Build context-rich description from completed tasks + discoveries."""
        prior_results = tb.get_completed_results()
        discoveries = mb.get_discoveries()

        context_block = ""
        if prior_results:
            context_block += "\n\n--- TEAM FINDINGS ---\n"
            for tid, res in prior_results.items():
                t = tb.get(tid)
                label = t.subject if t else tid
                context_block += f"\n[{label}]\n{res}\n"

        if discoveries:
            context_block += "\n\n--- DISCOVERIES ---\n"
            for msg in discoveries[-20:]:
                context_block += f"[{msg.sender}] {msg.content}\n"

        return (
            f"{description}\n\n"
            f"YOUR ROLE: {mate.role}\n"
            f"{mate.prompt}"
            f"{context_block}"
        )

    def _format_task_result(self, result: SolveResult) -> str:
        """Format a SolveResult into a string for the task board."""
        parts = []
        if result.flags:
            parts.append(f"FLAGS FOUND: {result.flags}")
        if result.answer:
            parts.append(f"Answer: {result.answer}")
        if result.summary:
            parts.append(result.summary)
        return "\n".join(parts) if parts else "No definitive results."

    # ── Reactive Monitor Loop ──────────────────────────────────────

    def _reactive_monitor_loop(self) -> SolveResult:
        """Event-driven loop reacting to messages from teammates."""
        tb = self._taskboard
        mb = self._msgbus
        assert tb is not None and mb is not None

        while not self._cancel_event.is_set():
            # Process leader's messages
            msgs = mb.receive("lead")
            for msg in msgs:
                if msg.msg_type == "flag":
                    self._cb.on_flag_found(msg.content)
                    self._cancel_event.set()
                    with self._results_lock:
                        return self._build_result(found_flag=msg.content)

                elif msg.msg_type == "discovery":
                    self._cb.on_phase("Team", f"[{msg.sender}] {msg.content[:200]}")

                elif msg.msg_type == "task_created":
                    self._cb.on_phase("Team", f"[{msg.sender}] New task: {msg.content[:100]}")

                elif msg.msg_type == "idle":
                    _log.debug(f"[lead] {msg.sender} is idle")

                elif msg.msg_type == "shutdown_response":
                    _log.debug(f"[lead] {msg.sender} shutdown: {msg.content}")

            # Check if all tasks done
            if tb.all_done():
                self._cb.on_phase("Team", "All tasks completed")
                with self._results_lock:
                    return self._build_result()

            # Deadlock detection — break circular dependencies
            cycles = tb.detect_deadlocks()
            for cycle in cycles:
                cycle_str = " -> ".join(cycle)
                _log.warning(f"[lead] Deadlock detected: {cycle_str}")
                self._cb.on_phase("Team", f"Breaking deadlock: {cycle_str}")
                tb.break_deadlock(cycle)

            # Check if all threads dead
            alive = [t for t in self._threads.values() if t.is_alive()]
            if not alive:
                with self._results_lock:
                    return self._build_result()

            time.sleep(1.0)

        # Cancelled
        with self._results_lock:
            return self._build_result()

    # ── Shutdown Protocol ──────────────────────────────────────────

    def _shutdown_all_teammates(self) -> None:
        """Graceful shutdown — send shutdown_request to all active teammates."""
        mb = self._msgbus
        if mb is None:
            return

        for name, thread in self._threads.items():
            if thread.is_alive():
                mb.send_shutdown_request("lead", name, "Team solve complete")

        # Give teammates a moment to acknowledge
        deadline = time.time() + 5.0
        while time.time() < deadline:
            alive = [t for t in self._threads.values() if t.is_alive()]
            if not alive:
                break
            time.sleep(0.5)

    # ── Result Synthesis ───────────────────────────────────────────

    def _build_result(self, found_flag: str | None = None) -> SolveResult:
        """Synthesize results from all teammates into one SolveResult."""
        tb = self._taskboard
        all_flags = []
        total_cost = 0.0
        total_tokens = 0
        total_iters = 0
        best_answer = ""
        best_confidence = ""
        category = ""

        for name, r in self._results.items():
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

        summary_parts = [f"Team solve ({len(self._results)} agents)"]
        for name, r in self._results.items():
            status = "solved" if r.success else "no flag"
            summary_parts.append(f"  {name}: {status} ({r.iterations} steps, ${r.cost_usd:.4f})")
        if tb:
            summary_parts.append(f"Tasks:\n{tb.summary()}")

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

    # ── Public Accessors ───────────────────────────────────────────

    def get_active_teammates(self) -> list[dict]:
        """Return status info for all teammates."""
        tb = self._taskboard
        result = []
        for name, thread in self._threads.items():
            mate = self._mate_configs.get(name)
            status = "running" if thread.is_alive() else "done"

            # Find current task
            current_task = ""
            if tb:
                for t in tb.list_all():
                    if t.owner == name and t.status == "in_progress":
                        current_task = t.subject[:50]
                        break

            if thread.is_alive() and not current_task:
                status = "idle"

            result.append({
                "name": name,
                "role": mate.role if mate else "?",
                "status": status,
                "task": current_task or "-",
            })
        return result

    def cancel(self) -> None:
        """Cancel all teammates."""
        self._cancel_event.set()
