"""Netcat-style TCP/UDP session tool using Python sockets.

Provides simple persistent network connections for CTF challenges
that require raw protocol interaction. No external dependencies
beyond the Python standard library.
"""

from __future__ import annotations

import socket
import select
from typing import Any

from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger

MAX_OUTPUT = 4000
DEFAULT_TIMEOUT = 10
RECV_SIZE = 65536


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text)} chars total)"


class NetcatSessionTool(BaseTool):
    """Simple persistent TCP/UDP session for raw network interaction."""

    name = "netcat_session"
    description = (
        "Manage a persistent TCP or UDP connection for raw network "
        "interaction. Simpler than pwntools — use for basic protocol "
        "communication, banner grabbing, and service interaction in "
        "CTF challenges."
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Netcat action to perform.",
            enum=["connect", "send", "recv", "recv_until", "close"],
        ),
        ToolParameter(
            name="host",
            type="string",
            description="Target hostname or IP (for 'connect').",
            required=False,
        ),
        ToolParameter(
            name="port",
            type="string",
            description="Target port number (for 'connect').",
            required=False,
        ),
        ToolParameter(
            name="data",
            type="string",
            description=(
                "Data to send (for 'send'). "
                "Delimiter to wait for (for 'recv_until'). "
                "Supports \\n for newlines."
            ),
            required=False,
        ),
        ToolParameter(
            name="protocol",
            type="string",
            description="Protocol: 'tcp' (default) or 'udp'.",
            required=False,
            enum=["tcp", "udp"],
        ),
        ToolParameter(
            name="timeout",
            type="string",
            description="Timeout in seconds. Default: 10.",
            required=False,
        ),
    ]

    def __init__(self) -> None:
        self._log = get_logger()
        self._sock: socket.socket | None = None
        self._protocol: str = "tcp"
        self._target: str = ""
        self._buffer: bytes = b""

    def _is_connected(self) -> bool:
        if self._sock is None:
            return False
        try:
            # Check if socket is still valid
            self._sock.getpeername()
            return True
        except (OSError, socket.error):
            self._sock = None
            return False

    def _close_socket(self) -> str:
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self._buffer = b""
        target = self._target
        self._target = ""
        return f"Connection to {target} closed." if target else "No active connection."

    def __del__(self) -> None:
        self._close_socket()

    def execute(self, **kwargs: Any) -> str:
        action: str = kwargs["action"]

        dispatch = {
            "connect": self._connect,
            "send": self._send,
            "recv": self._recv,
            "recv_until": self._recv_until,
            "close": lambda **kw: self._close_socket(),
        }

        handler = dispatch.get(action)
        if handler is None:
            return f"[ERROR] Unknown netcat action: {action}"

        return handler(**kwargs)

    def _connect(self, **kwargs: Any) -> str:
        host = kwargs.get("host", "")
        port_str = kwargs.get("port", "")
        if not host or not port_str:
            return "[ERROR] 'host' and 'port' are required for connect."

        try:
            port = int(port_str)
        except ValueError:
            return f"[ERROR] Invalid port: {port_str}"

        protocol = kwargs.get("protocol", "tcp")
        timeout = float(kwargs.get("timeout", "10"))

        # Close existing connection
        if self._sock is not None:
            self._close_socket()

        self._protocol = protocol

        try:
            if protocol == "tcp":
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(timeout)
                self._sock.connect((host, port))
            else:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._sock.settimeout(timeout)
                self._sock.connect((host, port))

            self._target = f"{host}:{port}"
            self._buffer = b""

            # Try to read any immediate banner
            banner = ""
            try:
                ready, _, _ = select.select([self._sock], [], [], 2)
                if ready:
                    data = self._sock.recv(RECV_SIZE)
                    if data:
                        banner = f"\nBanner:\n{data.decode('utf-8', errors='replace')}"
            except Exception:
                pass

            return f"Connected to {self._target} ({protocol.upper()}).{banner}"

        except socket.timeout:
            self._sock = None
            return f"[ERROR] Connection to {host}:{port} timed out."
        except ConnectionRefusedError:
            self._sock = None
            return f"[ERROR] Connection refused: {host}:{port}"
        except OSError as exc:
            self._sock = None
            return f"[ERROR] Connection failed: {exc}"

    def _send(self, **kwargs: Any) -> str:
        if not self._is_connected():
            return "[ERROR] No active connection. Use 'connect' first."

        data = kwargs.get("data", "")
        if not data:
            return "[ERROR] 'data' is required for send."

        # Process escape sequences
        processed = data.encode("utf-8").decode("unicode_escape").encode("latin-1")

        try:
            self._sock.sendall(processed)
            return f"Sent {len(processed)} bytes to {self._target}."
        except (OSError, socket.error) as exc:
            self._close_socket()
            return f"[ERROR] Send failed (connection lost): {exc}"

    def _recv(self, **kwargs: Any) -> str:
        if not self._is_connected():
            return "[ERROR] No active connection. Use 'connect' first."

        timeout = float(kwargs.get("timeout", "5"))
        self._sock.settimeout(timeout)

        try:
            data = self._sock.recv(RECV_SIZE)
            if not data:
                self._close_socket()
                return "[INFO] Connection closed by remote host."
            text = data.decode("utf-8", errors="replace")
            return _truncate(f"Received {len(data)} bytes:\n{text}")
        except socket.timeout:
            return "[TIMEOUT] No data received within timeout."
        except (OSError, socket.error) as exc:
            self._close_socket()
            return f"[ERROR] Recv failed: {exc}"

    def _recv_until(self, **kwargs: Any) -> str:
        if not self._is_connected():
            return "[ERROR] No active connection. Use 'connect' first."

        delim = kwargs.get("data", "")
        if not delim:
            return "[ERROR] 'data' (delimiter) is required for recv_until."

        timeout = float(kwargs.get("timeout", "10"))
        delim_bytes = delim.encode("utf-8").decode("unicode_escape").encode("latin-1")
        self._sock.settimeout(timeout)

        received = self._buffer
        try:
            while delim_bytes not in received:
                chunk = self._sock.recv(RECV_SIZE)
                if not chunk:
                    self._buffer = b""
                    text = received.decode("utf-8", errors="replace")
                    return _truncate(
                        f"[INFO] Connection closed before delimiter found.\n"
                        f"Received {len(received)} bytes:\n{text}"
                    )
                received += chunk

            idx = received.index(delim_bytes) + len(delim_bytes)
            result = received[:idx]
            self._buffer = received[idx:]
            text = result.decode("utf-8", errors="replace")
            return _truncate(f"Received {len(result)} bytes (until '{delim}'):\n{text}")

        except socket.timeout:
            self._buffer = received
            text = received.decode("utf-8", errors="replace")
            return _truncate(
                f"[TIMEOUT] Delimiter not found within {timeout}s.\n"
                f"Buffered {len(received)} bytes:\n{text}"
            )
        except (OSError, socket.error) as exc:
            self._close_socket()
            return f"[ERROR] Recv failed: {exc}"
