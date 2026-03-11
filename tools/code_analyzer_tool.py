"""Code analyzer tool — wraps CodeAnalyzer as a BaseTool for the registry."""
from __future__ import annotations

from typing import Any

from tools.base import BaseTool, ToolParameter
from tools.code_analyzer import CodeAnalyzer


class CodeAnalyzerTool(BaseTool):
    """Static source-code vulnerability scanner for white-box CTF solving."""

    name = "code_analyzer"
    description = (
        "Scan a source code directory for common vulnerability patterns "
        "(SQLi, XSS, command injection, path traversal, auth bypass, SSRF, "
        "deserialization). Returns findings with file, line number, and severity. "
        "Useful for white-box challenges where source code is available."
    )
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="Path to the source code directory or repository to scan.",
        ),
    ]

    def __init__(self) -> None:
        self._analyzer = CodeAnalyzer()

    def execute(self, **kwargs: Any) -> str:
        path = kwargs.get("path", "")
        if not path:
            return "[ERROR] 'path' is required."

        analysis = self._analyzer.analyze_directory(path)

        if not analysis["findings"]:
            return (
                f"Scanned {analysis['files_scanned']} {analysis['language']} files. "
                f"No potential vulnerabilities found."
            )

        output = self._analyzer.summary(analysis) + "\n\n"
        output += self._analyzer.format_for_prompt(analysis)
        return output
