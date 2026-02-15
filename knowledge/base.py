"""Local knowledge base — stores and retrieves past solve data.

Uses JSON + keyword matching. No vector DB or embeddings required.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class KnowledgeBase:
    """Stores writeups from solved challenges and retrieves similar ones.

    Data is persisted to a single JSON file containing an array of
    knowledge entries.
    """

    def __init__(self, path: str | Path = "knowledge/writeups.json") -> None:
        self.path = Path(path)
        self.entries: list[dict[str, Any]] = self._load()

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
            json.dumps(self.entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(self, entry: dict[str, Any]) -> None:
        """Record a solve result in the knowledge base.

        Args:
            entry: Dict with keys like challenge, category, techniques,
                   commands, answer, flag, steps, cost, success.
        """
        entry["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
        self.entries.append(entry)
        self._save()

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Find similar past solves using keyword matching.

        Args:
            query: Free-text query string.
            category: Optional category filter.
            limit: Max results to return.

        Returns:
            List of matching knowledge entries, best first.
        """
        query_words = set(query.lower().split())
        scored: list[tuple[int, dict[str, Any]]] = []

        for entry in self.entries:
            if not entry.get("success"):
                continue
            if category and entry.get("category") != category:
                continue

            entry_text = " ".join([
                entry.get("challenge", ""),
                " ".join(entry.get("techniques", [])),
                " ".join(entry.get("file_types", [])),
                entry.get("category", ""),
            ]).lower()

            overlap = len(query_words & set(entry_text.split()))
            if overlap > 0:
                scored.append((overlap, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def get_stats(self) -> dict[str, Any]:
        """Compute summary statistics from the knowledge base.

        Returns:
            Dict with total, success count, category breakdown,
            and top tools used.
        """
        total = len(self.entries)
        success = sum(1 for e in self.entries if e.get("success"))
        categories = Counter(e.get("category") for e in self.entries)
        tools = Counter(
            t for e in self.entries for t in e.get("tools_used", [])
        )
        techniques = Counter(
            t for e in self.entries for t in e.get("techniques", [])
        )
        return {
            "total": total,
            "success": success,
            "by_category": dict(categories),
            "top_tools": dict(tools.most_common(10)),
            "top_techniques": dict(techniques.most_common(10)),
        }

    def clear(self) -> None:
        """Remove all entries."""
        self.entries = []
        self._save()

    def export(self, path: str | Path = "knowledge/export.json") -> Path:
        """Export knowledge base to a file.

        Args:
            path: Output file path.

        Returns:
            Path to the exported file.
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(self.entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return out
