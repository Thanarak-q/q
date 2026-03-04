"""Thread-safe shared task board for team coordination."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    """A single task on the board."""

    id: str
    subject: str
    description: str
    status: str = "pending"  # pending | in_progress | completed | failed
    owner: str = ""
    assignee: str = ""  # pre-assigned agent name (empty = any agent can take it)
    blocked_by: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "owner": self.owner,
            "assignee": self.assignee,
            "blocked_by": self.blocked_by,
            "blocks": self.blocks,
            "metadata": self.metadata,
            "result": self.result,
        }


class TaskBoard:
    """Thread-safe shared task list for team agents."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def create(
        self,
        subject: str,
        description: str = "",
        blocked_by: list[str] | None = None,
        blocks: list[str] | None = None,
        assignee: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        with self._lock:
            self._counter += 1
            task_id = f"task_{self._counter}"
            now = time.time()
            task = Task(
                id=task_id,
                subject=subject,
                description=description,
                assignee=assignee,
                blocked_by=list(blocked_by or []),
                blocks=list(blocks or []),
                metadata=dict(metadata or {}),
                created_at=now,
                updated_at=now,
            )
            self._tasks[task_id] = task

            # Auto-populate inverse dependency references
            for blocker_id in task.blocked_by:
                blocker = self._tasks.get(blocker_id)
                if blocker and task_id not in blocker.blocks:
                    blocker.blocks.append(task_id)

            for blocked_id in task.blocks:
                blocked = self._tasks.get(blocked_id)
                if blocked and task_id not in blocked.blocked_by:
                    blocked.blocked_by.append(task_id)

            return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_all(self) -> list[Task]:
        with self._lock:
            return list(self._tasks.values())

    def list_available(self, for_agent: str = "") -> list[Task]:
        """Tasks that are pending, unblocked, and unowned.

        If for_agent is given, only returns tasks assigned to that agent
        or tasks with no assignee.
        """
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status == "pending"
                and not t.owner
                and not self._is_blocked(t)
                and (not t.assignee or not for_agent or t.assignee == for_agent)
            ]

    def list_by_status(self, status: str) -> list[Task]:
        """Filter tasks by status."""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == status]

    def claim(self, task_id: str, owner: str) -> bool:
        """Claim a task. Returns False if already taken or blocked."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status != "pending" or task.owner:
                return False
            if self._is_blocked(task):
                return False
            task.owner = owner
            task.status = "in_progress"
            task.updated_at = time.time()
            return True

    def update(
        self,
        task_id: str,
        subject: str | None = None,
        description: str | None = None,
        assignee: str | None = None,
        add_blocked_by: list[str] | None = None,
        add_blocks: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Modify task fields atomically. Returns False if task not found."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if subject is not None:
                task.subject = subject
            if description is not None:
                task.description = description
            if assignee is not None:
                task.assignee = assignee

            if add_blocked_by:
                for bid in add_blocked_by:
                    if bid not in task.blocked_by:
                        task.blocked_by.append(bid)
                    blocker = self._tasks.get(bid)
                    if blocker and task_id not in blocker.blocks:
                        blocker.blocks.append(task_id)

            if add_blocks:
                for bid in add_blocks:
                    if bid not in task.blocks:
                        task.blocks.append(bid)
                    blocked = self._tasks.get(bid)
                    if blocked and task_id not in blocked.blocked_by:
                        blocked.blocked_by.append(task_id)

            if metadata:
                task.metadata.update(metadata)

            task.updated_at = time.time()
            return True

    def delete(self, task_id: str) -> bool:
        """Remove task and clean up dependency references."""
        with self._lock:
            task = self._tasks.pop(task_id, None)
            if not task:
                return False

            # Clean up references in other tasks
            for other in self._tasks.values():
                if task_id in other.blocked_by:
                    other.blocked_by.remove(task_id)
                if task_id in other.blocks:
                    other.blocks.remove(task_id)

            return True

    def complete(self, task_id: str, result: str = "") -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "completed"
                task.result = result
                task.updated_at = time.time()

    def fail(self, task_id: str, reason: str = "") -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "failed"
                task.result = reason
                task.updated_at = time.time()

    def all_done(self) -> bool:
        """True if all tasks are completed or failed."""
        with self._lock:
            if not self._tasks:
                return False
            return all(
                t.status in ("completed", "failed")
                for t in self._tasks.values()
            )

    def get_completed_results(self) -> dict[str, str]:
        """Map of task_id -> result for completed tasks."""
        with self._lock:
            return {
                t.id: t.result
                for t in self._tasks.values()
                if t.status == "completed" and t.result
            }

    def summary(self) -> str:
        """Human-readable summary of all tasks."""
        with self._lock:
            lines = []
            for t in self._tasks.values():
                status_icon = {
                    "pending": "○",
                    "in_progress": "◉",
                    "completed": "✓",
                    "failed": "✗",
                }.get(t.status, "?")
                owner = f" [{t.owner}]" if t.owner else ""
                blocked = ""
                if t.blocked_by:
                    pending_blockers = [
                        bid for bid in t.blocked_by
                        if (b := self._tasks.get(bid)) and b.status != "completed"
                    ]
                    if pending_blockers:
                        blocked = f" (blocked by: {', '.join(pending_blockers)})"
                lines.append(f"  {status_icon} {t.id}: {t.subject}{owner}{blocked}")
            return "\n".join(lines)

    def _is_blocked(self, task: Task) -> bool:
        """Check if any blocker is still incomplete. Must hold lock."""
        for blocker_id in task.blocked_by:
            blocker = self._tasks.get(blocker_id)
            if blocker and blocker.status != "completed":
                return True
        return False
