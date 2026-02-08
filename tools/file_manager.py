"""File management tool for reading, writing, and listing files.

Operates on the workspace directory (inside Docker or on host).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from tools.base import BaseTool, ToolParameter
from utils.file_detector import detect_file_type
from utils.logger import get_logger

_MAX_READ_SIZE = 100_000  # 100 KB text read limit


class FileManagerTool(BaseTool):
    """Read, write, and list files in the workspace."""

    name = "file_manager"
    description = (
        "Manage files in the workspace. Supports reading file contents, "
        "writing new files, listing directory contents, and detecting "
        "file types. Use action='read' | 'write' | 'list' | 'detect'."
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="One of: read, write, list, detect.",
            enum=["read", "write", "list", "detect"],
        ),
        ToolParameter(
            name="path",
            type="string",
            description="File or directory path (relative to workspace root).",
        ),
        ToolParameter(
            name="content",
            type="string",
            description="Content to write (only for action='write').",
            required=False,
        ),
    ]

    def __init__(
        self,
        workspace: Path | None = None,
        docker_manager: Optional[Any] = None,
    ) -> None:
        """Initialise the file manager.

        Args:
            workspace: Host-side workspace directory.
            docker_manager: Optional DockerSandbox instance.
        """
        self._workspace = workspace or Path.cwd()
        self._docker = docker_manager
        self._log = get_logger()
        self.timeout = 10

    def _resolve(self, rel_path: str) -> Path:
        """Resolve a relative path against the workspace root.

        Args:
            rel_path: Relative file path.

        Returns:
            Absolute Path within the workspace.
        """
        resolved = (self._workspace / rel_path).resolve()
        # Prevent path traversal outside workspace
        if not str(resolved).startswith(str(self._workspace.resolve())):
            raise ValueError(f"Path traversal detected: {rel_path}")
        return resolved

    def execute(self, **kwargs: Any) -> str:
        """Dispatch to the appropriate file action.

        Args:
            **kwargs: Must include 'action' and 'path'. 'content' for write.

        Returns:
            Result string.
        """
        action: str = kwargs["action"]
        path_str: str = kwargs["path"]

        if action == "read":
            return self._read(path_str)
        elif action == "write":
            content: str = kwargs.get("content", "")
            return self._write(path_str, content)
        elif action == "list":
            return self._list(path_str)
        elif action == "detect":
            return self._detect(path_str)
        else:
            return f"[ERROR] Unknown action: {action}"

    def _read(self, rel_path: str) -> str:
        """Read file contents as text.

        Args:
            rel_path: Relative path to the file.

        Returns:
            File contents or error message.
        """
        fpath = self._resolve(rel_path)
        if not fpath.exists():
            return f"[ERROR] File not found: {rel_path}"
        if not fpath.is_file():
            return f"[ERROR] Not a regular file: {rel_path}"

        try:
            data = fpath.read_bytes()
            if len(data) > _MAX_READ_SIZE:
                text = data[:_MAX_READ_SIZE].decode("utf-8", errors="replace")
                return text + f"\n\n[TRUNCATED at {_MAX_READ_SIZE} bytes]"
            return data.decode("utf-8", errors="replace")
        except OSError as exc:
            return f"[ERROR] {exc}"

    def _write(self, rel_path: str, content: str) -> str:
        """Write content to a file.

        Args:
            rel_path: Relative path to write to.
            content: Text content.

        Returns:
            Success or error message.
        """
        fpath = self._resolve(rel_path)
        try:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")
            return f"Written {len(content)} bytes to {rel_path}"
        except OSError as exc:
            return f"[ERROR] {exc}"

    def _list(self, rel_path: str) -> str:
        """List directory contents.

        Args:
            rel_path: Relative directory path.

        Returns:
            Newline-separated listing with type indicators.
        """
        dpath = self._resolve(rel_path)
        if not dpath.exists():
            return f"[ERROR] Directory not found: {rel_path}"
        if not dpath.is_dir():
            return f"[ERROR] Not a directory: {rel_path}"

        entries: list[str] = []
        try:
            for item in sorted(dpath.iterdir()):
                prefix = "d " if item.is_dir() else "f "
                size = ""
                if item.is_file():
                    size = f"  ({item.stat().st_size} bytes)"
                entries.append(f"{prefix}{item.name}{size}")
        except OSError as exc:
            return f"[ERROR] {exc}"

        if not entries:
            return "(empty directory)"
        return "\n".join(entries)

    def _detect(self, rel_path: str) -> str:
        """Detect file type.

        Args:
            rel_path: Relative file path.

        Returns:
            File type description.
        """
        fpath = self._resolve(rel_path)
        return detect_file_type(fpath)
