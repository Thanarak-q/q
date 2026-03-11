"""Pwntools session tool with persistent Python subprocess.

Wraps pwntools functionality via a persistent Python/pexpect subprocess,
enabling exploit development workflows: connecting to services, sending
payloads, reading responses, and inspecting ELF binaries.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any

from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger

MAX_OUTPUT = 4000
DEFAULT_TIMEOUT = 30
PYTHON_PROMPT = r">>> "


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text)} chars total)"


class PwntoolsSessionTool(BaseTool):
    """Persistent pwntools session for exploit development."""

    name = "pwntools_session"
    description = (
        "Manage a persistent pwntools session for exploit development. "
        "Connect to remote services or local processes, send/receive data, "
        "inspect ELF binaries (checksec, symbols), and find ROP gadgets. "
        "The session persists across calls."
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Pwntools action to perform.",
            enum=[
                "connect",
                "send",
                "sendline",
                "recv",
                "recvuntil",
                "close",
                "elf_info",
                "rop_gadgets",
            ],
        ),
        ToolParameter(
            name="target",
            type="string",
            description=(
                "Connection target: 'host:port' for remote, or path to "
                "binary for process (for 'connect'). "
                "Path to ELF binary (for 'elf_info', 'rop_gadgets')."
            ),
            required=False,
        ),
        ToolParameter(
            name="data",
            type="string",
            description=(
                "Data to send (for 'send', 'sendline'). "
                "Delimiter to wait for (for 'recvuntil'). "
                "Supports \\x hex escapes."
            ),
            required=False,
        ),
        ToolParameter(
            name="mode",
            type="string",
            description="Connection mode: 'remote' (TCP) or 'process' (local binary). Default: 'remote'.",
            required=False,
            enum=["remote", "process"],
        ),
        ToolParameter(
            name="timeout",
            type="string",
            description="Timeout in seconds for recv operations. Default: 5.",
            required=False,
        ),
    ]

    def __init__(self) -> None:
        self._log = get_logger()
        self._proc = None  # pexpect child running Python with pwntools
        self._connected = False

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

    def _start_python(self) -> None:
        """Start persistent Python subprocess with pwntools imported."""
        if self._is_alive():
            return

        pexpect = self._ensure_pexpect()
        self._proc = pexpect.spawn(
            "python3 -u -i -c ''",
            timeout=DEFAULT_TIMEOUT,
            encoding="utf-8",
            maxread=65536,
        )
        self._proc.expect(PYTHON_PROMPT, timeout=10)

        # Import pwntools with context set to avoid noise
        init_cmds = [
            "import warnings; warnings.filterwarnings('ignore')",
            "from pwn import *",
            "context.log_level = 'error'",
            "conn = None",
        ]
        for cmd in init_cmds:
            self._proc.sendline(cmd)
            self._proc.expect(PYTHON_PROMPT, timeout=15)

    def _run_python(self, code: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        """Execute Python code in the persistent subprocess."""
        pexpect = self._ensure_pexpect()
        if not self._is_alive():
            return "[ERROR] Python subprocess not running. Use 'connect' or 'elf_info' first."

        # Wrap multi-line code
        self._proc.sendline(code)
        try:
            self._proc.expect(PYTHON_PROMPT, timeout=timeout)
            output = self._proc.before or ""
            # Strip the echoed command
            lines = output.strip().splitlines()
            if lines and code.strip() in lines[0]:
                lines = lines[1:]
            return _truncate("\n".join(lines).strip())
        except pexpect.TIMEOUT:
            return f"[TIMEOUT] No response within {timeout}s."
        except pexpect.EOF:
            self._proc = None
            self._connected = False
            return "[ERROR] Python subprocess ended unexpectedly."

    def _close_session(self) -> str:
        if self._proc is not None:
            try:
                if self._proc.isalive():
                    self._proc.sendline("exit()")
                    self._proc.expect_exact("", timeout=3)
            except Exception:
                pass
            try:
                self._proc.close(force=True)
            except Exception:
                pass
            self._proc = None
        self._connected = False
        return "Pwntools session closed."

    def __del__(self) -> None:
        self._close_session()

    def execute(self, **kwargs: Any) -> str:
        action: str = kwargs["action"]

        dispatch = {
            "connect": self._connect,
            "send": self._send,
            "sendline": self._sendline,
            "recv": self._recv,
            "recvuntil": self._recvuntil,
            "close": lambda **kw: self._close_session(),
            "elf_info": self._elf_info,
            "rop_gadgets": self._rop_gadgets,
        }

        handler = dispatch.get(action)
        if handler is None:
            return f"[ERROR] Unknown pwntools action: {action}"

        return handler(**kwargs)

    def _connect(self, **kwargs: Any) -> str:
        target = kwargs.get("target", "")
        if not target:
            return "[ERROR] 'target' is required for connect."

        mode = kwargs.get("mode", "remote")
        self._start_python()

        if mode == "remote":
            if ":" not in target:
                return "[ERROR] Remote target must be 'host:port'."
            host, port = target.rsplit(":", 1)
            code = f"conn = remote({repr(host)}, {int(port)})"
        else:
            code = f"conn = process({repr(target)})"

        result = self._run_python(code, timeout=15)
        if "[ERROR]" in result or "[TIMEOUT]" in result:
            return f"[ERROR] Failed to connect: {result}"

        self._connected = True
        return f"Connected to {target} (mode={mode})."

    def _send(self, **kwargs: Any) -> str:
        data = kwargs.get("data", "")
        if not data:
            return "[ERROR] 'data' is required for send."
        if not self._connected:
            return "[ERROR] No active connection. Use 'connect' first."
        # Use raw string to handle hex escapes
        escaped = data.encode("utf-8").decode("unicode_escape") if "\\x" in data else data
        code = f"conn.send({repr(escaped.encode() if isinstance(escaped, str) else escaped)})"
        # Simpler: just pass the string
        code = f"conn.send({repr(data)}.encode() if isinstance({repr(data)}, str) else {repr(data)})"
        # Actually simplest approach: let Python handle it
        code = f"conn.send({repr(data.encode('latin-1'))})"
        result = self._run_python(code)
        if "[ERROR]" in result:
            return result
        return f"Sent {len(data)} bytes."

    def _sendline(self, **kwargs: Any) -> str:
        data = kwargs.get("data", "")
        if not self._connected:
            return "[ERROR] No active connection. Use 'connect' first."
        code = f"conn.sendline({repr(data.encode('latin-1'))})"
        result = self._run_python(code)
        if "[ERROR]" in result:
            return result
        return f"Sent line: {repr(data)}"

    def _recv(self, **kwargs: Any) -> str:
        if not self._connected:
            return "[ERROR] No active connection. Use 'connect' first."
        timeout = kwargs.get("timeout", "5")
        code = f"print(repr(conn.recv(timeout={timeout})))"
        return self._run_python(code, timeout=int(timeout) + 5)

    def _recvuntil(self, **kwargs: Any) -> str:
        if not self._connected:
            return "[ERROR] No active connection. Use 'connect' first."
        delim = kwargs.get("data", "")
        if not delim:
            return "[ERROR] 'data' (delimiter) is required for recvuntil."
        timeout = kwargs.get("timeout", "10")
        code = f"print(repr(conn.recvuntil({repr(delim.encode('latin-1'))}, timeout={timeout})))"
        return self._run_python(code, timeout=int(timeout) + 5)

    def _elf_info(self, **kwargs: Any) -> str:
        target = kwargs.get("target", "")
        if not target:
            return "[ERROR] 'target' (path to ELF) is required."
        import os.path
        if not os.path.isfile(target):
            return f"[ERROR] File not found: {target}"
        self._start_python()
        code = textwrap.dedent(f"""\
            _e = ELF({repr(target)}, checksec=False)
            _info = []
            _info.append(f"Arch: {{_e.arch}}")
            _info.append(f"Bits: {{_e.bits}}")
            _info.append(f"Endian: {{_e.endian}}")
            _info.append(f"OS: {{_e.os}}")
            _cs = {{'RELRO': _e.relro or 'No', 'Stack Canary': bool(_e.canary), 'NX': bool(_e.nx), 'PIE': bool(_e.pie)}}
            _info.append(f"Checksec: {{_cs}}")
            _syms = dict(list(_e.symbols.items())[:30])
            _info.append(f"Symbols (first 30): {{_syms}}")
            _info.append(f"Entry: {{hex(_e.entry)}}")
            print('\\n'.join(_info))""")
        # Send line by line to avoid multiline issues
        lines = code.strip().splitlines()
        # Use exec() to handle multiline
        escaped = code.replace("'", "\\'").replace("\n", "\\n")
        exec_code = f"exec('''{code}''')"
        return self._run_python(exec_code, timeout=15)

    def _rop_gadgets(self, **kwargs: Any) -> str:
        target = kwargs.get("target", "")
        if not target:
            return "[ERROR] 'target' (path to ELF) is required."
        import os.path
        if not os.path.isfile(target):
            return f"[ERROR] File not found: {target}"
        self._start_python()
        code = textwrap.dedent(f"""\
            _e = ELF({repr(target)}, checksec=False)
            _r = ROP(_e)
            print(_r.dump())""")
        exec_code = f"exec('''{code}''')"
        return self._run_python(exec_code, timeout=30)
