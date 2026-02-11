"""Structured JSONL audit logger.

Appends one JSON object per line to a session-specific audit file.
Events are written in append mode so no data is lost on crash.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    """Append-only JSONL audit logger for a single session.

    Each call to ``log()`` writes one JSON line immediately.
    """

    def __init__(self, session_id: str, session_dir: Path | None = None) -> None:
        self._session_id = session_id
        self._dir = session_dir or Path("sessions")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fpath = self._dir / f"{session_id}_audit.jsonl"
        self._fh = open(self._fpath, "a", encoding="utf-8")

    def log(self, event_type: str, **kwargs: Any) -> None:
        """Write a single audit event.

        Args:
            event_type: Event type string (session_start, tool_call, etc.)
            **kwargs: Arbitrary event data.
        """
        entry = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "type": event_type,
            "session_id": self._session_id,
            **kwargs,
        }
        line = json.dumps(entry, ensure_ascii=False, default=str)
        self._fh.write(line + "\n")
        self._fh.flush()

    def log_session_start(
        self,
        challenge: str,
        files: list[str] | None = None,
        target_url: str = "",
    ) -> None:
        self.log(
            "session_start",
            challenge=challenge[:200],
            files=files or [],
            target_url=target_url,
        )

    def log_classify(self, category: str, intent: str) -> None:
        self.log("classify", category=category, intent=intent)

    def log_plan(self, model: str, plan: str) -> None:
        self.log("plan", model=model, plan=plan[:500])

    def log_tool_call(
        self,
        step: int,
        tool: str,
        args: dict,
        tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        self.log(
            "tool_call",
            step=step,
            tool=tool,
            args=_truncate_args(args),
            tokens=tokens,
            cost=round(cost, 6),
        )

    def log_tool_result(
        self,
        step: int,
        tool: str,
        success: bool,
        output_length: int,
    ) -> None:
        self.log(
            "tool_result",
            step=step,
            tool=tool,
            success=success,
            output_length=output_length,
        )

    def log_tool_error(self, step: int, tool: str, error: str) -> None:
        self.log("tool_error", step=step, tool=tool, error=error[:300])

    def log_answer(self, answer: str, confidence: str, flag: str = "") -> None:
        self.log(
            "answer",
            answer=answer[:500],
            confidence=confidence,
            flag=flag,
        )

    def log_flag_found(self, flag: str) -> None:
        self.log("flag_found", flag=flag)

    def log_pivot(self, level: str, pivot_count: int) -> None:
        self.log("pivot", level=level, pivot_count=pivot_count)

    def log_model_switch(self, old_model: str, new_model: str) -> None:
        self.log("model_switch", old_model=old_model, new_model=new_model)

    def log_context_summary(self, old_messages: int, new_messages: int) -> None:
        self.log(
            "context_summary",
            old_messages=old_messages,
            new_messages=new_messages,
        )

    def log_session_end(
        self,
        status: str,
        total_steps: int,
        total_tokens: int,
        total_cost: float,
    ) -> None:
        self.log(
            "session_end",
            status=status,
            total_steps=total_steps,
            total_tokens=total_tokens,
            total_cost=round(total_cost, 6),
        )

    def close(self) -> None:
        """Flush and close the audit file."""
        if self._fh and not self._fh.closed:
            self._fh.flush()
            self._fh.close()

    @property
    def path(self) -> Path:
        return self._fpath

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def read_audit_log(
    session_id: str,
    session_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Read all entries from an audit log.

    Args:
        session_id: Session ID.
        session_dir: Directory containing audit files.

    Returns:
        List of audit event dicts.
    """
    fpath = (session_dir or Path("sessions")) / f"{session_id}_audit.jsonl"
    if not fpath.exists():
        return []

    entries: list[dict[str, Any]] = []
    with open(fpath, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def summarize_audit_log(entries: list[dict[str, Any]]) -> str:
    """Produce a human-readable summary of audit entries.

    Args:
        entries: List of audit event dicts.

    Returns:
        Formatted summary string.
    """
    if not entries:
        return "No audit entries."

    lines: list[str] = []
    total_tokens = 0
    total_cost = 0.0
    tool_calls = 0

    for e in entries:
        event_type = e.get("type", "?")
        ts = e.get("ts", "")
        ts_short = ts[11:19] if len(ts) > 19 else ts

        if event_type == "session_start":
            lines.append(f"[{ts_short}] Session started")
        elif event_type == "classify":
            lines.append(
                f"[{ts_short}] Classified: {e.get('category', '?')} "
                f"({e.get('intent', '?')})"
            )
        elif event_type == "plan":
            lines.append(f"[{ts_short}] Plan created ({e.get('model', '?')})")
        elif event_type == "tool_call":
            tool_calls += 1
            tokens = e.get("tokens", 0)
            cost = e.get("cost", 0.0)
            total_tokens += tokens
            total_cost += cost
            lines.append(
                f"[{ts_short}] Step {e.get('step', '?')}: "
                f"{e.get('tool', '?')} "
                f"({tokens} tok, ${cost:.4f})"
            )
        elif event_type == "tool_result":
            status = "\u2713" if e.get("success") else "\u2717"
            lines.append(
                f"           {status} {e.get('tool', '?')} "
                f"({e.get('output_length', 0)} chars)"
            )
        elif event_type == "tool_error":
            lines.append(
                f"           \u2717 ERROR: {e.get('error', '?')[:80]}"
            )
        elif event_type == "answer":
            lines.append(
                f"[{ts_short}] Answer ({e.get('confidence', '?')}): "
                f"{e.get('answer', '')[:80]}"
            )
        elif event_type == "flag_found":
            lines.append(f"[{ts_short}] FLAG: {e.get('flag', '?')}")
        elif event_type == "pivot":
            lines.append(
                f"[{ts_short}] Pivot #{e.get('pivot_count', '?')}: "
                f"{e.get('level', '?')}"
            )
        elif event_type == "model_switch":
            lines.append(
                f"[{ts_short}] Model: {e.get('old_model')} -> "
                f"{e.get('new_model')}"
            )
        elif event_type == "session_end":
            lines.append(
                f"[{ts_short}] Session ended: {e.get('status', '?')} "
                f"({e.get('total_steps', 0)} steps, "
                f"{e.get('total_tokens', 0)} tokens, "
                f"${e.get('total_cost', 0):.4f})"
            )

    lines.append("")
    lines.append(
        f"Summary: {tool_calls} tool calls, "
        f"{total_tokens} tokens, ${total_cost:.4f}"
    )
    return "\n".join(lines)


def export_audit_csv(
    entries: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Export audit entries as CSV.

    Args:
        entries: List of audit event dicts.
        output_path: Destination CSV file path.

    Returns:
        Path to the written CSV file.
    """
    import csv

    fieldnames = [
        "ts", "type", "session_id", "step", "tool",
        "success", "tokens", "cost", "output_length",
        "answer", "confidence", "flag", "error",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)

    return output_path


def _truncate_args(args: dict, max_len: int = 200) -> dict:
    """Truncate long argument values for audit logging."""
    result = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > max_len:
            result[k] = v[:max_len] + "..."
        else:
            result[k] = v
    return result
