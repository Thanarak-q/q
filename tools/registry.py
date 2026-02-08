"""Tool registry that maps tool names to instances.

Provides the list of OpenAI tool definitions and dispatches calls
by name.
"""

from __future__ import annotations

from typing import Any, Optional

from tools.base import BaseTool, ToolResult
from tools.file_manager import FileManagerTool
from tools.network import NetworkTool
from tools.python_exec import PythonExecTool
from tools.shell import ShellTool
from utils.logger import get_logger


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

        # Truncate oversized output
        from config import load_config
        max_chars = load_config().agent.tool_output_max_chars
        if len(result.output) > max_chars:
            result.output = result.output[:max_chars] + f"\n\n[TRUNCATED at {max_chars} chars]"

        return result
