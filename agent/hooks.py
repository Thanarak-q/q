"""YAML-configured hook system for tool execution safety and extensibility.

Provides pre/post hooks for tool calls, solve completion, and flag discovery.
Hooks are configured via YAML and support:
- Pre-tool-call blocking (regex-based command filtering)
- Pre-answer stop hooks (verify work before declaring victory)
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
class StopHookAction:
    """A stop hook that verifies work before the agent returns an answer."""
    check: str = ""           # "flag_format" | "flag_discriminator" | "shell"
    run: str = ""             # shell command (for check="shell")
    message: str = ""         # feedback message when check fails
    flag_pattern: str = ""    # regex for flag_format check


@dataclass
class HooksConfig:
    """Parsed hooks configuration."""
    pre_tool_call: list[HookAction] = field(default_factory=list)
    pre_answer: list[StopHookAction] = field(default_factory=list)
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
            or bool(self._config.pre_answer)
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
            pre_answer=cls._parse_stop_hooks(hooks_data.get("pre_answer", [])),
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

    @staticmethod
    def _parse_stop_hooks(items: list[dict[str, Any]]) -> list[StopHookAction]:
        """Parse a list of stop hook dicts into StopHookAction objects."""
        actions = []
        for item in items or []:
            if isinstance(item, dict):
                actions.append(StopHookAction(
                    check=item.get("check", ""),
                    run=item.get("run", ""),
                    message=item.get("message", "Stop hook rejected the answer"),
                    flag_pattern=item.get("flag_pattern", ""),
                ))
        return actions

    def pre_answer(self, answer: str, flag: str, custom_flag_pattern: str = "") -> tuple[bool, str]:
        """Run pre-answer stop hooks. Returns (ok, feedback).

        Returns (True, "") if the answer is accepted.
        Returns (False, feedback) if a hook rejects the answer.
        """
        if not self._enabled or not self._config.pre_answer:
            return True, ""

        for hook in self._config.pre_answer:
            if hook.check == "flag_format":
                # Verify flag matches expected format
                pattern = hook.flag_pattern or custom_flag_pattern
                if pattern and flag:
                    try:
                        if not re.search(pattern, flag):
                            return False, (
                                hook.message or
                                f"Flag '{flag}' does not match expected format: {pattern}"
                            )
                    except re.error:
                        pass
                elif not flag and custom_flag_pattern:
                    return False, (
                        hook.message or
                        "Answer has no flag but a flag format was specified. "
                        "Continue looking for the flag."
                    )

            elif hook.check == "flag_discriminator":
                # Use the FlagDiscriminator for validation
                if flag:
                    try:
                        from agent.flag_discriminator import FlagDiscriminator
                        disc = FlagDiscriminator(custom_pattern=custom_flag_pattern)
                        verdict = disc.validate(flag)
                        if not verdict.is_valid:
                            return False, (
                                hook.message or
                                f"Flag discriminator rejected: {verdict.reason}"
                            )
                    except Exception as exc:
                        self._log.debug(f"Flag discriminator hook failed: {exc}")

            elif hook.check == "shell":
                # Run a shell command; exit code 0 = ok, non-zero = reject
                if hook.run:
                    cmd = hook.run
                    cmd = cmd.replace("{answer}", shlex.quote(answer))
                    cmd = cmd.replace("{flag}", shlex.quote(flag or ""))
                    try:
                        result = subprocess.run(
                            cmd,
                            shell=True,
                            timeout=10,
                            capture_output=True,
                            text=True,
                        )
                        if result.returncode != 0:
                            feedback = result.stdout.strip() or result.stderr.strip() or hook.message
                            return False, feedback
                    except subprocess.TimeoutExpired:
                        self._log.warning(f"Stop hook timed out: {cmd[:80]}")
                    except Exception as exc:
                        self._log.warning(f"Stop hook failed: {cmd[:80]} — {exc}")

        return True, ""

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
