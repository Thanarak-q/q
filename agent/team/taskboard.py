"""Thread-safe shared task board for team coordination."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Task:
    """A single task on the board."""

    id: str
    subject: str
    description: str
    status: str = "pending"  # pending | in_progress | completed | failed
    owner: str = ""
    blocked_by: list[str] = field(default_factory=list)
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
            "blocked_by": self.blocked_by,
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
    ) -> Task:
        with self._lock:
            self._counter += 1
            task_id = f"task_{self._counter}"
            now = time.time()
            task = Task(
                id=task_id,
                subject=subject,
                description=description,
                blocked_by=list(blocked_by or []),
                created_at=now,
                updated_at=now,
            )
            self._tasks[task_id] = task
            return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_all(self) -> list[Task]:
        with self._lock:
            return list(self._tasks.values())

    def list_available(self) -> list[Task]:
        """Tasks that are pending, unblocked, and unowned."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status == "pending"
                and not t.owner
                and not self._is_blocked(t)
            ]

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
                lines.append(f"  {status_icon} {t.id}: {t.subject}{owner}")
            return "\n".join(lines)

    def _is_blocked(self, task: Task) -> bool:
        """Check if any blocker is still incomplete. Must hold lock."""
        for blocker_id in task.blocked_by:
            blocker = self._tasks.get(blocker_id)
            if blocker and blocker.status != "completed":
                return True
        return False
