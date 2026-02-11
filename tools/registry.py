"""Tool registry that maps tool names to instances.

Provides the list of OpenAI tool definitions and dispatches calls
by name.  Includes smart output truncation for different content types.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from tools.answer_user import AnswerUserTool
from tools.base import BaseTool, ToolResult
from tools.file_manager import FileManagerTool
from tools.network import NetworkTool
from tools.python_exec import PythonExecTool
from tools.shell import ShellTool
from utils.logger import get_logger


def _has_binary_chars(data: str) -> bool:
    """Check if string contains non-text binary characters."""
    binary_count = sum(
        1 for ch in data[:500]
        if ord(ch) < 32 and ch not in "\n\r\t"
    )
    return binary_count > len(data[:500]) * 0.1


def _smart_truncate(output: str, max_chars: int) -> str:
    """Truncate tool output intelligently based on content type.

    - Binary data → immediate summary.
    - Hex / binary data → aggressive truncation (200 chars) + summary.
    - HTML → strip tags, keep text.
    - Repeated lines → deduplicate.
    - Same-as-previous detection is handled at the orchestrator level.
    - Everything else → normal truncation with char count.
    """
    if len(output) <= max_chars:
        return output

    # Detect binary data (non-printable chars)
    if _has_binary_chars(output):
        return (
            f"Binary data ({len(output)} bytes). "
            f"Use file_manager with read action for details."
        )

    # Detect hex dumps (lines of hex like "00 4a 2f ...")
    hex_pattern = re.compile(r"^[0-9a-fA-F\s:.|]{20,}$", re.MULTILINE)
    hex_matches = hex_pattern.findall(output)
    if len(hex_matches) > 10:
        limit = min(200, max_chars)
        return (
            output[:limit]
            + f"\n... (truncated, {len(output)} chars total)"
        )

    # Detect HTML content
    if "<html" in output.lower() or "<body" in output.lower():
        stripped = re.sub(r"<[^>]+>", " ", output)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        if len(stripped) <= max_chars:
            return f"[HTML tags stripped]\n{stripped}"
        return (
            f"[HTML tags stripped]\n{stripped[:max_chars]}"
            f"\n... (truncated, showing {max_chars}/{len(stripped)} chars)"
        )

    # Deduplicate repeated lines
    lines = output.splitlines()
    if len(lines) > 20:
        seen: dict[str, int] = {}
        deduped: list[str] = []
        suppressed = 0
        for line in lines:
            key = line.strip()
            seen[key] = seen.get(key, 0) + 1
            if seen[key] <= 2:
                deduped.append(line)
            else:
                suppressed += 1
        if suppressed > 0:
            output = "\n".join(deduped)
            output += f"\n[{suppressed} duplicate lines suppressed]"
            if len(output) <= max_chars:
                return output

    # Default truncation
    return (
        output[:max_chars]
        + f"\n... (truncated, showing {max_chars}/{len(output)} chars)"
    )


class ToolRegistry:
    """Registry holding all available tools for the CTF agent.

    Provides lookup by name, the combined OpenAI tool definitions, and
    a dispatch method for executing tool calls.
    """

    def __init__(
        self,
        docker_manager: Optional[Any] = None,
        workspace: Optional[Any] = None,
    ) -> None:
        """Initialise the registry and register default tools.

        Args:
            docker_manager: Optional DockerSandbox instance shared by tools.
            workspace: Optional workspace Path for file operations.
        """
        self._tools: dict[str, BaseTool] = {}
        self._log = get_logger()

        # Register built-in tools
        self.register(ShellTool(docker_manager=docker_manager))
        self.register(PythonExecTool(docker_manager=docker_manager))
        self.register(FileManagerTool(workspace=workspace, docker_manager=docker_manager))
        self.register(NetworkTool())
        self.register(AnswerUserTool())

    @classmethod
    def from_subset(
        cls,
        tool_names: list[str],
        docker_manager: Optional[Any] = None,
        workspace: Optional[Any] = None,
    ) -> "ToolRegistry":
        """Create a registry with only the specified tools.

        Useful for pipeline agents that need a restricted tool set.

        Args:
            tool_names: List of tool names to include.
            docker_manager: Docker sandbox manager.
            workspace: Workspace path.

        Returns:
            A ToolRegistry with only the requested tools registered.
        """
        full = cls(docker_manager=docker_manager, workspace=workspace)
        filtered = cls.__new__(cls)
        filtered._tools = {}
        filtered._log = get_logger()

        for name in tool_names:
            tool = full.get(name)
            if tool:
                filtered._tools[name] = tool

        # Register submit_deliverable if requested but not in the full set
        if "submit_deliverable" in tool_names and "submit_deliverable" not in filtered._tools:
            from tools.submit_deliverable import SubmitDeliverableTool
            filtered._tools["submit_deliverable"] = SubmitDeliverableTool()

        return filtered

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance.

        Args:
            tool: BaseTool subclass instance.
        """
        if tool.name in self._tools:
            self._log.warning(f"Overwriting existing tool: {tool.name}")
        self._tools[tool.name] = tool
        self._log.debug(f"Registered tool: {tool.name}")

    def get(self, name: str) -> BaseTool | None:
        """Look up a tool by name.

        Args:
            name: Tool identifier.

        Returns:
            The tool instance, or None if not found.
        """
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        """Return all registered tool names.

        Returns:
            Sorted list of tool name strings.
        """
        return sorted(self._tools.keys())

    def openai_definitions(self) -> list[dict[str, Any]]:
        """Generate OpenAI tool definitions for all registered tools.

        Returns:
            List of tool schema dicts ready for the API.
        """
        return [tool.openai_schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with the given arguments.

        Args:
            name: Tool name to invoke.
            arguments: Keyword arguments for the tool.

        Returns:
            ToolResult with output or error.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {name}",
            )

        result = tool.run(**arguments)

        # Smart truncation for oversized output
        from config import load_config
        max_chars = load_config().agent.tool_output_max_chars
        if len(result.output) > max_chars:
            result.output = _smart_truncate(result.output, max_chars)

        return result
