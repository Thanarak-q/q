"""Team persistence — create, track, and delete teams."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from agent.team.roles import TeammateConfig


class TeamManager:
    """Persist team metadata to ~/.q/teams/."""

    def __init__(self, teams_dir: Path | None = None) -> None:
        self._dir = teams_dir or (Path.home() / ".q" / "teams")
        self._dir.mkdir(parents=True, exist_ok=True)

    def create_team(
        self,
        challenge: str,
        category: str,
        teammates: list[TeammateConfig],
        budget: float = 4.0,
    ) -> str:
        """Create and persist a new team. Returns team_id."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        team_id = f"{ts}_{uuid.uuid4().hex[:6]}"
        data = {
            "team_id": team_id,
            "challenge": challenge[:200],
            "category": category,
            "teammates": [asdict(m) for m in teammates],
            "budget": budget,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self._dir / f"{team_id}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return team_id

    def get_team(self, team_id: str) -> dict | None:
        path = self._dir / f"{team_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_teams(self) -> list[dict]:
        teams = []
        for f in sorted(self._dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                teams.append({
                    "team_id": data.get("team_id", f.stem),
                    "challenge": data.get("challenge", "")[:60],
                    "category": data.get("category", ""),
                    "status": data.get("status", ""),
                    "teammates": len(data.get("teammates", [])),
                    "created_at": data.get("created_at", "")[:19],
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return teams

    def update_status(self, team_id: str, status: str) -> None:
        path = self._dir / f"{team_id}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = status
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def delete_team(self, team_id: str) -> bool:
        path = self._dir / f"{team_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
