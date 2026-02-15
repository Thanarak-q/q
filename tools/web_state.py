"""Web State Manager for multi-step exploit tracking.

Maintains state across multiple HTTP interactions during web exploitation:
cookies, tokens, registered users, discovered endpoints, and approaches
already tried.  This prevents the agent from repeating failed approaches
and helps it build on previously discovered information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RegisteredUser:
    """A user account created during the exploit."""

    username: str
    password: str
    role: str = "user"
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Endpoint:
    """A discovered endpoint with its properties."""

    path: str
    method: str = "GET"
    auth_required: bool = False
    parameters: list[str] = field(default_factory=list)
    notes: str = ""


class WebState:
    """Track web application state across multi-step exploits.

    This is meant to be instantiated once per solve session and updated
    as the agent interacts with the target.
    """

    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}
        self.tokens: dict[str, str] = {}  # JWT, CSRF, API keys, etc.
        self.registered_users: list[RegisteredUser] = []
        self.endpoints: list[Endpoint] = []
        self.tried_approaches: list[dict[str, Any]] = []
        self.tech_stack: list[str] = []
        self.base_url: str = ""
        self.notes: list[str] = []

    # ------------------------------------------------------------------
    # Cookies & tokens
    # ------------------------------------------------------------------

    def set_cookies(self, cookies: dict[str, str]) -> None:
        """Update tracked cookies."""
        self.cookies.update(cookies)

    def set_token(self, name: str, value: str) -> None:
        """Store a named token (JWT, CSRF, API key, etc.)."""
        self.tokens[name] = value

    def get_auth_header(self) -> dict[str, str]:
        """Build an Authorization header from stored tokens.

        Returns:
            Dict with Authorization header if a JWT/bearer token exists.
        """
        for key in ("jwt", "bearer", "token", "access_token", "authorization"):
            if key in self.tokens:
                val = self.tokens[key]
                if not val.lower().startswith("bearer "):
                    val = f"Bearer {val}"
                return {"Authorization": val}
        return {}

    # ------------------------------------------------------------------
    # Registered users
    # ------------------------------------------------------------------

    def add_user(
        self,
        username: str,
        password: str,
        role: str = "user",
        **extra: str,
    ) -> None:
        """Record a registered user account."""
        self.registered_users.append(
            RegisteredUser(
                username=username,
                password=password,
                role=role,
                extra=dict(extra),
            )
        )

    def get_user(self, role: str = "user") -> RegisteredUser | None:
        """Get a registered user by role."""
        for u in self.registered_users:
            if u.role == role:
                return u
        return self.registered_users[0] if self.registered_users else None

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def add_endpoint(
        self,
        path: str,
        method: str = "GET",
        auth_required: bool = False,
        parameters: list[str] | None = None,
        notes: str = "",
    ) -> None:
        """Record a discovered endpoint."""
        # Avoid duplicates
        for ep in self.endpoints:
            if ep.path == path and ep.method == method:
                if notes and notes not in ep.notes:
                    ep.notes += f"; {notes}"
                return
        self.endpoints.append(
            Endpoint(
                path=path,
                method=method,
                auth_required=auth_required,
                parameters=parameters or [],
                notes=notes,
            )
        )

    def get_endpoints(
        self, auth_required: bool | None = None
    ) -> list[Endpoint]:
        """Get endpoints, optionally filtered by auth requirement."""
        if auth_required is None:
            return list(self.endpoints)
        return [e for e in self.endpoints if e.auth_required == auth_required]

    # ------------------------------------------------------------------
    # Approach tracking
    # ------------------------------------------------------------------

    def record_approach(
        self,
        technique: str,
        target: str,
        payload: str = "",
        result: str = "",
        success: bool = False,
    ) -> None:
        """Record an attempted approach so it won't be retried.

        Args:
            technique: Attack technique name (e.g., "sqli", "ssti").
            target: The endpoint or parameter targeted.
            payload: The payload used.
            result: Brief result description.
            success: Whether the approach worked.
        """
        self.tried_approaches.append({
            "technique": technique,
            "target": target,
            "payload": payload[:200],
            "result": result[:200],
            "success": success,
        })

    def was_tried(self, technique: str, target: str = "") -> bool:
        """Check if a technique was already tried on a target."""
        for a in self.tried_approaches:
            if a["technique"] == technique:
                if not target or a["target"] == target:
                    return True
        return False

    def successful_approaches(self) -> list[dict[str, Any]]:
        """Return only the approaches that succeeded."""
        return [a for a in self.tried_approaches if a.get("success")]

    # ------------------------------------------------------------------
    # State summary (for injection into LLM context)
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Generate a concise state summary for the agent's context.

        Returns:
            Formatted string describing current web state, or "".
        """
        parts: list[str] = []

        if self.base_url:
            parts.append(f"Target: {self.base_url}")

        if self.tech_stack:
            parts.append(f"Tech: {', '.join(self.tech_stack)}")

        if self.cookies:
            cookie_names = list(self.cookies.keys())
            parts.append(f"Cookies: {cookie_names}")

        if self.tokens:
            token_names = list(self.tokens.keys())
            parts.append(f"Tokens: {token_names}")

        if self.registered_users:
            users_info = [
                f"{u.username}:{u.password} ({u.role})"
                for u in self.registered_users
            ]
            parts.append(f"Users: {', '.join(users_info)}")

        if self.endpoints:
            ep_count = len(self.endpoints)
            auth_count = sum(1 for e in self.endpoints if e.auth_required)
            parts.append(
                f"Endpoints: {ep_count} discovered ({auth_count} need auth)"
            )

        if self.tried_approaches:
            tried_summary = []
            for a in self.tried_approaches:
                status = "OK" if a["success"] else "FAIL"
                tried_summary.append(
                    f"{a['technique']}@{a['target']}={status}"
                )
            parts.append(f"Tried: {', '.join(tried_summary)}")

        if self.notes:
            parts.append(f"Notes: {'; '.join(self.notes[-3:])}")

        if not parts:
            return ""

        return "[WEB STATE] " + " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for session persistence."""
        return {
            "base_url": self.base_url,
            "cookies": self.cookies,
            "tokens": self.tokens,
            "tech_stack": self.tech_stack,
            "registered_users": [
                {
                    "username": u.username,
                    "password": u.password,
                    "role": u.role,
                    "extra": u.extra,
                }
                for u in self.registered_users
            ],
            "endpoints": [
                {
                    "path": e.path,
                    "method": e.method,
                    "auth_required": e.auth_required,
                    "parameters": e.parameters,
                    "notes": e.notes,
                }
                for e in self.endpoints
            ],
            "tried_approaches": self.tried_approaches,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebState:
        """Restore state from a serialized dict."""
        state = cls()
        state.base_url = data.get("base_url", "")
        state.cookies = data.get("cookies", {})
        state.tokens = data.get("tokens", {})
        state.tech_stack = data.get("tech_stack", [])
        state.notes = data.get("notes", [])

        for u in data.get("registered_users", []):
            state.registered_users.append(
                RegisteredUser(
                    username=u["username"],
                    password=u["password"],
                    role=u.get("role", "user"),
                    extra=u.get("extra", {}),
                )
            )

        for e in data.get("endpoints", []):
            state.endpoints.append(
                Endpoint(
                    path=e["path"],
                    method=e.get("method", "GET"),
                    auth_required=e.get("auth_required", False),
                    parameters=e.get("parameters", []),
                    notes=e.get("notes", ""),
                )
            )

        state.tried_approaches = data.get("tried_approaches", [])
        return state
