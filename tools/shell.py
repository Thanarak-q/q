"""Shell command execution tool.

Runs commands inside a Docker container (preferred) or falls back to a
local subprocess when Docker is unavailable.
"""

from __future__ import annotations

import subprocess
from typing import Any, Optional

from config import load_config
from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger


class ShellTool(BaseTool):
    """Execute shell commands for CTF analysis."""

    name = "shell"
    description = (
        "Execute a shell command. Use this for running binaries, "
        "system tools (strings, file, binwalk, objdump, nmap, etc.), "
        "and general UNIX commands. The command runs in a sandboxed "
        "environment with a timeout."
    )
    parameters = [
        ToolParameter(
            name="command",
            type="string",
            description="The shell command to execute.",
        ),
        ToolParameter(
            name="workdir",
            type="string",
            description="Working directory for the command. Defaults to /workspace.",
            required=False,
        ),
    ]

    def __init__(self, docker_manager: Optional[Any] = None) -> None:
        """Initialise the shell tool.

        Args:
            docker_manager: Optional DockerSandbox instance for container execution.
        """
        cfg = load_config()
        self.timeout = cfg.tool.shell_timeout
        self._docker = docker_manager
        self._log = get_logger()

    def execute(self, **kwargs: Any) -> str:
        """Execute a shell command and return its output.

        Args:
            **kwargs: Must contain 'command'. Optional 'workdir'.

        Returns:
            Combined stdout + stderr output.
        """
        command: str = kwargs["command"]
        workdir: str = kwargs.get("workdir", "/workspace")

        # Try Docker first
        if self._docker and self._docker.is_running():
            return self._exec_docker(command, workdir)

        self._log.warning("Docker unavailable, falling back to local subprocess")
        return self._exec_local(command, workdir)

    def _exec_docker(self, command: str, workdir: str) -> str:
        """Run command inside the Docker container.

        Args:
            command: Shell command string.
            workdir: Working directory inside the container.

        Returns:
            Command output.
        """
        assert self._docker is not None
        return self._docker.exec_command(command, workdir=workdir, timeout=self.timeout)

    def _exec_local(self, command: str, workdir: str) -> str:
        """Run command as a local subprocess (fallback).

        Args:
            command: Shell command string.
            workdir: Working directory on the host.

        Returns:
            Combined stdout and stderr.
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=workdir if workdir != "/workspace" else None,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output.strip()
        except subprocess.TimeoutExpired:
            return f"[ERROR] Command timed out after {self.timeout}s"
        except OSError as exc:
            return f"[ERROR] {exc}"
