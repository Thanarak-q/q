"""Error analyzer for CTF agent.

Detects common error patterns in tool output and suggests adaptations.
Tracks failed approaches to prevent the agent from repeating them.
"""

from __future__ import annotations


class ErrorAnalyzer:
    """Detect errors in tool output and suggest adaptation strategies."""

    ERROR_PATTERNS: dict[str, dict] = {
        "waf_blocked": {
            "patterns": [
                "403 forbidden", "blocked", "waf",
                "not acceptable", "mod_security",
            ],
            "suggestion": (
                "WAF detected. Try encoding payload: "
                "URL encoding, double encoding, "
                "comment injection (/**/), case variation."
            ),
        },
        "auth_required": {
            "patterns": [
                "401 unauthorized", "login required",
                "not authenticated", "access denied",
            ],
            "suggestion": (
                "Authentication needed. "
                "Try: default credentials, register new account, "
                "bypass auth via SQLi or JWT manipulation."
            ),
        },
        "not_found": {
            "patterns": [
                "404 not found", "no such file",
                "does not exist",
            ],
            "suggestion": (
                "Resource not found. "
                "Check: URL typo? Wrong endpoint? "
                "Try directory enumeration."
            ),
        },
        "connection_error": {
            "patterns": [
                "connection refused", "timeout",
                "unreachable", "econnrefused",
            ],
            "suggestion": (
                "Cannot connect. Check: Is the target running? "
                "Wrong port? Try nmap to find open ports."
            ),
        },
        "syntax_error": {
            "patterns": [
                "syntax error", "parse error",
                "unexpected token",
            ],
            "suggestion": (
                "Syntax error in payload. "
                "Your input is being parsed. "
                "This means injection might work — "
                "fix the payload syntax."
            ),
        },
        "tool_not_found": {
            "patterns": [
                "command not found", "not installed",
                "no such command",
            ],
            "suggestion": (
                "Tool not available. Use an alternative: "
                "tshark→tcpdump, gobuster→dirb, "
                "nikto→curl manual checks."
            ),
        },
    }

    def __init__(self) -> None:
        self._failures: list[str] = []

    def analyze(self, output: str) -> dict[str, str] | None:
        """Analyze tool output for errors.

        Returns:
            {"error_type": "...", "suggestion": "..."} or None.
        """
        output_lower = output.lower()

        for error_type, info in self.ERROR_PATTERNS.items():
            for pattern in info["patterns"]:
                if pattern in output_lower:
                    return {
                        "error_type": error_type,
                        "suggestion": info["suggestion"],
                    }
        return None

    def track_failure(self, approach: str) -> None:
        """Track a failed approach to avoid repeating it."""
        self._failures.append(approach)

    def get_failure_context(self) -> str:
        """Format failed approaches for injection into context."""
        if not self._failures:
            return ""
        return (
            "\nApproaches already tried and FAILED "
            "(do NOT repeat these):\n"
            + "\n".join(f"- {f}" for f in self._failures)
        )

    def reset(self) -> None:
        """Clear failure history (call at start of each solve)."""
        self._failures.clear()
