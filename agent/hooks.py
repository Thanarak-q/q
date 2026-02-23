"""YAML-configured hook system for tool execution safety and extensibility.

Provides pre/post hooks for tool calls, solve completion, and flag discovery.
Hooks are configured via YAML and support:
- Pre-tool-call blocking (regex-based command filtering)
- Post-solve shell commands (notifications, logging)
- Post-flag shell commands (auto-submission)
"""
from __future__ import annotations

import fnmatch
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


@dataclass
class HookAction:
    """A single hook action definition."""
    match: str = "*"          # fnmatch pattern for tool name
    block_if: str = ""        # regex pattern to block (pre_tool_call only)
    message: str = ""         # message to show when blocked
    run: str = ""             # shell command to execute


@dataclass
class HooksConfig:
    """Parsed hooks configuration."""
    pre_tool_call: list[HookAction] = field(default_factory=list)
    post_solve: list[HookAction] = field(default_factory=list)
    post_flag: list[HookAction] = field(default_factory=list)


class HookEngine:
    """Executes configured hooks at key agent lifecycle points.

    Fast no-op path when no hooks are configured (_enabled=False).
    """

    def __init__(self, config: HooksConfig | None = None) -> None:
        self._log = get_logger()
        self._config = config or HooksConfig()
        self._enabled = config is not None and (
            bool(self._config.pre_tool_call)
            or bool(self._config.post_solve)
            or bool(self._config.post_flag)
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "HookEngine":
        """Load hooks from a YAML file. Returns no-op engine if missing."""
        path = Path(path)
        if not path.exists():
            return cls()

        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            get_logger().warning(f"Failed to load hooks from {path}: {exc}")
            return cls()

        hooks_data = data.get("hooks", data)  # support both top-level and nested
        config = HooksConfig(
            pre_tool_call=cls._parse_actions(hooks_data.get("pre_tool_call", [])),
            post_solve=cls._parse_actions(hooks_data.get("post_solve", [])),
            post_flag=cls._parse_actions(hooks_data.get("post_flag", [])),
        )
        return cls(config=config)

    @staticmethod
    def _parse_actions(items: list[dict[str, Any]]) -> list[HookAction]:
        """Parse a list of action dicts into HookAction objects."""
        actions = []
        for item in items or []:
            if isinstance(item, dict):
                actions.append(HookAction(
                    match=item.get("match", "*"),
                    block_if=item.get("block_if", ""),
                    message=item.get("message", "Blocked by hook"),
                    run=item.get("run", ""),
                ))
        return actions

    def pre_tool_call(self, tool_name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Check pre-tool-call hooks. Returns (allowed, message).

        Returns (True, "") if allowed, (False, message) if blocked.
        """
        if not self._enabled:
            return True, ""

        args_str = str(args)
        for action in self._config.pre_tool_call:
            if not fnmatch.fnmatch(tool_name, action.match):
                continue
            if action.block_if:
                try:
                    if re.search(action.block_if, args_str):
                        self._log.warning(
                            f"Hook blocked {tool_name}: {action.message}"
                        )
                        return False, action.message or "Blocked by pre_tool_call hook"
                except re.error:
                    pass
        return True, ""

    def post_solve(self, status: str, flags: list[str], cost: float, steps: int) -> None:
        """Run post-solve hooks."""
        if not self._enabled:
            return
        for action in self._config.post_solve:
            if action.run:
                cmd = action.run
                cmd = cmd.replace("{status}", shlex.quote(status))
                cmd = cmd.replace("{flags}", shlex.quote(",".join(flags)))
                cmd = cmd.replace("{cost}", shlex.quote(f"{cost:.4f}"))
                cmd = cmd.replace("{steps}", shlex.quote(str(steps)))
                self._run_shell(cmd)

    def post_flag(self, flag: str) -> None:
        """Run post-flag hooks."""
        if not self._enabled:
            return
        for action in self._config.post_flag:
            if action.run:
                cmd = action.run.replace("{flag}", shlex.quote(flag))
                self._run_shell(cmd)

    def _run_shell(self, cmd: str, timeout: int = 10) -> None:
        """Execute a shell command (best-effort, non-blocking)."""
        try:
            self._log.debug(f"Hook running: {cmd}")
            subprocess.run(
                cmd,
                shell=True,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            self._log.warning(f"Hook timed out: {cmd[:80]}")
        except Exception as exc:
            self._log.warning(f"Hook failed: {cmd[:80]} — {exc}")
