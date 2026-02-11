"""Cost tracking for API usage.

Tracks prompt and completion tokens per API call, computes running
cost estimates, and warns when approaching budget limits.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from config import MODEL_PRICING
from utils.logger import get_logger


@dataclass
class APICallRecord:
    """Record of a single API call."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    iteration: int


@dataclass
class CostTracker:
    """Accumulates token usage and cost across all API calls in a session.

    Provides real-time cost estimates, per-model breakdowns, and budget
    limit checking.
    """

    budget_limit: float = 0.0
    records: list[APICallRecord] = field(default_factory=list)
    _total_prompt: int = 0
    _total_completion: int = 0
    _total_cost: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def record(
        self,
        model: str,
        usage: Any,
        iteration: int = 0,
    ) -> APICallRecord:
        """Record token usage from an API response.

        Thread-safe for parallel solver execution.

        Args:
            model: Model identifier that was called.
            usage: The ``usage`` object from the OpenAI response
                   (has ``prompt_tokens`` and ``completion_tokens``).
            iteration: Current agent iteration number.

        Returns:
            The created APICallRecord.
        """
        prompt_tok = getattr(usage, "prompt_tokens", 0) or 0
        compl_tok = getattr(usage, "completion_tokens", 0) or 0
        cost = self._calc_cost(model, prompt_tok, compl_tok)

        rec = APICallRecord(
            model=model,
            prompt_tokens=prompt_tok,
            completion_tokens=compl_tok,
            cost_usd=cost,
            iteration=iteration,
        )

        with self._lock:
            self.records.append(rec)
            self._total_prompt += prompt_tok
            self._total_completion += compl_tok
            self._total_cost += cost

        return rec

    @property
    def total_prompt_tokens(self) -> int:
        """Total prompt tokens used across all calls."""
        return self._total_prompt

    @property
    def total_completion_tokens(self) -> int:
        """Total completion tokens used across all calls."""
        return self._total_completion

    @property
    def total_tokens(self) -> int:
        """Total tokens (prompt + completion)."""
        return self._total_prompt + self._total_completion

    @property
    def total_cost(self) -> float:
        """Total estimated cost in USD."""
        return self._total_cost

    @property
    def call_count(self) -> int:
        """Number of API calls recorded."""
        return len(self.records)

    def is_over_budget(self) -> bool:
        """Check whether cost has exceeded the budget limit.

        Returns:
            True if budget_limit > 0 and total_cost >= budget_limit.
        """
        if self.budget_limit <= 0:
            return False
        return self._total_cost >= self.budget_limit

    def budget_warning(self) -> str | None:
        """Return a warning string if approaching or over budget.

        Returns:
            Warning message, or None if within budget.
        """
        if self.budget_limit <= 0:
            return None
        pct = (self._total_cost / self.budget_limit) * 100
        if pct >= 100:
            return (
                f"BUDGET EXCEEDED: ${self._total_cost:.4f} / "
                f"${self.budget_limit:.2f} ({pct:.0f}%)"
            )
        if pct >= 80:
            return (
                f"Budget warning: ${self._total_cost:.4f} / "
                f"${self.budget_limit:.2f} ({pct:.0f}%)"
            )
        return None

    def per_model_summary(self) -> dict[str, dict[str, Any]]:
        """Break down usage by model.

        Returns:
            Dict mapping model name to {calls, prompt_tokens,
            completion_tokens, cost_usd}.
        """
        summary: dict[str, dict[str, Any]] = {}
        for rec in self.records:
            if rec.model not in summary:
                summary[rec.model] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                }
            s = summary[rec.model]
            s["calls"] += 1
            s["prompt_tokens"] += rec.prompt_tokens
            s["completion_tokens"] += rec.completion_tokens
            s["cost_usd"] += rec.cost_usd
        return summary

    def to_dict(self) -> dict[str, Any]:
        """Serialise tracker state to a dict (for session saving).

        Returns:
            Dict with total stats and per-call records.
        """
        return {
            "total_prompt_tokens": self._total_prompt,
            "total_completion_tokens": self._total_completion,
            "total_cost_usd": round(self._total_cost, 6),
            "call_count": self.call_count,
            "budget_limit": self.budget_limit,
            "per_model": self.per_model_summary(),
            "records": [
                {
                    "model": r.model,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "cost_usd": round(r.cost_usd, 6),
                    "iteration": r.iteration,
                }
                for r in self.records
            ],
        }

    @staticmethod
    def _calc_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate the cost of an API call.

        Args:
            model: Model identifier.
            prompt_tokens: Number of input tokens.
            completion_tokens: Number of output tokens.

        Returns:
            Estimated cost in USD.
        """
        pricing = MODEL_PRICING.get(model, {"input": 2.50, "output": 10.00})
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost
