"""Task tree renderer for minimal Claude Code-style output.

Renders agent events as a tree structure with Unicode box-drawing
connectors and ANSI colors.  Uses direct ANSI escape codes (not Rich)
for full control over incremental, streaming output.

Example output::

    ● Analyzing challenge (forensics)
    ├── ✓ Extract IP addresses from pcap
    │     Found: 111.224.250.131, 170.40.150.126
    ├── ✓ Analyze HTTP requests
    │     SQL injection attempts detected
    └── ✓ Identify attacker
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TextIO


# ------------------------------------------------------------------
# Node state and icons
# ------------------------------------------------------------------


class NodeState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


STATE_ICONS: dict[NodeState, str] = {
    NodeState.PENDING: "○",
    NodeState.RUNNING: "■",
    NodeState.DONE: "✓",
    NodeState.FAILED: "✗",
}

# ANSI color codes — applied only when output is a tty.
_COLORS = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "green": "\033[32m",
    "dim_green": "\033[2;32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "bold_green": "\033[1;32m",
    "grey": "\033[90m",
}


# ------------------------------------------------------------------
# Tree node
# ------------------------------------------------------------------


@dataclass
class TreeNode:
    """One node in the task tree."""

    title: str
    state: NodeState = NodeState.PENDING
    detail: str = ""
    verbose_detail: str = ""


# ------------------------------------------------------------------
# Task tree
# ------------------------------------------------------------------


class TaskTree:
    """Maintains and renders a streaming task tree for one solve session."""

    def __init__(
        self,
        stream: TextIO | None = None,
        use_color: bool = True,
    ) -> None:
        self._nodes: list[TreeNode] = []
        self._root_title: str = ""
        self._stream = stream or sys.stdout
        self._use_color = use_color and hasattr(self._stream, "isatty") and self._stream.isatty()
        self._spinner: object | None = None

    # -- public API ------------------------------------------------

    def set_spinner(self, spinner: object | None) -> None:
        """Attach a LiveSpinner for output coordination."""
        self._spinner = spinner

    def set_root(self, title: str) -> None:
        """Set and print the root task title."""
        self._root_title = title
        icon = self._c("bold", "●")
        text = self._c("bold", self._root_title)
        self._write(f"\n{icon} {text}\n")

    def add_node(
        self,
        title: str,
        state: NodeState = NodeState.RUNNING,
    ) -> int:
        """Add a child node and print it.  Returns the node index."""
        node = TreeNode(title=title, state=state)
        self._nodes.append(node)
        idx = len(self._nodes) - 1
        self._print_node(idx)
        return idx

    def complete_node(
        self,
        index: int,
        detail: str = "",
        verbose_detail: str = "",
        success: bool = True,
    ) -> None:
        """Mark a node as done/failed and print result status."""
        if index < 0 or index >= len(self._nodes):
            return
        node = self._nodes[index]
        node.state = NodeState.DONE if success else NodeState.FAILED
        node.detail = detail
        node.verbose_detail = verbose_detail
        # Print a completion line: │  ✓ detail  (or  │  ✗ error)
        if detail:
            icon = self._state_icon(node.state)
            self._write(f"│  {icon} {self._c('dim', detail)}\n")

    def add_completed_node(
        self,
        title: str,
        detail: str = "",
        success: bool = True,
    ) -> int:
        """Add a node that is already done/failed."""
        state = NodeState.DONE if success else NodeState.FAILED
        node = TreeNode(title=title, state=state, detail=detail)
        self._nodes.append(node)
        idx = len(self._nodes) - 1
        self._print_node(idx)
        return idx

    def reset(self) -> None:
        """Clear all nodes for a new solve session."""
        self._nodes.clear()
        self._root_title = ""

    def render_to_string(self) -> str:
        """Render the task tree to a string instead of stdout."""
        from io import StringIO
        buf = StringIO()
        if self._root_title:
            buf.write(f"● {self._root_title}\n")
        for node in self._nodes:
            icon = self._state_icon(node.state) if self._use_color else STATE_ICONS.get(node.state, "○")
            line = f"├── {icon} {node.title}"
            if node.detail:
                line += f" — {node.detail}"
            buf.write(line + "\n")
        return buf.getvalue()

    # -- rendering -------------------------------------------------

    def _c(self, color_name: str, text: str) -> str:
        """Apply ANSI color if enabled."""
        if not self._use_color:
            return text
        code = _COLORS.get(color_name, "")
        if not code:
            return text
        return f"{code}{text}{_COLORS['reset']}"

    def _state_icon(self, state: NodeState) -> str:
        """Return the colored icon for a node state."""
        icon = STATE_ICONS[state]
        color_map = {
            NodeState.PENDING: "grey",
            NodeState.RUNNING: "yellow",
            NodeState.DONE: "dim_green",
            NodeState.FAILED: "red",
        }
        return self._c(color_map[state], icon)

    def _print_node(self, index: int) -> None:
        """Print a child node line with connector."""
        node = self._nodes[index]
        icon = self._state_icon(node.state)
        line = f"├── {icon} {node.title}"
        self._write(line + "\n")
        if node.detail:
            self._write(f"│     {self._c('dim', node.detail)}\n")

    def _write(self, text: str) -> None:
        """Write text to the output stream, coordinating with any spinner."""
        s = self._spinner
        if s and hasattr(s, "clear_for_output"):
            s.clear_for_output()
        self._stream.write(text)
        self._stream.flush()
        if s and hasattr(s, "done_output"):
            s.done_output()


# ------------------------------------------------------------------
# Summarization helpers
# ------------------------------------------------------------------

# Patterns for action-oriented sentences in LLM thinking
_ACTION_PATTERNS = [
    re.compile(r"(?:I(?:'ll| will| need to| should|'m going to)\s+.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:Let me\s+.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:Next,?\s+.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:Now,?\s+I?\s*.+?)(?:\.|$)", re.IGNORECASE),
]


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if needed."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def summarize_thinking(text: str, max_len: int = 80) -> str:
    """Extract a 1-line summary from LLM thinking text.

    Strategy: look for action sentences first, then fall back to the
    first non-empty line.
    """
    if not text or not text.strip():
        return ""

    for pat in _ACTION_PATTERNS:
        match = pat.search(text)
        if match:
            sentence = match.group(0).strip()
            if len(sentence) > 10:
                return _truncate(sentence, max_len)

    # Fallback: first non-empty line with reasonable length
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped) > 5:
            return _truncate(stripped, max_len)

    return _truncate(text.strip(), max_len)


def summarize_tool_call(tool_name: str, args: dict, max_len: int = 60) -> str:
    """Convert tool_name + args into a readable 1-line summary.

    Examples::

        shell + {"command": "tshark -r f.pcap"} -> "shell: tshark -r f.pcap"
        python_exec + {"code": "import..."} -> "python: import..."
        file_manager + {"action": "read", "path": "x"} -> "file: read x"
        network + {"url": "http://..."} -> "network: GET http://..."
    """
    if tool_name == "shell":
        cmd = args.get("command", "")
        return _truncate(f"shell: {cmd}", max_len)

    if tool_name == "python_exec":
        code = args.get("code", "")
        first_line = code.strip().splitlines()[0] if code.strip() else ""
        return _truncate(f"python: {first_line}", max_len)

    if tool_name == "file_manager":
        action = args.get("action", "?")
        path = args.get("path", "")
        short = path.rsplit("/", 1)[-1] if "/" in path else path
        return _truncate(f"file: {action} {short}", max_len)

    if tool_name == "network":
        method = args.get("http_method", "GET")
        url = args.get("url", "")
        return _truncate(f"network: {method} {url}", max_len)

    if tool_name == "answer_user":
        return "answer_user"

    # Generic fallback
    arg_str = ", ".join(f"{k}={v}" for k, v in list(args.items())[:2])
    return _truncate(f"{tool_name}: {arg_str}", max_len)


def summarize_tool_result(output: str, max_len: int = 80) -> str:
    """Extract a 1-line summary from tool output."""
    if not output:
        return ""

    for line in output.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("[TRUNCATED"):
            return _truncate(stripped, max_len)

    first = output.strip().splitlines()[0] if output.strip() else ""
    return _truncate(first, max_len)
