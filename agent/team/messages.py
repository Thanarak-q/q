"""Thread-safe message bus for inter-agent communication."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Message:
    """A single message between agents."""

    sender: str
    recipient: str  # Agent name or "*" for broadcast
    content: str
    msg_type: str = "info"  # info | discovery | instruction | shutdown_request | shutdown_response | flag | idle | task_created
    request_id: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "sender": self.sender,
            "recipient": self.recipient,
            "content": self.content,
            "type": self.msg_type,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        }


class MessageBus:
    """Thread-safe per-agent message queues."""

    def __init__(self) -> None:
        self._queues: dict[str, list[Message]] = defaultdict(list)
        self._log: list[Message] = []
        self._lock = threading.Lock()

    def send(
        self,
        sender: str,
        recipient: str,
        content: str,
        msg_type: str = "info",
        request_id: str = "",
    ) -> None:
        msg = Message(
            sender=sender,
            recipient=recipient,
            content=content,
            msg_type=msg_type,
            request_id=request_id,
        )
        with self._lock:
            self._queues[recipient].append(msg)
            self._log.append(msg)

    def broadcast(
        self,
        sender: str,
        content: str,
        msg_type: str = "info",
        exclude: str | None = None,
    ) -> None:
        """Send to all registered recipients except exclude."""
        with self._lock:
            recipients = [r for r in self._queues if r != exclude and r != sender]
        for r in recipients:
            self.send(sender, r, content, msg_type)

    def receive(self, recipient: str) -> list[Message]:
        """Drain and return all pending messages for recipient."""
        with self._lock:
            msgs = self._queues.pop(recipient, [])
            return msgs

    def peek(self, recipient: str) -> list[Message]:
        """Non-destructive read of pending messages for recipient."""
        with self._lock:
            return list(self._queues.get(recipient, []))

    def has_messages(self, recipient: str) -> bool:
        with self._lock:
            return bool(self._queues.get(recipient))

    def register(self, name: str) -> None:
        """Register an agent name so broadcasts reach it."""
        with self._lock:
            if name not in self._queues:
                self._queues[name] = []

    def get_log(self, limit: int = 50) -> list[Message]:
        """Return recent message history."""
        with self._lock:
            return list(self._log[-limit:])

    def get_discoveries(self) -> list[Message]:
        """Return all discovery-type messages (findings from agents)."""
        with self._lock:
            return [m for m in self._log if m.msg_type == "discovery"]

    # ── Shutdown protocol helpers ──────────────────────────────────

    def send_shutdown_request(
        self,
        sender: str,
        recipient: str,
        content: str = "Shutting down team",
    ) -> str:
        """Send a shutdown request. Returns the request_id."""
        req_id = uuid.uuid4().hex[:8]
        self.send(
            sender=sender,
            recipient=recipient,
            content=content,
            msg_type="shutdown_request",
            request_id=req_id,
        )
        return req_id

    def send_shutdown_response(
        self,
        sender: str,
        recipient: str,
        request_id: str,
        approved: bool = True,
        content: str = "",
    ) -> None:
        """Send a shutdown response (approve or reject)."""
        msg_content = content or ("Shutdown approved" if approved else "Shutdown rejected")
        self.send(
            sender=sender,
            recipient=recipient,
            content=msg_content,
            msg_type="shutdown_response",
            request_id=request_id,
        )
