"""Flag discriminator agent — validates candidate flags before submission.

Inspired by CAI framework's segregation of duties: the exploitation agent
finds a candidate flag, then a separate discriminator agent validates it
before the team declares victory.

Uses a cheap model to:
1. Check format against known patterns
2. Detect false positives (placeholders, regex patterns, code snippets)
3. Apply contextual validation (does this flag make sense for the challenge?)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from utils.flag_extractor import (
    DEFAULT_FLAG_PATTERNS,
    _is_regex_pattern,
    _validate_flag,
)
from utils.logger import get_logger


@dataclass
class FlagVerdict:
    """Result of flag discrimination."""

    flag: str
    is_valid: bool
    confidence: str  # high, medium, low
    reason: str


class FlagDiscriminator:
    """Validates candidate flags using heuristics and optional LLM verification.

    Two-tier validation:
    1. Fast path: regex + heuristic checks (no LLM call)
    2. Slow path: LLM-based contextual validation (optional)
    """

    def __init__(
        self,
        provider: Any = None,
        config: Any = None,
        custom_pattern: str | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._custom_pattern = custom_pattern
        self._log = get_logger()
        self._seen_flags: set[str] = set()
        self._verdicts: list[FlagVerdict] = []

    def validate(
        self,
        candidate: str,
        context: str = "",
        challenge_description: str = "",
    ) -> FlagVerdict:
        """Validate a candidate flag.

        Args:
            candidate: The candidate flag string.
            context: The surrounding text where the flag was found.
            challenge_description: The challenge description for contextual validation.

        Returns:
            FlagVerdict with validation result.
        """
        candidate = candidate.strip()

        # Dedup
        if candidate in self._seen_flags:
            verdict = FlagVerdict(
                flag=candidate,
                is_valid=True,
                confidence="high",
                reason="Already validated in this session.",
            )
            return verdict

        # Fast path: heuristic checks
        verdict = self._heuristic_check(candidate, context)
        if verdict.confidence == "high":
            self._record(verdict)
            return verdict

        # Slow path: LLM verification (if provider available and confidence is low)
        if self._provider and self._config and verdict.confidence == "low":
            llm_verdict = self._llm_verify(candidate, context, challenge_description)
            if llm_verdict is not None:
                self._record(llm_verdict)
                return llm_verdict

        self._record(verdict)
        return verdict

    def _heuristic_check(self, candidate: str, context: str) -> FlagVerdict:
        """Fast heuristic validation without LLM calls."""
        # Check 1: Does it match any known flag pattern?
        matches_pattern = False
        patterns = list(DEFAULT_FLAG_PATTERNS)
        if self._custom_pattern:
            patterns.insert(0, self._custom_pattern)

        for pattern in patterns:
            try:
                if re.fullmatch(pattern, candidate):
                    matches_pattern = True
                    break
            except re.error:
                continue

        if not matches_pattern:
            # Check if it at least has the flag{...} structure
            if not re.match(r"^[a-zA-Z0-9_]+\{.+\}$", candidate):
                return FlagVerdict(
                    flag=candidate,
                    is_valid=False,
                    confidence="high",
                    reason="Does not match any known flag format (prefix{content}).",
                )

        # Check 2: Extract content and validate
        brace_match = re.search(r"\{(.+)\}", candidate)
        if not brace_match:
            return FlagVerdict(
                flag=candidate,
                is_valid=False,
                confidence="high",
                reason="No braces found in flag.",
            )

        content = brace_match.group(1)

        # Check 3: Reject regex patterns
        if _is_regex_pattern(content):
            return FlagVerdict(
                flag=candidate,
                is_valid=False,
                confidence="high",
                reason=f"Flag content contains regex metacharacters: {content[:50]}",
            )

        # Check 4: Reject placeholders
        placeholders = {
            "...", "xxx", "???", "flag", "here",
            "placeholder", "your_flag_here", "insert_flag",
            "example", "test", "todo",
        }
        if content.lower().strip() in placeholders:
            return FlagVerdict(
                flag=candidate,
                is_valid=False,
                confidence="high",
                reason=f"Flag content is a placeholder: {content}",
            )

        # Check 5: Too short
        if len(content) < 3:
            return FlagVerdict(
                flag=candidate,
                is_valid=False,
                confidence="medium",
                reason=f"Flag content too short ({len(content)} chars).",
            )

        # Check 6: Validate against full text context
        if context:
            status = _validate_flag(candidate, context, context.find(candidate))
            if status == "rejected":
                return FlagVerdict(
                    flag=candidate,
                    is_valid=False,
                    confidence="high",
                    reason="Flag appears to be in code context (regex, string literal).",
                )

        # Passed all checks
        return FlagVerdict(
            flag=candidate,
            is_valid=True,
            confidence="high" if matches_pattern else "medium",
            reason="Matches known flag pattern." if matches_pattern else "Has flag structure but unknown prefix.",
        )

    def _llm_verify(
        self,
        candidate: str,
        context: str,
        challenge_description: str,
    ) -> FlagVerdict | None:
        """Use a cheap LLM to verify a flag contextually."""
        try:
            model = self._config.model.fast_model
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a CTF flag validator. Given a candidate flag and "
                        "context, determine if it's a real flag or a false positive. "
                        "Respond with ONLY 'VALID' or 'INVALID: <reason>'."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Candidate flag: {candidate}\n"
                        f"Challenge: {challenge_description[:200]}\n"
                        f"Context: {context[:500]}\n\n"
                        f"Is this a real CTF flag or a false positive?"
                    ),
                },
            ]
            result = self._provider.chat(
                model=model,
                messages=messages,
                temperature=0.0,
                max_tokens=100,
            )
            response = result["message"].get("content", "").strip()

            if response.startswith("VALID"):
                return FlagVerdict(
                    flag=candidate,
                    is_valid=True,
                    confidence="high",
                    reason="LLM validation: confirmed as real flag.",
                )
            elif response.startswith("INVALID"):
                reason = response.replace("INVALID:", "").strip() or "LLM rejected"
                return FlagVerdict(
                    flag=candidate,
                    is_valid=False,
                    confidence="medium",
                    reason=f"LLM validation: {reason}",
                )
        except Exception as exc:
            self._log.debug(f"LLM flag verification failed: {exc}")

        return None

    def _record(self, verdict: FlagVerdict) -> None:
        """Record a verdict."""
        if verdict.is_valid:
            self._seen_flags.add(verdict.flag)
        self._verdicts.append(verdict)
        self._log.debug(
            f"Flag discriminator: {verdict.flag} -> "
            f"{'VALID' if verdict.is_valid else 'INVALID'} "
            f"({verdict.confidence}): {verdict.reason}"
        )

    @property
    def verdicts(self) -> list[FlagVerdict]:
        """All verdicts from this session."""
        return list(self._verdicts)

    def summary(self) -> str:
        """Human-readable summary of all verdicts."""
        if not self._verdicts:
            return "No flags evaluated."
        lines = []
        for v in self._verdicts:
            icon = "+" if v.is_valid else "x"
            lines.append(f"  [{icon}] {v.flag} ({v.confidence}): {v.reason}")
        return "\n".join(lines)
