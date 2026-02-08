"""Base class for all CTF agent tools.

Every tool must inherit from BaseTool and implement the execute() method.
The class provides a standard interface that the tool registry and the
OpenAI function-calling layer rely on.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from utils.logger import get_logger


class ToolParameter(BaseModel):
    """Schema for a single tool parameter."""

    name: str
    type: str  # "string", "integer", "boolean", "array"
    description: str
    required: bool = True
    enum: list[str] | None = None


class ToolResult(BaseModel):
    """Standardised result returned by every tool execution."""

    success: bool
    output: str
    error: str | None = None
    duration_s: float = 0.0


class BaseTool(ABC):
    """Abstract base for all tools available to the CTF agent.

    Subclasses must define:
        - name: unique tool identifier
        - description: what the tool does (shown to the LLM)
        - parameters: list of ToolParameter for function-calling schema
        - execute(**kwargs) -> str: actual implementation
    """

    name: str = ""
    description: str = ""
    parameters: list[ToolParameter] = []
    timeout: int = 30  # default timeout in seconds

    def openai_schema(self) -> dict[str, Any]:
        """Generate the OpenAI function-calling tool definition.

        Returns:
            Dict matching OpenAI's tool schema for function calling.
        """
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with timing and error handling.

        Args:
            **kwargs: Arguments matching the declared parameters.

        Returns:
            ToolResult with output or error information.
        """
        log = get_logger()
        log.debug(f"Tool [{self.name}] called with: {kwargs}")
        start = time.monotonic()
        try:
            output = self.execute(**kwargs)
            duration = time.monotonic() - start
            log.debug(f"Tool [{self.name}] finished in {duration:.2f}s")
            return ToolResult(success=True, output=output, duration_s=round(duration, 3))
        except Exception as exc:
            duration = time.monotonic() - start
            error_msg = f"{type(exc).__name__}: {exc}"
            log.warning(f"Tool [{self.name}] error: {error_msg}")
            return ToolResult(
                success=False,
                output="",
                error=error_msg,
                duration_s=round(duration, 3),
            )

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """Run the tool logic and return output as a string.

        Args:
            **kwargs: Tool-specific arguments.

        Returns:
            Human-readable string result.
        """
        ...
