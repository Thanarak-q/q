"""Structured Markdown report generator.

Produces a professional solve report after each session, including
challenge info, result, steps taken, evidence, and statistics.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.evidence_tracker import EvidenceTracker


def generate_report(
    session_data: dict[str, Any],
    cost_data: dict[str, Any] | None = None,
    duration_s: float = 0.0,
    evidence_tracker: EvidenceTracker | None = None,
    answer: str = "",
) -> str:
    """Generate a Markdown solve report from session data.

    Args:
        session_data: The session dict (from SessionData).
        cost_data: Cost tracker dict (from CostTracker.to_dict()).
        duration_s: Total solve duration in seconds.

    Returns:
        Markdown-formatted report string.
    """
    sid = session_data.get("session_id", "unknown")
    description = session_data.get("description", "")
    category = session_data.get("category", "unknown")
    status = session_data.get("status", "unknown")
    flags = session_data.get("flags", [])
    steps = session_data.get("steps", [])
    plan = session_data.get("plan", "")
    files = session_data.get("files", [])
    model_used = session_data.get("model_used", "")

    # Determine result status
    if status == "solved" and flags:
        status_icon = "\u2705 Solved"
    elif status == "solved":
        status_icon = "\u2705 Solved"
    elif status == "paused":
        status_icon = "\u26a0\ufe0f Paused"
    else:
        status_icon = "\u274c Failed"

    # Extract answer from steps (use parameter if provided)
    answer_confidence = ""
    if not answer:
        for step in reversed(steps):
            if step.get("tool_name") == "answer_user":
                args = step.get("tool_args", {})
                answer = args.get("answer", "")
                answer_confidence = args.get("confidence", "")
                break
    else:
        # Still extract confidence from steps
        for step in reversed(steps):
            if step.get("tool_name") == "answer_user":
                args = step.get("tool_args", {})
                answer_confidence = args.get("confidence", "")
                break

    # Build report
    lines: list[str] = []

    # Header
    lines.append("# Q CTF Agent \u2014 Solve Report")
    lines.append("")

    # Challenge Info
    lines.append("## Challenge Info")
    lines.append(f"- **Description**: {description}")
    lines.append(f"- **Category**: {category}")
    if files:
        file_names = [Path(f).name for f in files]
        lines.append(f"- **Files**: {', '.join(file_names)}")
    lines.append(f"- **Session**: {sid}")
    lines.append("")

    # Result
    lines.append("## Result")
    lines.append(f"- **Status**: {status_icon}")
    if answer:
        lines.append(f"- **Answer**: {answer}")
    if flags:
        lines.append(f"- **Flag**: {', '.join(flags)}")
    if answer_confidence:
        lines.append(f"- **Confidence**: {answer_confidence}")
    lines.append("")

    # Attack Plan
    if plan:
        lines.append("## Attack Plan")
        lines.append("")
        lines.append(plan)
        lines.append("")

    # Steps Taken table
    tool_steps = [s for s in steps if s.get("event") == "tool_call"]
    if tool_steps:
        lines.append("## Steps Taken")
        lines.append("")
        lines.append("| Step | Action | Tool | Result |")
        lines.append("|------|--------|------|--------|")
        for i, step in enumerate(tool_steps, 1):
            tool = step.get("tool_name", "?")
            args = step.get("tool_args", {})
            output = step.get("tool_output", "")

            # Build action summary
            action = _summarize_action(tool, args)
            # Build result summary
            result_summary = _summarize_result(output)

            lines.append(f"| {i} | {action} | {tool} | {result_summary} |")
        lines.append("")

    # Evidence section
    evidence_steps = [
        s for s in steps
        if s.get("event") == "tool_call"
        and s.get("tool_output", "")
        and not s.get("tool_output", "").startswith("[ERROR]")
        and len(s.get("tool_output", "")) > 20
    ]

    if evidence_steps:
        lines.append("## Evidence")
        lines.append("")
        for i, step in enumerate(evidence_steps, 1):
            tool = step.get("tool_name", "?")
            iteration = step.get("iteration", "?")
            args = step.get("tool_args", {})
            output = step.get("tool_output", "")

            lines.append(f"### Step {iteration}: {_summarize_action(tool, args)}")
            lines.append("")

            # Show command if shell
            if tool == "shell" and "command" in args:
                lines.append("```")
                lines.append(args["command"])
                lines.append("```")
                lines.append("")

            if tool == "python_exec" and "code" in args:
                lines.append("```python")
                lines.append(args["code"][:500])
                lines.append("```")
                lines.append("")

            lines.append("Output:")
            lines.append("```")
            lines.append(output[:800])
            lines.append("```")
            lines.append("")

    # Evidence Chain (anti-hallucination verification)
    if evidence_tracker is not None:
        from tools.evidence_tracker import extract_claims as _extract

        answer_text = answer or ""
        if not answer_text:
            # Try to extract from steps
            for step in reversed(steps):
                if step.get("tool_name") == "answer_user":
                    args = step.get("tool_args", {})
                    answer_text = args.get("answer", "")
                    break

        if answer_text:
            claims = _extract(answer_text)
            if claims:
                chain = evidence_tracker.build_evidence_chain(claims)
                lines.append("## Evidence Chain")
                lines.append("")

                verified_count = sum(1 for c in chain if c["verified"])
                unverified_count = len(chain) - verified_count

                for item in chain:
                    icon = "\u2705" if item["verified"] else "\u26a0\ufe0f"
                    lines.append(
                        f"- {icon} `{item['claim']}` \u2014 Source: {item['source']}"
                    )

                lines.append("")
                if unverified_count:
                    lines.append(
                        f"\u26a0\ufe0f **WARNING**: {unverified_count} claim(s) "
                        f"could not be traced to tool output."
                    )
                else:
                    lines.append(
                        f"\u2705 All {verified_count} claim(s) verified against tool output."
                    )
                lines.append("")

    # Statistics
    lines.append("## Statistics")

    total_steps = len(tool_steps)
    lines.append(f"- **Steps**: {total_steps}")

    if cost_data:
        total_tokens = (
            cost_data.get("total_prompt_tokens", 0)
            + cost_data.get("total_completion_tokens", 0)
        )
        tokens_str = f"{total_tokens / 1000:.1f}k" if total_tokens >= 1000 else str(total_tokens)
        prompt_tokens = cost_data.get("total_prompt_tokens", 0)
        compl_tokens = cost_data.get("total_completion_tokens", 0)
        p_str = f"{prompt_tokens / 1000:.1f}k" if prompt_tokens >= 1000 else str(prompt_tokens)
        c_str = f"{compl_tokens / 1000:.1f}k" if compl_tokens >= 1000 else str(compl_tokens)
        total_cost = cost_data.get("total_cost_usd", 0)

        lines.append(f"- **Tokens**: {tokens_str} (prompt: {p_str}, completion: {c_str})")
        lines.append(f"- **Cost**: ${total_cost:.4f}")

    if duration_s > 0:
        if duration_s >= 60:
            lines.append(f"- **Duration**: {duration_s / 60:.1f} minutes")
        else:
            lines.append(f"- **Duration**: {duration_s:.0f} seconds")

    if model_used:
        lines.append(f"- **Model**: {model_used}")

    lines.append("")
    return "\n".join(lines)


def save_report(
    report_md: str,
    session_id: str,
    report_dir: Path | None = None,
) -> Path:
    """Save a report to disk.

    Args:
        report_md: The Markdown report content.
        session_id: Session ID for the filename.
        report_dir: Directory to save in (default: ./reports).

    Returns:
        Path to the saved report file.
    """
    dest = report_dir or Path("reports")
    dest.mkdir(parents=True, exist_ok=True)
    fpath = dest / f"{session_id}.md"
    fpath.write_text(report_md, encoding="utf-8")
    return fpath


def _summarize_action(tool: str, args: dict) -> str:
    """Build a short action summary for the steps table."""
    if tool == "shell":
        cmd = args.get("command", "")
        # Take first word of command
        parts = cmd.split()
        if parts:
            return f"{parts[0]} {''.join(parts[1:3])}"[:50]
        return "shell command"
    if tool == "python_exec":
        code = args.get("code", "")
        first_line = code.strip().splitlines()[0] if code.strip() else ""
        return first_line[:50] or "python script"
    if tool == "file_manager":
        action = args.get("action", "?")
        path = args.get("path", "")
        name = Path(path).name if path else ""
        return f"{action} {name}"[:50]
    if tool == "network":
        method = args.get("http_method", "GET")
        url = args.get("url", "")
        return f"{method} {url}"[:50]
    if tool == "answer_user":
        return "Submit answer"
    return tool


def _summarize_result(output: str, max_len: int = 60) -> str:
    """Build a short result summary for the steps table."""
    if not output:
        return "(empty)"
    if output.startswith("[ERROR]"):
        return output[:max_len]
    # First non-empty line
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            if len(stripped) > max_len:
                return stripped[:max_len - 3] + "..."
            return stripped
    return output[:max_len]
