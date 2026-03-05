"""LLM interaction tool for AI security CTF challenges.

Provides a dedicated interface for interacting with target AI systems —
sending prompts, maintaining multi-turn conversations, and analyzing
responses for leaked secrets or flags.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from config import load_config
from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger


# Common flag patterns to detect in responses
_FLAG_PATTERNS = [
    re.compile(r"flag\{[^}]+\}", re.IGNORECASE),
    re.compile(r"ctf\{[^}]+\}", re.IGNORECASE),
    re.compile(r"NCSA\{[^}]+\}"),
    re.compile(r"FLAG\{[^}]+\}"),
    re.compile(r"(?:the\s+(?:secret|password|key|flag)\s+is)[:\s]+(.{3,80})", re.IGNORECASE),
]


class LLMInteractTool(BaseTool):
    """Interact with target AI/LLM systems for AI security challenges.

    Supports single prompts and multi-turn conversations with automatic
    session tracking and response analysis.
    """

    name = "llm_interact"
    description = (
        "Interact with a target AI/LLM system. Use for AI security challenges "
        "that involve prompt injection, jailbreaking, or secret extraction. "
        "Supports single prompts, multi-turn conversations, automated payload "
        "spraying, and response analysis. Tracks request count per target."
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description=(
                "Action to perform. 'spray' cycles through pre-built prompt injection "
                "payloads automatically and returns the first response containing a flag. "
                "'auto_attack' runs an escalating sequence of attacks."
            ),
            enum=[
                "send_prompt",
                "multi_turn",
                "spray",
                "auto_attack",
                "analyze_response",
                "reset_session",
                "show_history",
            ],
        ),
        ToolParameter(
            name="target_url",
            type="string",
            description=(
                "Target AI endpoint URL (e.g. 'http://target/api/chat'). "
                "Required for send_prompt and multi_turn."
            ),
            required=False,
        ),
        ToolParameter(
            name="prompt",
            type="string",
            description="The prompt/message to send to the target AI.",
            required=False,
        ),
        ToolParameter(
            name="http_method",
            type="string",
            description="HTTP method (GET or POST). Default: POST.",
            required=False,
            enum=["GET", "POST"],
        ),
        ToolParameter(
            name="request_format",
            type="string",
            description=(
                "How to send the prompt. 'json' sends as JSON body, "
                "'form' sends as form data, 'query' sends as query parameter. "
                "Default: json."
            ),
            required=False,
            enum=["json", "form", "query"],
        ),
        ToolParameter(
            name="prompt_field",
            type="string",
            description=(
                "JSON/form field name for the prompt. Default: 'message'. "
                "Common values: 'message', 'prompt', 'input', 'text', 'query'."
            ),
            required=False,
        ),
        ToolParameter(
            name="response_field",
            type="string",
            description=(
                "JSON field to extract from response. Default: auto-detect. "
                "Common values: 'response', 'message', 'reply', 'output', 'text'."
            ),
            required=False,
        ),
        ToolParameter(
            name="headers",
            type="string",
            description="Extra HTTP headers as JSON string.",
            required=False,
        ),
        ToolParameter(
            name="extra_body",
            type="string",
            description=(
                "Extra JSON fields to include in the request body (as JSON string). "
                "e.g. '{\"session_id\": \"abc\", \"model\": \"gpt-4\"}'"
            ),
            required=False,
        ),
        ToolParameter(
            name="text",
            type="string",
            description="Raw text to analyze (for analyze_response action).",
            required=False,
        ),
        ToolParameter(
            name="payload_category",
            type="string",
            description=(
                "Filter payloads by category for 'spray' action. "
                "Options: direct, override, roleplay, encoding, indirect, "
                "sidechannel, context. Default: all."
            ),
            required=False,
        ),
        ToolParameter(
            name="max_attempts",
            type="string",
            description="Max number of payloads to try for spray/auto_attack. Default: 10.",
            required=False,
        ),
    ]

    def __init__(self) -> None:
        cfg = load_config()
        self.timeout = cfg.tool.network_timeout
        self._log = get_logger()
        # Multi-turn conversation history per target
        self._sessions: dict[str, list[dict[str, str]]] = {}
        # Persistent HTTP client for cookie/session handling
        self._http_client: httpx.Client | None = None
        # Request counter per target URL
        self._request_counts: dict[str, int] = {}

    def _get_client(self) -> httpx.Client:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                verify=False,
            )
        return self._http_client

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]

        dispatch = {
            "send_prompt": self._send_prompt,
            "multi_turn": self._multi_turn,
            "spray": self._spray,
            "auto_attack": self._auto_attack,
            "analyze_response": self._analyze_response,
            "reset_session": self._reset_session,
            "show_history": self._show_history,
        }

        handler = dispatch.get(action)
        if handler is None:
            return f"[ERROR] Unknown action: {action}"
        return handler(**kwargs)

    def _send_prompt(self, **kwargs: Any) -> str:
        """Send a single prompt to the target AI (no history tracking)."""
        target_url = kwargs.get("target_url", "")
        prompt = kwargs.get("prompt", "")
        if not target_url:
            return "[ERROR] 'target_url' is required."
        if not prompt:
            return "[ERROR] 'prompt' is required."

        raw_response, extracted = self._do_request(target_url, prompt, **kwargs)

        # Analyze for flags
        flags = self._detect_flags(extracted)
        result = f"Response:\n{extracted}"
        if flags:
            result += f"\n\n[FLAG DETECTED] {', '.join(flags)}"
        return result

    def _multi_turn(self, **kwargs: Any) -> str:
        """Send a prompt as part of a multi-turn conversation."""
        target_url = kwargs.get("target_url", "")
        prompt = kwargs.get("prompt", "")
        if not target_url:
            return "[ERROR] 'target_url' is required."
        if not prompt:
            return "[ERROR] 'prompt' is required."

        # Track conversation
        if target_url not in self._sessions:
            self._sessions[target_url] = []

        self._sessions[target_url].append({"role": "user", "content": prompt})

        # Include conversation history in extra_body if the API supports it
        raw_response, extracted = self._do_request(target_url, prompt, **kwargs)

        self._sessions[target_url].append({"role": "assistant", "content": extracted})

        turn_num = len(self._sessions[target_url]) // 2
        flags = self._detect_flags(extracted)

        result = f"[Turn {turn_num}] Response:\n{extracted}"
        if flags:
            result += f"\n\n[FLAG DETECTED] {', '.join(flags)}"
        return result

    def _analyze_response(self, **kwargs: Any) -> str:
        """Analyze a text for leaked secrets, flags, or interesting patterns."""
        text = kwargs.get("text", "") or kwargs.get("prompt", "")
        if not text:
            return "[ERROR] 'text' is required for analyze_response."

        findings: list[str] = []

        # Flag patterns
        flags = self._detect_flags(text)
        if flags:
            findings.append(f"Flags found: {', '.join(flags)}")

        # Base64 detection
        b64_pattern = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
        b64_matches = b64_pattern.findall(text)
        if b64_matches:
            import base64
            for match in b64_matches[:5]:
                try:
                    decoded = base64.b64decode(match).decode("utf-8", errors="replace")
                    if decoded.isprintable() and len(decoded) > 3:
                        findings.append(f"Base64 decoded: {match[:30]}... -> {decoded[:100]}")
                        sub_flags = self._detect_flags(decoded)
                        if sub_flags:
                            findings.append(f"Flag in decoded base64: {', '.join(sub_flags)}")
                except Exception:
                    pass

        # Hex string detection
        hex_pattern = re.compile(r"(?:0x)?([0-9a-fA-F]{20,})")
        hex_matches = hex_pattern.findall(text)
        if hex_matches:
            for match in hex_matches[:5]:
                try:
                    decoded = bytes.fromhex(match).decode("utf-8", errors="replace")
                    if decoded.isprintable() and len(decoded) > 3:
                        findings.append(f"Hex decoded: {match[:30]}... -> {decoded[:100]}")
                        sub_flags = self._detect_flags(decoded)
                        if sub_flags:
                            findings.append(f"Flag in decoded hex: {', '.join(sub_flags)}")
                except Exception:
                    pass

        # System prompt leak indicators
        leak_indicators = [
            "system prompt", "instructions", "you are", "your role",
            "do not reveal", "never share", "keep secret", "confidential",
            "the password is", "the secret is", "the flag is", "the key is",
        ]
        found_indicators = [ind for ind in leak_indicators if ind.lower() in text.lower()]
        if found_indicators:
            findings.append(f"Leak indicators: {', '.join(found_indicators)}")

        # ROT13 check
        rot13 = text.translate(str.maketrans(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
            "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
        ))
        rot13_flags = self._detect_flags(rot13)
        if rot13_flags:
            findings.append(f"Flag in ROT13: {', '.join(rot13_flags)}")

        # Reversed text check
        reversed_text = text[::-1]
        rev_flags = self._detect_flags(reversed_text)
        if rev_flags:
            findings.append(f"Flag in reversed text: {', '.join(rev_flags)}")

        if not findings:
            return "No flags, secrets, or suspicious patterns detected in the text."
        return "Analysis results:\n" + "\n".join(f"  - {f}" for f in findings)

    def _spray(self, **kwargs: Any) -> str:
        """Spray pre-built payloads against the target, stop on first flag."""
        target_url = kwargs.get("target_url", "")
        if not target_url:
            return "[ERROR] 'target_url' is required."

        from tools.ai_payloads import get_payloads

        category = kwargs.get("payload_category", None)
        max_attempts = int(kwargs.get("max_attempts", "10") or "10")
        payloads = get_payloads(category)[:max_attempts]

        results: list[str] = []
        for i, payload in enumerate(payloads, 1):
            _raw, extracted = self._do_request(target_url, payload.prompt, **kwargs)
            flags = self._detect_flags(extracted)

            status = "FLAG!" if flags else "no flag"
            summary = extracted[:120].replace("\n", " ")
            results.append(f"  [{i}/{len(payloads)}] {payload.name} ({payload.category}): {status}")
            results.append(f"         {summary}")

            if flags:
                results.append(f"\n[FLAG DETECTED] {', '.join(flags)}")
                results.append(f"Payload: {payload.prompt[:200]}")
                return "\n".join(results)

        return (
            f"Sprayed {len(payloads)} payloads — no flag detected.\n"
            + "\n".join(results)
            + "\n\nTry: encoding bypass, multi-turn, or side-channel extraction."
        )

    def _auto_attack(self, **kwargs: Any) -> str:
        """Run an escalating sequence of attacks against the target."""
        target_url = kwargs.get("target_url", "")
        if not target_url:
            return "[ERROR] 'target_url' is required."

        from tools.ai_payloads import get_escalation_sequence

        max_attempts = int(kwargs.get("max_attempts", "13") or "13")
        sequence = get_escalation_sequence()[:max_attempts]

        results: list[str] = []
        all_responses: list[str] = []

        for i, payload in enumerate(sequence, 1):
            _raw, extracted = self._do_request(target_url, payload.prompt, **kwargs)
            flags = self._detect_flags(extracted)
            all_responses.append(extracted)

            status = "FLAG!" if flags else "no flag"
            summary = extracted[:120].replace("\n", " ")
            results.append(f"  [{i}] {payload.name}: {status}")
            results.append(f"      {summary}")

            if flags:
                results.append(f"\n[FLAG DETECTED] {', '.join(flags)}")
                results.append(f"Winning payload ({payload.category}): {payload.prompt[:200]}")
                return "\n".join(results)

        # No flag found — analyze all responses for partial leaks
        combined = "\n---\n".join(all_responses)
        analysis = self._analyze_response(text=combined)

        return (
            f"Auto-attack: {len(sequence)} payloads tried — no direct flag.\n"
            + "\n".join(results)
            + f"\n\n{analysis}"
            + "\n\nSuggestions: try side-channel (character-by-character), "
            "multi-turn trust-building, or custom encoding bypass."
        )

    def _reset_session(self, **kwargs: Any) -> str:
        """Reset conversation history and HTTP session."""
        target_url = kwargs.get("target_url", "")
        if target_url and target_url in self._sessions:
            turns = len(self._sessions[target_url]) // 2
            del self._sessions[target_url]
            msg = f"Session reset for {target_url} ({turns} turns cleared)."
        elif target_url:
            msg = f"No active session for {target_url}."
        else:
            count = len(self._sessions)
            self._sessions.clear()
            msg = f"All sessions reset ({count} cleared)."

        # Reset HTTP client to clear cookies
        if self._http_client and not self._http_client.is_closed:
            self._http_client.close()
            self._http_client = None
        return msg

    def _show_history(self, **kwargs: Any) -> str:
        """Show conversation history for a target."""
        target_url = kwargs.get("target_url", "")
        if target_url and target_url in self._sessions:
            history = self._sessions[target_url]
            if not history:
                return f"Empty session for {target_url}."
            lines = []
            for msg in history:
                role = msg["role"].upper()
                content = msg["content"][:200]
                lines.append(f"[{role}] {content}")
            return f"History for {target_url} ({len(history)} messages):\n" + "\n".join(lines)
        elif target_url:
            return f"No session for {target_url}."
        else:
            if not self._sessions and not self._request_counts:
                return "No active sessions."
            lines = []
            all_urls = set(list(self._sessions.keys()) + list(self._request_counts.keys()))
            for url in sorted(all_urls):
                msgs = len(self._sessions.get(url, []))
                reqs = self._request_counts.get(url, 0)
                lines.append(f"  {url}: {msgs} messages, {reqs} total requests")
            return "Active sessions:\n" + "\n".join(lines)

    def _do_request(
        self,
        target_url: str,
        prompt: str,
        **kwargs: Any,
    ) -> tuple[str, str]:
        """Send the actual HTTP request and extract the response text.

        Returns (raw_response_text, extracted_ai_response).
        """
        http_method = kwargs.get("http_method", "POST").upper()
        request_format = kwargs.get("request_format", "json")
        prompt_field = kwargs.get("prompt_field", "message")
        response_field = kwargs.get("response_field", "")
        raw_headers = kwargs.get("headers", "")
        raw_extra_body = kwargs.get("extra_body", "")

        # Parse headers
        headers: dict[str, str] = {}
        if raw_headers:
            try:
                headers = json.loads(raw_headers)
            except json.JSONDecodeError:
                pass

        # Parse extra body fields
        extra_body: dict[str, Any] = {}
        if raw_extra_body:
            try:
                extra_body = json.loads(raw_extra_body)
            except json.JSONDecodeError:
                pass

        # Track request count
        self._request_counts[target_url] = self._request_counts.get(target_url, 0) + 1

        client = self._get_client()

        try:
            if http_method == "GET":
                params = {prompt_field: prompt, **extra_body}
                resp = client.get(target_url, params=params, headers=headers)
            elif request_format == "json":
                body = {prompt_field: prompt, **extra_body}
                if "Content-Type" not in headers:
                    headers["Content-Type"] = "application/json"
                resp = client.post(target_url, json=body, headers=headers)
            elif request_format == "form":
                data = {prompt_field: prompt, **extra_body}
                resp = client.post(target_url, data=data, headers=headers)
            else:  # query
                params = {prompt_field: prompt, **extra_body}
                resp = client.post(target_url, params=params, headers=headers)

            raw_text = resp.text
            status = resp.status_code

            # Try to extract the AI response from JSON
            extracted = raw_text
            try:
                resp_json = resp.json()
                if isinstance(resp_json, dict):
                    if response_field and response_field in resp_json:
                        extracted = str(resp_json[response_field])
                    else:
                        # Auto-detect common response fields
                        for field in [
                            "response", "message", "reply", "output", "text",
                            "answer", "content", "result", "data", "bot",
                            "assistant", "completion",
                        ]:
                            if field in resp_json:
                                val = resp_json[field]
                                if isinstance(val, str):
                                    extracted = val
                                    break
                                elif isinstance(val, dict) and "content" in val:
                                    extracted = str(val["content"])
                                    break
                        else:
                            extracted = json.dumps(resp_json, indent=2, ensure_ascii=False)
                elif isinstance(resp_json, str):
                    extracted = resp_json
            except (json.JSONDecodeError, ValueError):
                pass

            if status >= 400:
                return raw_text, f"[HTTP {status}] {extracted}"
            return raw_text, extracted

        except httpx.TimeoutException:
            msg = f"[ERROR] Request timed out after {self.timeout}s"
            return msg, msg
        except httpx.HTTPError as exc:
            msg = f"[ERROR] HTTP error: {exc}"
            return msg, msg

    @staticmethod
    def _detect_flags(text: str) -> list[str]:
        """Search text for common CTF flag patterns."""
        found: list[str] = []
        for pattern in _FLAG_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if value not in found:
                    found.append(value)
        return found
