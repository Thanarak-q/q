"""Network interaction tools for CTF challenges.

Provides HTTP requests, raw TCP socket connections, and netcat-like
functionality.
"""

from __future__ import annotations

import socket
from typing import Any

import httpx

from config import load_config
from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger


class NetworkTool(BaseTool):
    """Perform network operations for web and pwn challenges."""

    name = "network"
    description = (
        "Perform network requests. Supports HTTP (GET/POST), raw TCP "
        "socket send/receive, and netcat-style interactions. Use "
        "method='http' for web requests or method='tcp' for raw sockets."
    )
    parameters = [
        ToolParameter(
            name="method",
            type="string",
            description="Network method: 'http' or 'tcp'.",
            enum=["http", "tcp"],
        ),
        ToolParameter(
            name="url",
            type="string",
            description="Full URL for HTTP, or 'host:port' for TCP.",
        ),
        ToolParameter(
            name="http_method",
            type="string",
            description="HTTP method (GET, POST, PUT, DELETE). Only for method='http'.",
            required=False,
            enum=["GET", "POST", "PUT", "DELETE"],
        ),
        ToolParameter(
            name="headers",
            type="string",
            description="HTTP headers as JSON string. Only for method='http'.",
            required=False,
        ),
        ToolParameter(
            name="body",
            type="string",
            description="Request body for HTTP POST/PUT, or data to send via TCP.",
            required=False,
        ),
        ToolParameter(
            name="follow_redirects",
            type="boolean",
            description="Follow HTTP redirects. Default true.",
            required=False,
        ),
    ]

    def __init__(self) -> None:
        """Initialise the network tool."""
        cfg = load_config()
        self.timeout = cfg.tool.network_timeout
        self._log = get_logger()

    def execute(self, **kwargs: Any) -> str:
        """Dispatch to HTTP or TCP handler.

        Args:
            **kwargs: Must contain 'method' and 'url'.

        Returns:
            Response data as string.
        """
        method: str = kwargs["method"]
        if method == "http":
            return self._http_request(**kwargs)
        elif method == "tcp":
            return self._tcp_connect(**kwargs)
        return f"[ERROR] Unknown method: {method}"

    def _http_request(self, **kwargs: Any) -> str:
        """Make an HTTP request using httpx.

        Args:
            **kwargs: url, http_method, headers, body, follow_redirects.

        Returns:
            Status code, headers, and body text.
        """
        import json as json_mod

        url: str = kwargs["url"]
        http_method: str = kwargs.get("http_method", "GET").upper()
        raw_headers: str = kwargs.get("headers", "{}")
        body: str | None = kwargs.get("body")
        follow: bool = kwargs.get("follow_redirects", True)

        try:
            headers = json_mod.loads(raw_headers) if raw_headers else {}
        except json_mod.JSONDecodeError:
            headers = {}

        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=follow,
                verify=False,
            ) as client:
                response = client.request(
                    method=http_method,
                    url=url,
                    headers=headers,
                    content=body.encode() if body else None,
                )

            resp_headers = "\n".join(f"  {k}: {v}" for k, v in response.headers.items())
            body_text = response.text
            return (
                f"HTTP {response.status_code}\n"
                f"Headers:\n{resp_headers}\n\n"
                f"Body:\n{body_text}"
            )
        except httpx.TimeoutException:
            return f"[ERROR] HTTP request timed out after {self.timeout}s"
        except httpx.HTTPError as exc:
            return f"[ERROR] HTTP error: {exc}"

    def _tcp_connect(self, **kwargs: Any) -> str:
        """Open a raw TCP connection, send data, receive response.

        Args:
            **kwargs: url (as host:port), body (data to send).

        Returns:
            Received data as string or hex.
        """
        target: str = kwargs["url"]
        data_to_send: str | None = kwargs.get("body")

        # Parse host:port
        if ":" not in target:
            return "[ERROR] TCP target must be in host:port format"
        parts = target.rsplit(":", 1)
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            return f"[ERROR] Invalid port: {parts[1]}"

        try:
            with socket.create_connection((host, port), timeout=self.timeout) as sock:
                if data_to_send:
                    # Support \\n as literal newlines in the payload
                    payload = data_to_send.replace("\\n", "\n").encode()
                    sock.sendall(payload)

                # Receive data
                chunks: list[bytes] = []
                sock.settimeout(min(5.0, self.timeout))
                try:
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
                except socket.timeout:
                    pass  # recv timeout is expected

            received = b"".join(chunks)
            try:
                return received.decode("utf-8", errors="replace")
            except Exception:
                return received.hex()
        except socket.timeout:
            return f"[ERROR] TCP connection timed out after {self.timeout}s"
        except OSError as exc:
            return f"[ERROR] TCP error: {exc}"
