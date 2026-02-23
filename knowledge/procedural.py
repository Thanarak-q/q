"""Procedural memory — learns ordered technique chains from past solves."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROCEDURES_PATH = Path(__file__).parent / "procedures.json"
_MAX_PROCEDURES = 100
_MAX_ANTI_PATTERNS = 50


@dataclass
class Procedure:
    """A successful technique chain learned from a solve."""
    trigger_pattern: str
    category: str
    technique_chain: list[str] = field(default_factory=list)
    success_rate: float = 1.0
    times_used: int = 1
    last_updated: str = ""

    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class AntiPattern:
    """A failed approach to avoid."""
    trigger_pattern: str
    category: str
    failed_techniques: list[str] = field(default_factory=list)
    lesson: str = ""


class ProceduralMemory:
    """Learns and retrieves ordered technique chains from past solves."""

    def __init__(self, path: Path | None = None):
        self._path = path or _PROCEDURES_PATH
        self._procedures: list[Procedure] = []
        self._anti_patterns: list[AntiPattern] = []
        self._load()

    # ── persistence ──────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._procedures = [Procedure(**p) for p in data.get("procedures", [])]
            self._anti_patterns = [AntiPattern(**a) for a in data.get("anti_patterns", [])]
        except Exception as e:
            logger.debug("Failed to load procedural memory: %s", e)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "procedures": [asdict(p) for p in self._procedures],
                "anti_patterns": [asdict(a) for a in self._anti_patterns],
            }
            self._path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.debug("Failed to save procedural memory: %s", e)

    # ── recording ────────────────────────────────────────────────

    def record_success(
        self, challenge: str, category: str, steps_log: list[dict[str, Any]]
    ) -> None:
        """Record a successful solve's technique chain."""
        chain = self._extract_ordered_techniques(steps_log)
        if not chain:
            return

        # Merge with existing procedure if >50% technique overlap
        for proc in self._procedures:
            if proc.category == category and self._overlap(proc.technique_chain, chain) > 0.5:
                proc.technique_chain = chain
                proc.times_used += 1
                proc.success_rate = min(1.0, proc.success_rate + 0.05)
                proc.last_updated = datetime.now(timezone.utc).isoformat()
                self._save()
                return

        # New procedure
        self._procedures.append(Procedure(
            trigger_pattern=challenge.lower(),
            category=category,
            technique_chain=chain,
        ))
        self._enforce_limits()
        self._save()

    def record_failure(
        self,
        challenge: str,
        category: str,
        steps_log: list[dict[str, Any]],
        pivot_reasons: list[str] | None = None,
    ) -> None:
        """Record a failed approach as an anti-pattern."""
        chain = self._extract_ordered_techniques(steps_log)
        if not chain:
            return

        lesson = "; ".join(pivot_reasons) if pivot_reasons else "approach failed"
        self._anti_patterns.append(AntiPattern(
            trigger_pattern=challenge.lower(),
            category=category,
            failed_techniques=chain,
            lesson=lesson,
        ))
        self._enforce_limits()
        self._save()

    # ── retrieval ────────────────────────────────────────────────

    def get_suggestions(
        self, challenge: str, category: str, limit: int = 3
    ) -> tuple[list[Procedure], list[AntiPattern]]:
        """Get relevant procedures and anti-patterns for a challenge."""
        challenge_lower = challenge.lower()

        # Score procedures by category match + keyword overlap
        scored_procs = []
        for proc in self._procedures:
            score = 0.0
            if proc.category == category:
                score += 2.0
            # Keyword overlap between trigger and challenge
            trigger_words = set(proc.trigger_pattern.split())
            challenge_words = set(challenge_lower.split())
            overlap = len(trigger_words & challenge_words)
            if trigger_words:
                score += overlap / len(trigger_words)
            score += proc.success_rate * 0.5
            score += min(proc.times_used * 0.1, 0.5)
            if score > 0:
                scored_procs.append((score, proc))

        scored_procs.sort(key=lambda x: x[0], reverse=True)
        top_procs = [p for _, p in scored_procs[:limit]]

        # Filter anti-patterns by category
        anti = [a for a in self._anti_patterns if a.category == category]

        return top_procs, anti[:limit]

    def format_hints(self, challenge: str, category: str) -> str:
        """Format procedural hints as markdown for prompt injection."""
        procs, antis = self.get_suggestions(challenge, category)
        if not procs and not antis:
            return ""

        lines = ["## Procedural Memory (learned from past solves)"]
        if procs:
            lines.append("")
            lines.append("**Successful patterns:**")
            for i, proc in enumerate(procs, 1):
                chain = " → ".join(proc.technique_chain)
                lines.append(f"{i}. [{proc.category}] {chain} (used {proc.times_used}x, {proc.success_rate:.0%} success)")
        if antis:
            lines.append("")
            lines.append("**Avoid these approaches:**")
            for anti in antis:
                failed = ", ".join(anti.failed_techniques)
                lines.append(f"- [{anti.category}] {failed} — {anti.lesson}")

        return "\n".join(lines)

    # ── helpers ───────────────────────────────────────────────────

    def _extract_ordered_techniques(self, steps_log: list[dict[str, Any]]) -> list[str]:
        """Extract ordered technique chain from solve steps."""
        try:
            from knowledge.extractor import _detect_shell_techniques, _detect_python_techniques
        except ImportError:
            return []

        seen = set()
        chain: list[str] = []

        for step in steps_log:
            tool_calls = step.get("tool_calls", [])
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args_str = fn.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                    techniques: set[str] = set()
                    if name == "shell":
                        cmd = args.get("command", "")
                        _detect_shell_techniques(cmd, techniques)
                    elif name == "python_exec":
                        code = args.get("code", "")
                        _detect_python_techniques(code, techniques)
                    elif name in ("browser_action", "browser"):
                        techniques.add("browser automation")
                    elif name in ("network_request", "network"):
                        techniques.add("network request")

                    for t in techniques:
                        if t not in seen:
                            seen.add(t)
                            chain.append(t)
        return chain

    @staticmethod
    def _overlap(chain_a: list[str], chain_b: list[str]) -> float:
        """Calculate Jaccard overlap between two technique chains."""
        set_a, set_b = set(chain_a), set(chain_b)
        if not set_a and not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    def _enforce_limits(self) -> None:
        """Evict lowest-quality entries if over capacity."""
        if len(self._procedures) > _MAX_PROCEDURES:
            self._procedures.sort(key=lambda p: p.success_rate)
            self._procedures = self._procedures[-_MAX_PROCEDURES:]
        if len(self._anti_patterns) > _MAX_ANTI_PATTERNS:
            self._anti_patterns = self._anti_patterns[-_MAX_ANTI_PATTERNS:]
