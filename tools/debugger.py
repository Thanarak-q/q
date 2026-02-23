"""GDB debugger tool with persistent session via pexpect.

Provides interactive debugging capabilities for binary exploitation
CTF challenges. Maintains a persistent gdb subprocess across agent
iterations.
"""

from __future__ import annotations

import shutil
from typing import Any

from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger

MAX_OUTPUT = 4000
GDB_PROMPT = r"\(gdb\)"
DEFAULT_TIMEOUT = 30


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text)} chars total)"


class DebuggerTool(BaseTool):
    """Interactive GDB debugger for binary analysis and exploitation."""

    name = "debugger"
    description = (
        "Control an interactive GDB session for debugging binaries. "
        "Use for setting breakpoints, stepping through code, examining "
        "memory and registers, and analyzing binary exploitation challenges. "
        "The session persists across calls."
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Debugger action to perform.",
            enum=[
                "start",
                "breakpoint",
                "run",
                "step",
                "next",
                "continue",
                "print",
                "backtrace",
                "examine",
                "info_registers",
                "raw_command",
                "close",
            ],
        ),
        ToolParameter(
            name="binary",
            type="string",
            description="Path to binary to debug (for 'start' action).",
            required=False,
        ),
        ToolParameter(
            name="args",
            type="string",
            description=(
                "Arguments for the binary (for 'start'), "
                "breakpoint location (for 'breakpoint'), "
                "expression (for 'print'), "
                "address/format (for 'examine'), "
                "or raw GDB command (for 'raw_command')."
            ),
            required=False,
        ),
    ]

    def __init__(self) -> None:
        self._log = get_logger()
        self._proc = None

    def _ensure_pexpect(self):
        try:
            import pexpect
            return pexpect
        except ImportError:
            raise RuntimeError(
                "pexpect is not installed. Install with: pip install pexpect"
            )

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.isalive()

    def _send_command(self, cmd: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        """Send a command to gdb and return the output."""
        pexpect = self._ensure_pexpect()
        if not self._is_alive():
            return "[ERROR] No active GDB session. Use 'start' first."

        self._proc.sendline(cmd)
        try:
            self._proc.expect(GDB_PROMPT, timeout=timeout)
            output = self._proc.before
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            # Strip the echoed command from the beginning
            lines = output.strip().splitlines()
            if lines and cmd in lines[0]:
                lines = lines[1:]
            return _truncate("\n".join(lines).strip())
        except pexpect.TIMEOUT:
            return f"[TIMEOUT] GDB did not respond within {timeout}s. The program may be running or waiting for input."
        except pexpect.EOF:
            self._proc = None
            return "[ERROR] GDB session ended unexpectedly."

    def _close(self) -> str:
        if self._proc is not None:
            try:
                if self._proc.isalive():
                    self._proc.sendline("quit")
                    self._proc.expect_exact("", timeout=3)
            except Exception:
                pass
            try:
                self._proc.close(force=True)
            except Exception:
                pass
            self._proc = None
        return "GDB session closed."

    def __del__(self) -> None:
        self._close()

    def execute(self, **kwargs: Any) -> str:
        action: str = kwargs["action"]

        dispatch = {
            "start": self._start,
            "breakpoint": self._breakpoint,
            "run": self._run,
            "step": self._step,
            "next": self._next,
            "continue": self._continue,
            "print": self._print,
            "backtrace": self._backtrace,
            "examine": self._examine,
            "info_registers": self._info_registers,
            "raw_command": self._raw_command,
            "close": lambda **kw: self._close(),
        }

        handler = dispatch.get(action)
        if handler is None:
            return f"[ERROR] Unknown debugger action: {action}"

        return handler(**kwargs)

    def _start(self, **kwargs: Any) -> str:
        pexpect = self._ensure_pexpect()
        binary = kwargs.get("binary", "")
        if not binary:
            return "[ERROR] 'binary' is required for start action."

        # Close existing session
        if self._is_alive():
            self._close()

        gdb_path = shutil.which("gdb")
        if not gdb_path:
            return "[ERROR] gdb is not installed or not in PATH."

        args_str = kwargs.get("args", "")
        cmd = f"gdb -q {binary}"
        if args_str:
            cmd = f"gdb -q --args {binary} {args_str}"

        try:
            self._proc = pexpect.spawn(cmd, timeout=DEFAULT_TIMEOUT, encoding="utf-8")
            self._proc.expect(GDB_PROMPT, timeout=DEFAULT_TIMEOUT)
            output = self._proc.before or ""
            return _truncate(f"GDB session started for: {binary}\n{output.strip()}")
        except pexpect.TIMEOUT:
            self._close()
            return "[ERROR] GDB startup timed out."
        except Exception as exc:
            self._close()
            return f"[ERROR] Failed to start GDB: {exc}"

    def _breakpoint(self, **kwargs: Any) -> str:
        location = kwargs.get("args", "")
        if not location:
            return "[ERROR] 'args' (breakpoint location) is required."
        return self._send_command(f"break {location}")

    def _run(self, **kwargs: Any) -> str:
        args_str = kwargs.get("args", "")
        cmd = f"run {args_str}" if args_str else "run"
        return self._send_command(cmd, timeout=60)

    def _step(self, **kwargs: Any) -> str:
        return self._send_command("step")

    def _next(self, **kwargs: Any) -> str:
        return self._send_command("next")

    def _continue(self, **kwargs: Any) -> str:
        return self._send_command("continue", timeout=60)

    def _print(self, **kwargs: Any) -> str:
        expr = kwargs.get("args", "")
        if not expr:
            return "[ERROR] 'args' (expression) is required for print."
        return self._send_command(f"print {expr}")

    def _backtrace(self, **kwargs: Any) -> str:
        return self._send_command("backtrace")

    def _examine(self, **kwargs: Any) -> str:
        addr = kwargs.get("args", "")
        if not addr:
            return "[ERROR] 'args' (address/format) is required for examine."
        return self._send_command(f"x {addr}")

    def _info_registers(self, **kwargs: Any) -> str:
        return self._send_command("info registers")

    def _raw_command(self, **kwargs: Any) -> str:
        cmd = kwargs.get("args", "")
        if not cmd:
            return "[ERROR] 'args' (GDB command) is required for raw_command."
        return self._send_command(cmd)
