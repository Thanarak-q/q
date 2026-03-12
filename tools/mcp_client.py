"""MCP (Model Context Protocol) client — connects to external MCP servers.

Implements the MCP JSON-RPC 2.0 protocol for stdio-based servers.
Discovers tools from MCP servers and wraps them as BaseTool instances
that can be registered in the ToolRegistry.

MCP spec: https://spec.modelcontextprotocol.io/

Usage:
    client = MCPClient("uvx", ["mcp-server-sqlite", "--db-path", "test.db"])
    client.connect()
    tools = client.list_tools()
    result = client.call_tool("query", {"sql": "SELECT 1"})
    client.close()
"""
from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

from tools.base import BaseTool, ToolParameter, ToolResult
from utils.logger import get_logger

_log = get_logger()


@dataclass
class MCPToolSchema:
    """Schema for a tool discovered from an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


class MCPClient:
    """Client for stdio-based MCP servers using JSON-RPC 2.0."""

    def __init__(self, command: str, args: list[str] | None = None) -> None:
        self._command = command
        self._args = args or []
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._tools: list[MCPToolSchema] = []
        self._server_info: dict[str, Any] = {}

    def connect(self, timeout: int = 10) -> bool:
        """Start the MCP server process and initialize the session.

        Returns True if connection succeeded.
        """
        try:
            self._process = subprocess.Popen(
                [self._command, *self._args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            _log.error(f"MCP server command not found: {self._command}")
            return False
        except OSError as exc:
            _log.error(f"Failed to start MCP server: {exc}")
            return False

        # Send initialize request
        init_result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "q-ctf-agent",
                "version": "1.1.0",
            },
        })

        if init_result is None:
            self.close()
            return False

        self._server_info = init_result
        _log.info(f"MCP connected to: {init_result.get('serverInfo', {}).get('name', 'unknown')}")

        # Send initialized notification
        self._send_notification("notifications/initialized", {})
        return True

    def list_tools(self) -> list[MCPToolSchema]:
        """Discover tools from the MCP server."""
        result = self._send_request("tools/list", {})
        if result is None:
            return []

        self._tools = []
        for tool_data in result.get("tools", []):
            schema = MCPToolSchema(
                name=tool_data.get("name", ""),
                description=tool_data.get("description", ""),
                input_schema=tool_data.get("inputSchema", {}),
            )
            self._tools.append(schema)

        _log.info(f"MCP discovered {len(self._tools)} tool(s)")
        return self._tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server.

        Returns:
            {"content": [...], "isError": bool}
        """
        result = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if result is None:
            return {"content": [{"type": "text", "text": "MCP call failed"}], "isError": True}
        return result

    def close(self) -> None:
        """Shut down the MCP server process."""
        if self._process:
            try:
                self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC request and wait for response."""
        with self._lock:
            if not self._process or self._process.poll() is not None:
                _log.error("MCP server process not running")
                return None

            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            }

            try:
                line = json.dumps(request) + "\n"
                self._process.stdin.write(line)
                self._process.stdin.flush()

                # Read response line
                response_line = self._process.stdout.readline()
                if not response_line:
                    _log.error("MCP server closed connection")
                    return None

                response = json.loads(response_line)
                if "error" in response:
                    error = response["error"]
                    _log.error(f"MCP error: {error.get('message', 'unknown')}")
                    return None

                return response.get("result")

            except json.JSONDecodeError as exc:
                _log.error(f"MCP invalid JSON response: {exc}")
                return None
            except OSError as exc:
                _log.error(f"MCP I/O error: {exc}")
                return None

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        with self._lock:
            if not self._process or self._process.poll() is not None:
                return

            notification = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }

            try:
                line = json.dumps(notification) + "\n"
                self._process.stdin.write(line)
                self._process.stdin.flush()
            except OSError:
                pass


class MCPBridgeTool(BaseTool):
    """Wraps an MCP server's tools as a single BaseTool for the registry.

    Dynamically discovers tools from the MCP server and exposes them
    via a unified interface.
    """

    name = "mcp"
    description = (
        "Call external tools via MCP (Model Context Protocol) servers. "
        "Specify the server name and tool name to invoke."
    )
    parameters = [
        ToolParameter(
            name="server",
            type="string",
            description="MCP server name (as configured in settings).",
        ),
        ToolParameter(
            name="tool",
            type="string",
            description="Tool name to call on the server.",
        ),
        ToolParameter(
            name="arguments",
            type="string",
            description="JSON string of arguments to pass to the tool.",
            required=False,
        ),
    ]

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._tool_cache: dict[str, list[MCPToolSchema]] = {}

    def add_server(self, name: str, command: str, args: list[str] | None = None) -> bool:
        """Add and connect to an MCP server.

        Returns True if connection succeeded.
        """
        client = MCPClient(command, args)
        if client.connect():
            self._clients[name] = client
            self._tool_cache[name] = client.list_tools()
            return True
        return False

    def execute(
        self,
        server: str = "",
        tool: str = "",
        arguments: str = "{}",
        **kwargs: Any,
    ) -> str:
        """Execute an MCP tool call."""
        client = self._clients.get(server)
        if client is None:
            available = ", ".join(self._clients.keys()) if self._clients else "none"
            return f"MCP server '{server}' not connected. Available: {available}"

        # Validate tool exists
        known_tools = self._tool_cache.get(server, [])
        tool_names = [t.name for t in known_tools]
        if tool not in tool_names:
            return f"Tool '{tool}' not found on server '{server}'. Available: {', '.join(tool_names)}"

        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"Invalid JSON arguments: {arguments}"

        result = client.call_tool(tool, args)

        # Format response
        is_error = result.get("isError", False)
        content_parts = result.get("content", [])
        text_parts = []
        for part in content_parts:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif isinstance(part, str):
                text_parts.append(part)

        output = "\n".join(text_parts) if text_parts else str(result)
        if is_error:
            output = f"[MCP ERROR] {output}"
        return output

    def get_available_tools(self) -> dict[str, list[str]]:
        """Return a map of server -> tool names."""
        return {
            name: [t.name for t in tools]
            for name, tools in self._tool_cache.items()
        }

    def close_all(self) -> None:
        """Disconnect from all MCP servers."""
        for client in self._clients.values():
            client.close()
        self._clients.clear()
        self._tool_cache.clear()

    def __del__(self) -> None:
        self.close_all()
