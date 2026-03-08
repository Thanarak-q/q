"""Static source-code analyzer for white-box CTF solving.

Scans a repository for common vulnerability patterns (SQLi, XSS,
command injection, path traversal, auth bypass, SSRF, deserialization)
so the agent can focus its attacks on specific files and lines.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


class CodeAnalyzer:
    """Analyse source code to find potential vulnerabilities."""

    # File extensions per language
    LANG_EXTENSIONS: dict[str, list[str]] = {
        "python": [".py"],
        "php": [".php"],
        "javascript": [".js", ".jsx", ".ts", ".tsx"],
        "java": [".java"],
        "ruby": [".rb"],
        "go": [".go"],
        "csharp": [".cs"],
    }

    # Dangerous patterns per (vuln_type, language)
    VULN_PATTERNS: dict[str, dict[str, list[str]]] = {
        "sqli": {
            "python": [
                r'execute\s*\(\s*[f"\'](.*?%s.*?|.*?\{.*?\}.*?)',
                r"cursor\.execute\s*\(\s*[\"'].*?\+",
                r"\.format\s*\(.*?\).*?execute",
                r'f["\'].*?SELECT.*?\{',
            ],
            "php": [
                r"mysql_query\s*\(\s*[\"'].*?\$",
                r"\$.*?->query\s*\(\s*[\"'].*?\$",
                r"mysqli_query\s*\(.*?\$",
            ],
            "javascript": [
                r"\.query\s*\(\s*[`\"']\s*SELECT.*?\$\{",
                r"\.query\s*\(\s*[\"'].*?\+",
                r"\.raw\s*\(\s*[`\"']\s*SELECT.*?\$\{",
            ],
            "java": [
                r'createStatement\(\)\.execute.*?".*?\+',
                r"PreparedStatement.*?\".*?\+",
            ],
            "ruby": [
                r"\.where\s*\(.*?#\{",
                r"\.execute\s*\(.*?#\{",
            ],
            "go": [
                r'db\.(Query|Exec)\s*\(\s*".*?\+',
                r"fmt\.Sprintf.*?SELECT",
            ],
        },
        "xss": {
            "python": [
                r"render_template_string\s*\(",
                r"Markup\s*\(.*?\+",
                r"\.safe\s*=\s*True",
                r"\|safe\b",
            ],
            "php": [
                r"echo\s+\$_(GET|POST|REQUEST|COOKIE)",
                r"print\s+\$_(GET|POST|REQUEST|COOKIE)",
                r"<\?=\s*\$_(GET|POST|REQUEST|COOKIE)",
            ],
            "javascript": [
                r"innerHTML\s*=.*?(req\.|params|query|body)",
                r"\.html\s*\(.*?(req\.|params|query|body)",
                r"dangerouslySetInnerHTML",
                r"document\.write\s*\(",
            ],
        },
        "cmdi": {
            "python": [
                r"os\.system\s*\(.*?\+",
                r"os\.system\s*\(.*?f[\"']",
                r"subprocess\.(call|run|Popen)\s*\(.*?\+",
                r"subprocess\.(call|run|Popen)\s*\(.*?f[\"']",
                r"os\.popen\s*\(.*?\+",
                r"os\.popen\s*\(.*?f[\"']",
            ],
            "php": [
                r"(exec|system|passthru|shell_exec)\s*\(\s*\$",
                r"`\$",
                r"popen\s*\(\s*\$",
            ],
            "javascript": [
                r"exec\s*\(.*?\+",
                r"child_process\.exec\s*\(",
                r"execSync\s*\(",
            ],
            "ruby": [
                r"system\s*\(.*?#\{",
                r"`.*?#\{",
            ],
            "go": [
                r"exec\.Command\s*\(.*?\+",
            ],
        },
        "path_traversal": {
            "python": [
                r"open\s*\(.*?(request|input|argv|args)",
                r"send_file\s*\(.*?(request|input)",
                r"os\.path\.join\s*\(.*?(request|input|args)",
            ],
            "php": [
                r"(include|require|fopen|file_get_contents|readfile)\s*\(\s*\$",
            ],
            "javascript": [
                r"readFile(Sync)?\s*\(.*?(req\.|params|query)",
                r"\.sendFile\s*\(.*?(req\.|params|query)",
                r"path\.join\s*\(.*?(req\.|params|query)",
            ],
        },
        "auth_bypass": {
            "python": [
                r"verify.*?==\s*[\"']",
                r"jwt\.decode\s*\(.*?verify\s*=\s*False",
                r"password\s*==\s*[\"']",
                r"secret.*?=\s*[\"'][^\"']{1,30}[\"']",
            ],
            "php": [
                r"password\s*==\s*[\"']",
                r"\$_SESSION\[.*?\]\s*=.*?\$_(GET|POST)",
                r"md5\s*\(\s*\$_(GET|POST)",
                r"strcmp\s*\(",
            ],
            "javascript": [
                r"jwt\.verify.*?algorithms.*?none",
                r"password\s*===?\s*[\"']",
                r"secret.*?=\s*[\"'][^\"']{1,30}[\"']",
            ],
        },
        "ssrf": {
            "python": [
                r"requests\.(get|post)\s*\(.*?(request|input|args)",
                r"urllib\.request\.urlopen\s*\(.*?(request|input|args)",
            ],
            "php": [
                r"file_get_contents\s*\(\s*\$_(GET|POST)",
                r"curl_setopt.*?CURLOPT_URL.*?\$",
            ],
            "javascript": [
                r"fetch\s*\(.*?(req\.|params|query|body)",
                r"axios\.(get|post)\s*\(.*?(req\.|params|query|body)",
            ],
        },
        "deserialization": {
            "python": [
                r"pickle\.loads?\s*\(",
                r"yaml\.load\s*\(",
                r"marshal\.loads?\s*\(",
            ],
            "php": [
                r"unserialize\s*\(\s*\$",
            ],
            "javascript": [
                r"node-serialize",
                r"\.deserialize\s*\(",
            ],
            "java": [
                r"ObjectInputStream",
                r"readObject\s*\(",
            ],
        },
    }

    # Directories to skip
    _SKIP_DIRS = frozenset({
        "node_modules", "venv", ".venv", "env", ".git", "__pycache__",
        "test", "tests", "spec", "vendor", "dist", "build", ".tox",
        "site-packages", "migrations", "static", "assets",
    })

    # Severity mapping
    _SEVERITY: dict[str, str] = {
        "sqli": "critical",
        "cmdi": "critical",
        "auth_bypass": "critical",
        "deserialization": "critical",
        "xss": "high",
        "ssrf": "high",
        "path_traversal": "high",
    }

    def analyze_directory(self, repo_path: str) -> dict[str, Any]:
        """Scan a repository for potential vulnerabilities.

        Args:
            repo_path: Absolute or relative path to the repo root.

        Returns:
            Dict with keys: language, files_scanned, findings (list).
        """
        language = self._detect_language(repo_path)
        findings: list[dict[str, Any]] = []
        files_scanned = 0

        for filepath in self._get_code_files(repo_path, language):
            files_scanned += 1
            try:
                content = filepath.read_text(errors="ignore")
                lines = content.split("\n")
            except OSError:
                continue

            rel_path = os.path.relpath(filepath, repo_path)

            if self._should_skip(rel_path):
                continue

            for vuln_type, lang_patterns in self.VULN_PATTERNS.items():
                patterns = lang_patterns.get(language, [])
                for pattern in patterns:
                    try:
                        for match in re.finditer(pattern, content):
                            line_num = content[: match.start()].count("\n") + 1
                            code_line = lines[line_num - 1].strip() if line_num <= len(lines) else ""

                            findings.append({
                                "type": vuln_type,
                                "file": rel_path,
                                "line": line_num,
                                "code": code_line[:200],
                                "severity": self._SEVERITY.get(vuln_type, "medium"),
                            })
                    except re.error:
                        continue

        # Deduplicate on file+line
        unique: dict[str, dict[str, Any]] = {}
        for f in findings:
            key = f"{f['file']}:{f['line']}"
            if key not in unique:
                unique[key] = f
            elif self._severity_rank(f["severity"]) > self._severity_rank(unique[key]["severity"]):
                unique[key] = f  # keep the higher-severity finding

        # Sort by severity (critical first), then file
        sorted_findings = sorted(
            unique.values(),
            key=lambda x: (-self._severity_rank(x["severity"]), x["file"], x["line"]),
        )

        return {
            "language": language,
            "files_scanned": files_scanned,
            "findings": sorted_findings,
        }

    def format_for_prompt(self, analysis: dict[str, Any]) -> str:
        """Format analysis results for injection into the agent system prompt.

        Args:
            analysis: Result from analyze_directory().

        Returns:
            Markdown string to append to the system prompt, or "" if no findings.
        """
        if not analysis["findings"]:
            return ""

        output = "\n## Source Code Analysis Results (White-Box)\n"
        output += (
            f"Language: {analysis['language']}, "
            f"Files scanned: {analysis['files_scanned']}\n\n"
        )
        output += "Potential vulnerabilities found:\n"

        for f in analysis["findings"][:15]:  # cap at 15 to save tokens
            output += (
                f"- **{f['type'].upper()}** [{f['severity']}] "
                f"in `{f['file']}` line {f['line']}: `{f['code'][:100]}`\n"
            )

        output += (
            "\nFocus your testing on these specific locations. "
            "Start with critical findings first.\n"
        )
        return output

    def summary(self, analysis: dict[str, Any]) -> str:
        """One-line summary of findings for CLI display.

        Args:
            analysis: Result from analyze_directory().

        Returns:
            Human-readable summary string.
        """
        if not analysis["findings"]:
            return "No potential vulnerabilities found."

        by_type: dict[str, int] = {}
        for f in analysis["findings"]:
            key = f"{f['type']} ({f['severity']})"
            by_type[key] = by_type.get(key, 0) + 1

        parts = [f"{v}x {k}" for k, v in sorted(by_type.items())]
        return (
            f"Found {len(analysis['findings'])} potential vulnerabilities "
            f"in {analysis['files_scanned']} files: {', '.join(parts)}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_language(self, repo_path: str) -> str:
        """Detect the primary language of a repository."""
        counts: dict[str, int] = {}
        root = Path(repo_path)
        for lang, exts in self.LANG_EXTENSIONS.items():
            count = 0
            for ext in exts:
                count += sum(
                    1
                    for p in root.rglob(f"*{ext}")
                    if not self._should_skip(str(p.relative_to(root)))
                )
            counts[lang] = count
        return max(counts, key=counts.get) if any(counts.values()) else "python"

    def _get_code_files(self, repo_path: str, language: str):
        """Yield all code files for the detected language."""
        exts = self.LANG_EXTENSIONS.get(language, [".py"])
        root = Path(repo_path)
        for ext in exts:
            yield from root.rglob(f"*{ext}")

    def _should_skip(self, path: str) -> bool:
        """Return True if the path is in a directory we should skip."""
        parts = Path(path).parts
        return any(part.lower() in self._SKIP_DIRS for part in parts)

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return {"critical": 3, "high": 2, "medium": 1, "low": 0}.get(severity, 0)
