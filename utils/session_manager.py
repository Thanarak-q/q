"""Session persistence — save, load, list, and export sessions.

Each session captures the full state of a solve attempt so it can be
resumed, replayed, or exported as a writeup.  Writes are atomic
(write to .tmp then rename) to prevent data loss on crash.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.logger import get_logger


class WorkflowState:
    """Workflow state constants for crash-safe state tracking.

    Uses plain strings (not Enum) for stable JSON serialization.
    """

    CREATED = "created"
    CLASSIFYING = "classifying"
    PLANNING = "planning"
    SOLVING = "solving"
    SOLVED = "solved"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class StepRecord:
    """One discrete step in the solve session."""

    iteration: int
    timestamp: float
    event: str  # "llm_response" | "tool_call" | "tool_result" | "pivot" | "summary"
    model: str = ""
    content: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""
    flags_found: list[str] = field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0


@dataclass
class SessionData:
    """Full session state that is serialised to/from JSON."""

    session_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    status: str = "in_progress"  # in_progress | solved | failed | paused
    description: str = ""
    target_url: str = ""
    files: list[str] = field(default_factory=list)
    flag_pattern: str = ""
    category: str = ""
    plan: str = ""
    flags: list[str] = field(default_factory=list)
    current_iteration: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    scratchpad: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    cost: dict[str, Any] = field(default_factory=dict)
    model_used: str = ""
    discoveries: list[str] = field(default_factory=list)
    workflow_state: str = WorkflowState.CREATED
    workflow_history: list[dict[str, Any]] = field(default_factory=list)


class SessionManager:
    """Manages session persistence to disk as JSON files.

    Sessions are stored under ``session_dir/<session_id>.json``.
    """

    def __init__(self, session_dir: Path | None = None) -> None:
        """Initialise the session manager.

        Args:
            session_dir: Directory where session files are stored.
        """
        self._dir = session_dir or Path("sessions")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._log = get_logger()
        self._data: SessionData | None = None
        self._steps: list[StepRecord] = []

    @property
    def session_id(self) -> str:
        """Return current session ID or empty string."""
        return self._data.session_id if self._data else ""

    def new_session(
        self,
        description: str,
        target_url: str = "",
        files: list[str] | None = None,
        flag_pattern: str = "",
    ) -> str:
        """Create a new session.

        Args:
            description: Challenge description.
            target_url: Target service URL.
            files: List of file paths.
            flag_pattern: Custom flag regex.

        Returns:
            The new session ID.
        """
        sid = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        now = datetime.now(tz=timezone.utc).isoformat()
        self._data = SessionData(
            session_id=sid,
            created_at=now,
            updated_at=now,
            description=description,
            target_url=target_url,
            files=files or [],
            flag_pattern=flag_pattern,
        )
        self._steps = []
        self._log.info(f"New session: {sid}")
        return sid

    def add_step(self, step: StepRecord) -> None:
        """Record a step and auto-save.

        Args:
            step: The step record to add.
        """
        self._steps.append(step)
        if self._data:
            self._data.steps.append(self._step_to_dict(step))
            self._data.current_iteration = step.iteration
            self._data.updated_at = datetime.now(tz=timezone.utc).isoformat()
            if step.flags_found:
                for f in step.flags_found:
                    if f not in self._data.flags:
                        self._data.flags.append(f)

    def transition(self, new_state: str, detail: str = "") -> None:
        """Transition the workflow to a new state.

        Appends a history entry recording the transition. Does NOT call
        save() — the existing iteration-end save covers persistence.

        Args:
            new_state: Target WorkflowState constant.
            detail: Optional description of why the transition occurred.
        """
        if self._data is None:
            return
        old_state = self._data.workflow_state
        self._data.workflow_state = new_state
        self._data.workflow_history.append({
            "from": old_state,
            "to": new_state,
            "detail": detail,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })

    def update(self, **kwargs: Any) -> None:
        """Update session metadata fields.

        Args:
            **kwargs: Fields of SessionData to update.
        """
        if self._data is None:
            return
        for key, val in kwargs.items():
            if hasattr(self._data, key):
                setattr(self._data, key, val)
        self._data.updated_at = datetime.now(tz=timezone.utc).isoformat()

    def save(self) -> Path | None:
        """Write the session to disk with atomic write.

        Uses a temporary file + rename to prevent corruption on crash.

        Returns:
            Path to the saved file, or None on failure.
        """
        if self._data is None:
            return None
        fpath = self._dir / f"{self._data.session_id}.json"
        try:
            content = json.dumps(
                asdict(self._data), indent=2, ensure_ascii=False, default=str
            )
            # Atomic write: write to .tmp then rename
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(self._dir), suffix=".tmp", prefix=".session_"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_fh:
                    tmp_fh.write(content)
                    tmp_fh.flush()
                    os.fsync(tmp_fh.fileno())
                os.replace(tmp_path, str(fpath))
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            self._log.debug(f"Session saved: {fpath}")
            return fpath
        except Exception as exc:
            self._log.error(f"Failed to save session: {exc}")
            return None

    def load(self, session_id: str) -> SessionData | None:
        """Load a session from disk.

        Args:
            session_id: The session ID to load.

        Returns:
            SessionData if found, None otherwise.
        """
        fpath = self._dir / f"{session_id}.json"
        if not fpath.exists():
            self._log.error(f"Session not found: {session_id}")
            return None
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
            self._data = SessionData(**{
                k: v for k, v in raw.items() if k in SessionData.__dataclass_fields__
            })
            self._log.info(f"Session loaded: {session_id}")
            return self._data
        except Exception as exc:
            self._log.error(f"Failed to load session {session_id}: {exc}")
            return None

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved sessions with summary info.

        Returns:
            List of dicts with session_id, status, description, created_at.
        """
        sessions: list[dict[str, Any]] = []
        for fpath in sorted(self._dir.glob("*.json"), reverse=True):
            if fpath.stem.endswith("_audit"):
                continue
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": raw.get("session_id", fpath.stem),
                    "status": raw.get("status", "?"),
                    "category": raw.get("category", "?"),
                    "description": raw.get("description", "")[:80],
                    "created_at": raw.get("created_at", ""),
                    "iterations": raw.get("current_iteration", 0),
                    "flags": raw.get("flags", []),
                })
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                continue
        return sessions

    def find_latest(self, status_filter: str | None = None) -> str | None:
        """Find the most recent session ID.

        Args:
            status_filter: If given, only consider sessions with this status
                (e.g. 'paused', 'in_progress', 'failed').

        Returns:
            Session ID string, or None if no sessions exist.
        """
        sessions = self.list_sessions()
        if not sessions:
            return None
        if status_filter:
            sessions = [s for s in sessions if s.get("status") == status_filter]
        if not sessions:
            return None
        return sessions[0].get("session_id")

    def get_session_data(self) -> SessionData | None:
        """Return the currently loaded session data."""
        return self._data

    def export_writeup(self, session_id: str | None = None) -> str:
        """Export a session as a Markdown writeup.

        Args:
            session_id: Session to export. Uses current if None.

        Returns:
            Markdown-formatted writeup string.
        """
        data = self._data
        if session_id and (not data or data.session_id != session_id):
            data = self.load(session_id)
        if data is None:
            return "No session data available."

        lines: list[str] = [
            f"# CTF Writeup: {data.description[:100]}",
            "",
            f"**Category:** {data.category}",
            f"**Status:** {data.status}",
            f"**Flags:** {', '.join(data.flags) if data.flags else 'None found'}",
            f"**Iterations:** {data.current_iteration}",
            f"**Date:** {data.created_at}",
            "",
            "## Summary",
            "",
            self._generate_summary(data),
            "",
            "---",
            "",
            "## Challenge",
            "",
            data.description,
            "",
        ]

        if data.target_url:
            lines.append(f"**Target:** {data.target_url}\n")
        if data.files:
            lines.append("**Files:** " + ", ".join(data.files) + "\n")

        if data.plan:
            lines.extend(["## Attack Plan", "", data.plan, ""])

        lines.extend(["## Solve Steps", ""])

        for step in data.steps:
            event = step.get("event", "")
            iteration = step.get("iteration", "?")

            if event == "llm_response":
                content = step.get("content", "")
                if content:
                    lines.append(f"### Step {iteration}: Analysis")
                    lines.append("")
                    lines.append(content[:2000])
                    lines.append("")

            elif event == "tool_call":
                tool = step.get("tool_name", "?")
                args = step.get("tool_args", {})
                output = step.get("tool_output", "")
                lines.append(f"### Step {iteration}: Tool `{tool}`")
                lines.append("")
                lines.append(f"```\n{json.dumps(args, indent=2)[:500]}\n```")
                lines.append("")
                if output:
                    lines.append(f"**Output:**\n```\n{output[:1000]}\n```")
                    lines.append("")

            elif event == "pivot":
                lines.append(f"### Step {iteration}: Strategy Pivot")
                lines.append("")
                lines.append(step.get("content", "Approach changed."))
                lines.append("")

        # Evidence section — collect significant tool outputs
        evidence = self._collect_evidence(data)
        if evidence:
            lines.extend(["## Evidence", ""])
            for i, item in enumerate(evidence, 1):
                lines.append(
                    f"**{i}. {item['tool']}** (step {item['iteration']})"
                )
                lines.append(f"\n```\n{item['output']}\n```\n")

        if data.flags:
            lines.extend([
                "## Flag",
                "",
                f"```\n{chr(10).join(data.flags)}\n```",
            ])

        if data.cost:
            cost = data.cost
            lines.extend([
                "",
                "## Cost",
                "",
                f"- Tokens: {cost.get('total_prompt_tokens', 0):,} input + "
                f"{cost.get('total_completion_tokens', 0):,} output",
                f"- Cost: ${cost.get('total_cost_usd', 0):.4f}",
            ])

        return "\n".join(lines)

    @staticmethod
    def _generate_summary(data: SessionData) -> str:
        """Generate a 2-3 sentence summary from session data."""
        status_text = {
            "solved": "was successfully solved",
            "failed": "was attempted but not solved",
            "paused": "was paused before completion",
            "in_progress": "is still in progress",
        }.get(data.status, f"ended with status '{data.status}'")

        cost_val = data.cost.get("total_cost_usd", 0) if data.cost else 0
        parts = [
            f"This {data.category or 'unknown'} challenge {status_text} "
            f"in {data.current_iteration} iteration(s)."
        ]

        if data.flags:
            parts.append(f"Found flag(s): {', '.join(data.flags)}.")

        if cost_val > 0:
            tokens = (
                data.cost.get("total_prompt_tokens", 0)
                + data.cost.get("total_completion_tokens", 0)
            )
            parts.append(
                f"Total cost: ${cost_val:.4f} ({tokens:,} tokens)."
            )

        return " ".join(parts)

    @staticmethod
    def _collect_evidence(data: SessionData, max_items: int = 10) -> list[dict[str, Any]]:
        """Collect significant non-error tool outputs as evidence artifacts."""
        evidence: list[dict[str, Any]] = []
        for step in data.steps:
            if step.get("event") != "tool_call":
                continue
            output = step.get("tool_output", "")
            if not output or len(output) < 20:
                continue
            if output.startswith("[ERROR]"):
                continue
            evidence.append({
                "tool": step.get("tool_name", "unknown"),
                "iteration": step.get("iteration", "?"),
                "output": output[:500],
            })
            if len(evidence) >= max_items:
                break
        return evidence

    def export_audit_log(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Export session steps as a structured audit log.

        Args:
            session_id: Session to export. Uses current if None.

        Returns:
            List of audit entry dicts with a consistent schema.
        """
        data = self._data
        if session_id and (not data or data.session_id != session_id):
            data = self.load(session_id)
        if data is None:
            return []

        entries: list[dict[str, Any]] = []
        for step in data.steps:
            entries.append({
                "timestamp": step.get("timestamp", 0),
                "iteration": step.get("iteration", 0),
                "event": step.get("event", ""),
                "model": step.get("model", ""),
                "tool": step.get("tool_name", ""),
                "input": step.get("tool_args", {}) if step.get("tool_name") else step.get("content", "")[:500],
                "output": step.get("tool_output", "") or step.get("content", "")[:500],
                "tokens": step.get("tokens_used", 0),
                "cost_usd": step.get("cost_usd", 0.0),
            })
        return entries

    def save_audit_log(self, session_id: str | None = None) -> Path | None:
        """Write an audit JSON file for the session.

        Args:
            session_id: Session to export. Uses current if None.

        Returns:
            Path to the audit file, or None on failure.
        """
        sid = session_id or (self._data.session_id if self._data else "")
        if not sid:
            return None

        entries = self.export_audit_log(session_id)
        if not entries:
            return None

        fpath = self._dir / f"{sid}_audit.json"
        try:
            fpath.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            self._log.debug(f"Audit log saved: {fpath}")
            return fpath
        except Exception as exc:
            self._log.error(f"Failed to save audit log: {exc}")
            return None

    @staticmethod
    def _step_to_dict(step: StepRecord) -> dict[str, Any]:
        """Convert a StepRecord to a plain dict.

        Args:
            step: The step to convert.

        Returns:
            Plain dictionary.
        """
        return {
            "iteration": step.iteration,
            "timestamp": step.timestamp,
            "event": step.event,
            "model": step.model,
            "content": step.content,
            "tool_name": step.tool_name,
            "tool_args": step.tool_args,
            "tool_output": step.tool_output,
            "flags_found": step.flags_found,
            "tokens_used": step.tokens_used,
            "cost_usd": step.cost_usd,
        }
