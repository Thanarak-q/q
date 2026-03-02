"""Shell command execution tool.

Runs commands inside a Docker container (preferred) or falls back to a
local subprocess when Docker is unavailable.
"""

from __future__ import annotations

import re
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
        command: str = kwargs["command"].strip()
        workdir: str = kwargs.get("workdir", "/workspace")

        blocked = self._interactive_block_message(command)
        if blocked:
            return blocked

        prepared, prep_note = self._prepare_non_interactive(command)
        output = self._run_once(prepared, workdir=workdir, timeout=self.timeout)

        notes: list[str] = []
        if prep_note:
            notes.append(f"[policy] {prep_note}")

        if self._needs_recovery(output):
            recovery = self._recovery_command(command)
            if recovery and recovery != prepared:
                recovered = self._run_once(
                    recovery,
                    workdir=workdir,
                    timeout=min(self.timeout, 15),
                )
                notes.append(
                    f"[auto-recovery] Retried as non-interactive command: {recovery}"
                )
                output = f"{output}\n\n[auto-recovery output]\n{recovered}"

        if notes:
            return "\n".join(notes + [output]).strip()
        return output

    def _run_once(self, command: str, workdir: str, timeout: int) -> str:
        """Execute exactly one command invocation."""
        # Try Docker first
        if self._docker and self._docker.is_running():
            return self._exec_docker(command, workdir, timeout=timeout)

        self._log.warning("Docker unavailable, falling back to local subprocess")
        return self._exec_local(command, workdir, timeout=timeout)

    def _exec_docker(self, command: str, workdir: str, timeout: int) -> str:
        """Run command inside the Docker container.

        Args:
            command: Shell command string.
            workdir: Working directory inside the container.
            timeout: Command timeout in seconds.

        Returns:
            Command output.
        """
        assert self._docker is not None
        return self._docker.exec_command(command, workdir=workdir, timeout=timeout)

    def _exec_local(self, command: str, workdir: str, timeout: int) -> str:
        """Run command as a local subprocess (fallback).

        Args:
            command: Shell command string.
            workdir: Working directory on the host.
            timeout: Command timeout in seconds.

        Returns:
            Combined stdout and stderr.
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir if workdir != "/workspace" else None,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output.strip()
        except subprocess.TimeoutExpired:
            return f"[ERROR] Command timed out after {timeout}s"
        except OSError as exc:
            return f"[ERROR] {exc}"

    @staticmethod
    def _interactive_block_message(command: str) -> str | None:
        """Block obvious interactive TUI commands that hang automation."""
        parts = command.split()
        if not parts:
            return None

        idx = 1 if parts[0] == "sudo" and len(parts) > 1 else 0
        base = parts[idx]
        blocked = {
            "vi",
            "vim",
            "nano",
            "less",
            "more",
            "man",
            "top",
            "htop",
            "tmux",
            "screen",
        }
        if base in blocked:
            return (
                f"[POLICY] Interactive command '{base}' blocked. "
                "Use non-interactive alternatives (cat, grep, sed, head, tail)."
            )
        return None

    @staticmethod
    def _prepare_non_interactive(command: str) -> tuple[str, str]:
        """Best-effort rewrite for non-interactive execution."""
        cmd = command.strip()

        if re.match(r"^(sudo\s+)?apt(-get)?\s+install\b", cmd) and " -y" not in cmd:
            return f"{cmd} -y", "Added '-y' for non-interactive package install."

        if re.match(r"^unzip\b", cmd) and " -P " not in f" {cmd} ":
            return (
                f"{cmd} -o -P ''",
                "Added unzip non-interactive flags (-o and empty -P).",
            )

        if re.match(r"^7z\s+x\b", cmd) and " -y" not in cmd:
            return f"{cmd} -y", "Added '-y' for non-interactive 7z extraction."

        return cmd, ""

    @staticmethod
    def _needs_recovery(output: str) -> bool:
        """Detect likely prompt/timeouts that warrant auto-recovery."""
        if "[ERROR] Command timed out" in output or "[TIMEOUT" in output:
            return True

        prompt_patterns = (
            r"enter password",
            r"password:",
            r"passphrase",
            r"do you want to continue\?",
            r"overwrite\?",
            r"\[Y/n\]|\[y/N\]",
        )
        return any(re.search(p, output, flags=re.IGNORECASE) for p in prompt_patterns)

    @staticmethod
    def _recovery_command(command: str) -> str | None:
        """Build a one-shot non-interactive fallback command."""
        cmd = command.strip()
        if re.match(r"^unzip\b", cmd) and " -P " not in f" {cmd} ":
            return f"{cmd} -o -P ''"
        if re.match(r"^7z\s+x\b", cmd) and " -y" not in cmd:
            return f"{cmd} -y"
        if re.match(r"^(sudo\s+)?apt(-get)?\s+install\b", cmd) and " -y" not in cmd:
            return f"{cmd} -y"
        return None
