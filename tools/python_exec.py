"""Python code execution tool.

Writes Python code to a temp file and runs it inside the Docker sandbox
(or locally as a fallback).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from config import load_config
from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger


class PythonExecTool(BaseTool):
    """Execute Python code snippets for CTF solving."""

    name = "python_exec"
    description = (
        "Execute a Python 3 code snippet. Useful for crypto calculations, "
        "data manipulation, exploit scripting, encoding/decoding, and "
        "pwntools interactions. The code is written to a temp file and "
        "executed with a timeout."
    )
    parameters = [
        ToolParameter(
            name="code",
            type="string",
            description="Python 3 source code to execute.",
        ),
        ToolParameter(
            name="args",
            type="string",
            description="Optional command-line arguments to pass to the script.",
            required=False,
        ),
    ]

    def __init__(self, docker_manager: Optional[Any] = None) -> None:
        """Initialise the Python execution tool.

        Args:
            docker_manager: Optional DockerSandbox for container-based execution.
        """
        cfg = load_config()
        self.timeout = cfg.tool.python_timeout
        self._docker = docker_manager
        self._log = get_logger()

    def execute(self, **kwargs: Any) -> str:
        """Execute Python code and return stdout/stderr.

        Args:
            **kwargs: Must contain 'code'. Optional 'args'.

        Returns:
            Combined stdout and stderr.
        """
        code: str = kwargs["code"]
        args: str = kwargs.get("args", "")

        if self._docker and self._docker.is_running():
            return self._exec_docker(code, args)

        self._log.warning("Docker unavailable, executing Python locally")
        return self._exec_local(code, args)

    def _exec_docker(self, code: str, args: str) -> str:
        """Run Python code inside the Docker container.

        Args:
            code: Python source code.
            args: CLI arguments string.

        Returns:
            Script output.
        """
        assert self._docker is not None
        # Write code into the container workspace
        script_name = "_ctf_exec.py"
        self._docker.write_file(f"/workspace/{script_name}", code)
        cmd = f"cd /workspace && python3 {script_name}"
        if args:
            cmd += f" {args}"
        return self._docker.exec_command(cmd, timeout=self.timeout)

    def _exec_local(self, code: str, args: str) -> str:
        """Run Python code as a local subprocess.

        Args:
            code: Python source code.
            args: CLI arguments string.

        Returns:
            Combined stdout and stderr.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, prefix="ctf_"
        ) as tmp:
            tmp.write(code)
            tmp_path = Path(tmp.name)

        try:
            cmd_list = ["python3", str(tmp_path)]
            if args:
                import shlex
                cmd_list.extend(shlex.split(args))
            result = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output.strip()
        except subprocess.TimeoutExpired:
            return f"[ERROR] Python script timed out after {self.timeout}s"
        except OSError as exc:
            return f"[ERROR] {exc}"
        finally:
            tmp_path.unlink(missing_ok=True)
