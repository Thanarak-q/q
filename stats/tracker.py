"""Performance stats tracker — records and summarizes solve history.

Persists all solve attempts to a JSON file and provides dashboard
data including overall stats, per-category breakdown, trends,
and win streaks.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class StatsTracker:
    """Track Q's performance over time."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path.home() / ".q" / "stats" / "history.json"
        self.history: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.history, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def record(self, session: dict[str, Any]) -> None:
        """Record a solve attempt.

        Args:
            session: Dict with keys: session_id, challenge, category,
                     intent, success, steps, tokens, cost, duration, model.
        """
        session["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
        self.history.append(session)
        self._save()

    def get_dashboard(self) -> dict[str, Any]:
        """Generate dashboard data for display.

        Returns:
            Dict with overall stats, per-category breakdown,
            recent trends, and streak info.
        """
        if not self.history:
            return {"message": "No history yet. Solve some challenges!"}

        total = len(self.history)
        success = sum(1 for h in self.history if h.get("success"))

        # Per-category stats
        cat_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "success": 0, "steps": [], "costs": []}
        )
        for h in self.history:
            cat = h.get("category", "unknown")
            cat_data[cat]["total"] += 1
            if h.get("success"):
                cat_data[cat]["success"] += 1
            cat_data[cat]["steps"].append(h.get("steps", 0))
            cat_data[cat]["costs"].append(h.get("cost", 0))

        categories: dict[str, dict[str, str]] = {}
        for cat, data in sorted(cat_data.items()):
            steps = data["steps"]
            costs = data["costs"]
            categories[cat] = {
                "solved": f"{data['success']}/{data['total']}",
                "rate": f"{data['success'] / data['total'] * 100:.0f}%",
                "avg_steps": f"{sum(steps) / len(steps):.1f}",
                "avg_cost": f"${sum(costs) / len(costs):.3f}",
            }

        # Recent 7-day trend
        week_ago = (datetime.now(tz=timezone.utc) - timedelta(days=7)).isoformat()
        recent = [h for h in self.history if h.get("timestamp", "") > week_ago]

        # Totals
        total_cost = sum(h.get("cost", 0) for h in self.history)
        total_tokens = sum(h.get("tokens", 0) for h in self.history)
        avg_cost = total_cost / total if total else 0

        return {
            "overall": {
                "total": total,
                "success": success,
                "rate": f"{success / total * 100:.0f}%",
                "total_cost": f"${total_cost:.2f}",
                "avg_cost": f"${avg_cost:.3f}",
                "total_tokens": f"{total_tokens:,}",
            },
            "categories": categories,
            "recent_7d": {
                "solves": len(recent),
                "success": sum(1 for r in recent if r.get("success")),
            },
            "streaks": self._get_streaks(),
        }

    def get_summary_line(self) -> str | None:
        """Return a short one-line summary for the welcome screen.

        Returns:
            Summary string like "12 solved - 83% rate - 5 streak",
            or None if no history.
        """
        if not self.history:
            return None

        total = len(self.history)
        success = sum(1 for h in self.history if h.get("success"))
        rate = success / total * 100 if total else 0
        streaks = self._get_streaks()

        parts = [f"{success} solved", f"{rate:.0f}% rate"]
        if streaks["current"] > 0:
            parts.append(f"{streaks['current']} streak")
        return " - ".join(parts)

    def _get_streaks(self) -> dict[str, int]:
        """Calculate current and best win streaks.

        Returns:
            Dict with 'current' and 'best' streak counts.
        """
        if not self.history:
            return {"current": 0, "best": 0}

        best = 0
        streak = 0

        for h in self.history:
            if h.get("success"):
                streak += 1
                best = max(best, streak)
            else:
                streak = 0

        # Current streak = streak from the end
        current = 0
        for h in reversed(self.history):
            if h.get("success"):
                current += 1
            else:
                break

        return {"current": current, "best": best}
