"""Benchmark runner for evaluating CTF agent performance.

Loads challenge specifications from JSON, runs each through a fresh
Orchestrator instance, evaluates answers, and produces a summary.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from utils.logger import get_logger


class ChallengeSpec(TypedDict, total=False):
    """Schema for a single benchmark challenge entry."""

    id: str
    name: str
    category: str
    description: str
    files: list[str]
    expected_answer: str
    match_type: str  # "exact", "contains", "regex"
    max_steps: int
    max_cost: float


@dataclass
class ChallengeResult:
    """Result of running a single benchmark challenge."""

    id: str
    name: str
    category: str
    passed: bool
    within_budget: bool
    answer: str
    expected: str
    steps: int
    max_steps: int
    cost: float
    duration: float


class BenchmarkRunner:
    """Runs benchmark challenges and evaluates agent performance."""

    def __init__(
        self,
        challenges_file: str | Path,
        budget_override: float | None = None,
        iter_override: int | None = None,
    ) -> None:
        """Initialise the benchmark runner.

        Args:
            challenges_file: Path to the challenges JSON file.
            budget_override: Override max cost per challenge.
            iter_override: Override max iterations per challenge.
        """
        self._challenges_file = Path(challenges_file)
        self._budget_override = budget_override
        self._iter_override = iter_override
        self._log = get_logger()

        with open(self._challenges_file, encoding="utf-8") as fh:
            self._challenges: list[ChallengeSpec] = json.load(fh)

    def run(self, categories: list[str] | None = None) -> list[ChallengeResult]:
        """Run benchmark challenges.

        Args:
            categories: Optional filter — only run challenges in these categories.

        Returns:
            List of ChallengeResult for each challenge run.
        """
        from agent.orchestrator import Orchestrator
        from config import AgentConfig, AppConfig, load_config

        config = load_config()
        results: list[ChallengeResult] = []

        for spec in self._challenges:
            # Category filter
            if categories and spec.get("category", "") not in categories:
                continue

            challenge_id = spec.get("id", "unknown")
            name = spec.get("name", challenge_id)
            category = spec.get("category", "misc")
            description = spec.get("description", "")
            expected = spec.get("expected_answer", "")
            match_type = spec.get("match_type", "exact")
            max_steps = self._iter_override or spec.get("max_steps", 10)
            max_cost = self._budget_override or spec.get("max_cost", 1.0)

            self._log.info(f"Benchmark: running {challenge_id} ({name})")

            # Build config with per-challenge limits
            chall_config = AppConfig(
                model=config.model,
                agent=AgentConfig(
                    max_iterations=max_steps,
                    stall_threshold=config.agent.stall_threshold,
                    context_limit_percent=config.agent.context_limit_percent,
                    tool_output_max_chars=config.agent.tool_output_max_chars,
                    max_cost_per_challenge=max_cost,
                    max_cost_per_turn=config.agent.max_cost_per_turn,
                    max_tokens_per_turn=config.agent.max_tokens_per_turn,
                    max_cost_per_session=config.agent.max_cost_per_session,
                ),
                tool=config.tool,
                docker=config.docker,
                log=config.log,
                pipeline=config.pipeline,
                sandbox_mode=config.sandbox_mode,
            )

            # Fresh orchestrator per challenge
            orch = Orchestrator(config=chall_config, workspace=Path.cwd())

            files = [Path(f) for f in spec.get("files", [])] or None

            start = time.time()
            try:
                solve_result = orch.solve(
                    description=description,
                    files=files,
                    forced_category=category,
                )
            except Exception as exc:
                self._log.error(f"Benchmark {challenge_id} crashed: {exc}")
                solve_result = None

            duration = time.time() - start

            # Extract answer
            if solve_result:
                actual_answer = solve_result.answer or (
                    solve_result.flags[0] if solve_result.flags else ""
                )
                actual_cost = solve_result.cost_usd
                actual_steps = solve_result.iterations
            else:
                actual_answer = ""
                actual_cost = 0.0
                actual_steps = 0

            passed = check_answer(actual_answer, expected, match_type)
            within_budget = actual_cost <= max_cost and actual_steps <= max_steps

            results.append(
                ChallengeResult(
                    id=challenge_id,
                    name=name,
                    category=category,
                    passed=passed,
                    within_budget=within_budget,
                    answer=actual_answer,
                    expected=expected,
                    steps=actual_steps,
                    max_steps=max_steps,
                    cost=actual_cost,
                    duration=duration,
                )
            )

        return results

    def summarize(self, results: list[ChallengeResult]) -> dict[str, Any]:
        """Compute summary statistics and save to disk.

        Args:
            results: List of ChallengeResult from a run.

        Returns:
            Summary dict with totals and per-category breakdown.
        """
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        in_budget = sum(1 for r in results if r.within_budget)
        total_cost = sum(r.cost for r in results)
        total_duration = sum(r.duration for r in results)

        # Per-category breakdown
        cats: dict[str, dict[str, Any]] = {}
        for r in results:
            if r.category not in cats:
                cats[r.category] = {"total": 0, "passed": 0, "cost": 0.0}
            cats[r.category]["total"] += 1
            if r.passed:
                cats[r.category]["passed"] += 1
            cats[r.category]["cost"] += r.cost

        summary = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "total_challenges": total,
            "passed": passed,
            "failed": total - passed,
            "within_budget": in_budget,
            "pass_rate": f"{(passed / total * 100) if total else 0:.1f}%",
            "total_cost_usd": round(total_cost, 4),
            "total_duration_s": round(total_duration, 1),
            "per_category": cats,
            "results": [asdict(r) for r in results],
        }

        # Save results
        results_dir = Path("benchmark/results")
        results_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = results_dir / f"{ts}.json"
        out_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._log.info(f"Benchmark results saved: {out_path}")

        return summary


def check_answer(actual: str, expected: str, match_type: str) -> bool:
    """Evaluate whether the actual answer matches the expected one.

    Args:
        actual: The agent's answer string.
        expected: The expected answer string.
        match_type: One of "exact", "contains", "regex".

    Returns:
        True if the answer matches.
    """
    if not actual or not expected:
        return False

    if match_type == "exact":
        return actual.strip() == expected.strip()
    elif match_type == "contains":
        return expected.strip() in actual.strip()
    elif match_type == "regex":
        return bool(re.search(expected, actual))
    else:
        return actual.strip() == expected.strip()
