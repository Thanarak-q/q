"""Smart HTTP response parser for CTF-relevant information.

Parses HTTP responses and highlights indicators useful for web exploitation:
SQL errors, SSTI markers, flags, JWT tokens, HTML comments, interesting
headers, and technology fingerprints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedResponse:
    """Structured result from parsing an HTTP response."""

    status_code: int = 0
    interesting_headers: dict[str, str] = field(default_factory=dict)
    sql_errors: list[str] = field(default_factory=list)
    ssti_indicators: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    jwt_tokens: list[str] = field(default_factory=list)
    html_comments: list[str] = field(default_factory=list)
    hidden_inputs: list[dict[str, str]] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    interesting_paths: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)
    cookies: dict[str, str] = field(default_factory=dict)
    redirect_url: str = ""

    @property
    def has_findings(self) -> bool:
        """Return True if any CTF-relevant findings were detected."""
        return bool(
            self.sql_errors
            or self.ssti_indicators
            or self.flags
            or self.jwt_tokens
            or self.html_comments
            or self.hidden_inputs
            or self.interesting_headers
            or self.error_messages
        )


# SQL error patterns by database
SQL_ERROR_PATTERNS: list[tuple[str, str]] = [
    (r"mysql_fetch|mysql_num_rows|MySQL server", "MySQL"),
    (r"You have an error in your SQL syntax", "MySQL"),
    (r"Warning.*mysql_", "MySQL"),
    (r"pg_query|pg_exec|PostgreSQL.*ERROR", "PostgreSQL"),
    (r"unterminated quoted string.*position", "PostgreSQL"),
    (r"sqlite3\.OperationalError|SQLite3::", "SQLite"),
    (r"SQLITE_ERROR|near \".*\": syntax error", "SQLite"),
    (r"Microsoft OLE DB Provider|ODBC SQL Server", "MSSQL"),
    (r"Unclosed quotation mark|mssql_query", "MSSQL"),
    (r"ORA-\d{5}", "Oracle"),
    (r"quoted string not properly terminated", "Oracle"),
    (r"SQL syntax.*error|sql error|database error", "Generic SQL"),
]

# SSTI detection patterns
SSTI_PATTERNS: list[tuple[str, str]] = [
    (r"\{\{.*?\}\}", "Jinja2/Twig"),
    (r"\$\{.*?\}", "Freemarker/Velocity"),
    (r"<%=.*?%>", "ERB"),
    (r"#\{.*?\}", "Thymeleaf/Ruby"),
    (r"Traceback \(most recent call last\)", "Python error (possible SSTI)"),
    (r"jinja2\.exceptions\.", "Jinja2 confirmed"),
    (r"UndefinedError|TemplateSyntaxError", "Jinja2 confirmed"),
    (r"twig.*error|Twig_Error", "Twig confirmed"),
]

# Interesting HTTP headers
INTERESTING_HEADERS: set[str] = {
    "x-powered-by",
    "server",
    "x-debug",
    "x-debug-token",
    "x-debug-token-link",
    "x-request-id",
    "x-aspnet-version",
    "x-runtime",
    "x-version",
    "x-flag",
    "flag",
    "x-custom-header",
    "x-forwarded-for",
    "via",
    "x-backend-server",
    "x-generator",
    "x-cms",
    "www-authenticate",
    "x-token",
    "authorization",
    "access-control-allow-origin",
    "content-security-policy",
    "x-frame-options",
    "x-xss-protection",
}

# Technology fingerprints from headers/cookies
TECH_FINGERPRINTS: list[tuple[str, str, str]] = [
    # (pattern, location, tech_name)
    ("PHPSESSID", "cookie", "PHP"),
    ("connect.sid", "cookie", "Node.js/Express"),
    ("JSESSIONID", "cookie", "Java/Tomcat"),
    ("ASP.NET_SessionId", "cookie", "ASP.NET"),
    ("csrftoken", "cookie", "Django"),
    ("laravel_session", "cookie", "Laravel"),
    ("_rails", "cookie", "Ruby on Rails"),
    ("rack.session", "cookie", "Ruby/Rack"),
    ("wp-", "cookie", "WordPress"),
    ("express", "header:x-powered-by", "Express.js"),
    ("PHP", "header:x-powered-by", "PHP"),
    ("ASP.NET", "header:x-powered-by", "ASP.NET"),
    ("nginx", "header:server", "Nginx"),
    ("apache", "header:server", "Apache"),
    ("gunicorn", "header:server", "Python/Gunicorn"),
    ("werkzeug", "header:server", "Python/Flask"),
    ("Werkzeug", "header:server", "Python/Flask"),
    ("cloudflare", "header:server", "Cloudflare"),
]


class ResponseParser:
    """Parse HTTP responses and extract CTF-relevant information."""

    # Common flag formats
    FLAG_PATTERNS: list[str] = [
        r"(?:flag|FLAG|ctf|CTF)\{[^}]+\}",
        r"(?:picoCTF|HTB|THM|DUCTF|CSAW)\{[^}]+\}",
        r"[A-Za-z0-9+/]{20,}={0,2}",  # Base64 (long enough to be interesting)
    ]

    def parse(self, raw_response: str) -> ParsedResponse:
        """Parse a raw HTTP response string.

        Args:
            raw_response: The full HTTP response text (status + headers + body).

        Returns:
            ParsedResponse with all findings.
        """
        result = ParsedResponse()

        # Split into headers section and body
        headers_text, body = self._split_response(raw_response)

        # Parse status code
        result.status_code = self._extract_status_code(raw_response)

        # Parse headers
        headers = self._parse_headers(headers_text)
        result.interesting_headers = self._find_interesting_headers(headers)
        result.cookies = self._extract_cookies(headers)
        result.tech_stack = self._detect_tech(headers, result.cookies)

        # Check redirect
        if result.status_code in (301, 302, 303, 307, 308):
            result.redirect_url = headers.get("location", "")

        # Parse body
        result.sql_errors = self._find_sql_errors(body)
        result.ssti_indicators = self._find_ssti(body)
        result.flags = self._find_flags(raw_response)
        result.jwt_tokens = self._find_jwt(raw_response)
        result.html_comments = self._find_html_comments(body)
        result.hidden_inputs = self._find_hidden_inputs(body)
        result.interesting_paths = self._find_paths(body)
        result.error_messages = self._find_errors(body)

        return result

    def format_findings(self, parsed: ParsedResponse) -> str:
        """Format findings as a concise summary to inject into context.

        Args:
            parsed: ParsedResponse from parse().

        Returns:
            Formatted string with findings, or "" if nothing interesting.
        """
        if not parsed.has_findings:
            return ""

        lines: list[str] = ["[RESPONSE ANALYSIS]"]

        if parsed.flags:
            lines.append(f"  *** FLAGS FOUND: {parsed.flags}")

        if parsed.sql_errors:
            lines.append(f"  SQL errors detected: {parsed.sql_errors}")

        if parsed.ssti_indicators:
            lines.append(f"  SSTI indicators: {parsed.ssti_indicators}")

        if parsed.jwt_tokens:
            lines.append(f"  JWT tokens: {len(parsed.jwt_tokens)} found")
            for t in parsed.jwt_tokens[:2]:
                lines.append(f"    {t[:80]}...")

        if parsed.html_comments:
            lines.append(f"  HTML comments ({len(parsed.html_comments)}):")
            for c in parsed.html_comments[:5]:
                lines.append(f"    {c[:100]}")

        if parsed.hidden_inputs:
            lines.append(f"  Hidden inputs: {parsed.hidden_inputs}")

        if parsed.interesting_headers:
            for k, v in parsed.interesting_headers.items():
                lines.append(f"  Header [{k}]: {v}")

        if parsed.tech_stack:
            lines.append(f"  Tech stack: {', '.join(parsed.tech_stack)}")

        if parsed.error_messages:
            lines.append(f"  Errors: {parsed.error_messages[:3]}")

        if parsed.cookies:
            lines.append(f"  Cookies: {list(parsed.cookies.keys())}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_response(self, raw: str) -> tuple[str, str]:
        """Split raw response into headers and body."""
        # Look for double newline separating headers from body
        for sep in ["\n\nBody:\n", "\n\n", "\r\n\r\n"]:
            if sep in raw:
                parts = raw.split(sep, 1)
                return parts[0], parts[1] if len(parts) > 1 else ""
        return raw, ""

    def _extract_status_code(self, raw: str) -> int:
        """Extract HTTP status code from response."""
        m = re.search(r"HTTP[/ ]?\d?\s*(\d{3})", raw)
        return int(m.group(1)) if m else 0

    def _parse_headers(self, headers_text: str) -> dict[str, str]:
        """Parse header lines into a dict."""
        headers: dict[str, str] = {}
        for line in headers_text.splitlines():
            line = line.strip()
            if ":" in line:
                key, _, val = line.partition(":")
                headers[key.strip().lower()] = val.strip()
        return headers

    def _find_interesting_headers(
        self, headers: dict[str, str]
    ) -> dict[str, str]:
        """Filter headers to only interesting ones."""
        found: dict[str, str] = {}
        for key, val in headers.items():
            if key in INTERESTING_HEADERS:
                found[key] = val
        return found

    def _extract_cookies(self, headers: dict[str, str]) -> dict[str, str]:
        """Extract cookies from Set-Cookie headers."""
        cookies: dict[str, str] = {}
        for key, val in headers.items():
            if key == "set-cookie":
                # Parse "name=value; ..."
                cookie_part = val.split(";")[0]
                if "=" in cookie_part:
                    cname, _, cval = cookie_part.partition("=")
                    cookies[cname.strip()] = cval.strip()
        return cookies

    def _detect_tech(
        self, headers: dict[str, str], cookies: dict[str, str]
    ) -> list[str]:
        """Detect technology stack from headers and cookies."""
        tech: list[str] = []
        for pattern, location, name in TECH_FINGERPRINTS:
            if location == "cookie":
                for ck in cookies:
                    if pattern.lower() in ck.lower():
                        if name not in tech:
                            tech.append(name)
            elif location.startswith("header:"):
                hdr = location.split(":", 1)[1]
                hval = headers.get(hdr, "")
                if pattern.lower() in hval.lower():
                    if name not in tech:
                        tech.append(name)
        return tech

    def _find_sql_errors(self, body: str) -> list[str]:
        """Find SQL error patterns in response body."""
        found: list[str] = []
        for pattern, db_type in SQL_ERROR_PATTERNS:
            if re.search(pattern, body, re.IGNORECASE):
                found.append(db_type)
        return list(set(found))

    def _find_ssti(self, body: str) -> list[str]:
        """Find SSTI indicators in response body."""
        found: list[str] = []
        for pattern, engine in SSTI_PATTERNS:
            if re.search(pattern, body):
                if engine not in found:
                    found.append(engine)
        return found

    def _find_flags(self, text: str) -> list[str]:
        """Find flag-like strings in text."""
        flags: list[str] = []
        for pattern in self.FLAG_PATTERNS[:2]:  # Skip base64 (too noisy)
            for m in re.finditer(pattern, text):
                flags.append(m.group())
        return flags

    def _find_jwt(self, text: str) -> list[str]:
        """Find JWT tokens in text."""
        jwt_pattern = r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
        return re.findall(jwt_pattern, text)

    def _find_html_comments(self, body: str) -> list[str]:
        """Extract HTML comments (often contain hints in CTFs)."""
        comments = re.findall(r"<!--(.*?)-->", body, re.DOTALL)
        # Filter out trivial comments
        return [
            c.strip()
            for c in comments
            if len(c.strip()) > 3 and not c.strip().startswith("[if ")
        ]

    def _find_hidden_inputs(self, body: str) -> list[dict[str, str]]:
        """Find hidden form inputs."""
        inputs: list[dict[str, str]] = []
        for m in re.finditer(
            r'<input[^>]*type=["\']hidden["\'][^>]*>', body, re.IGNORECASE
        ):
            tag = m.group()
            name_m = re.search(r'name=["\']([^"\']+)["\']', tag)
            val_m = re.search(r'value=["\']([^"\']*)["\']', tag)
            if name_m:
                inputs.append({
                    "name": name_m.group(1),
                    "value": val_m.group(1) if val_m else "",
                })
        return inputs

    def _find_paths(self, body: str) -> list[str]:
        """Find interesting file paths and URLs in body."""
        paths: list[str] = []
        # Absolute paths
        for m in re.finditer(r'(?:href|src|action)=["\']([^"\']+)["\']', body):
            path = m.group(1)
            if path and not path.startswith(("http://", "https://", "#", "javascript:")):
                if path not in paths:
                    paths.append(path)
        # API endpoints
        for m in re.finditer(r'["\']/(api/[^"\']+)["\']', body):
            p = "/" + m.group(1)
            if p not in paths:
                paths.append(p)
        return paths[:20]  # Limit

    def _find_errors(self, body: str) -> list[str]:
        """Find error messages that might leak information."""
        errors: list[str] = []
        error_patterns = [
            r"Traceback \(most recent call last\).*?(?:Error|Exception): .+",
            r"Fatal error:.*?on line \d+",
            r"(?:Warning|Notice|Error):.*?(?:on line \d+|in /.+)",
            r"java\.\w+Exception:.*",
            r"at \w+\.\w+\([\w.]+:\d+\)",
            r"undefined is not a function",
            r"Cannot read propert(?:y|ies) of (?:null|undefined)",
            r"SQLSTATE\[\w+\]",
        ]
        for pattern in error_patterns:
            for m in re.finditer(pattern, body, re.DOTALL):
                msg = m.group()[:200]
                if msg not in errors:
                    errors.append(msg)
        return errors[:5]
