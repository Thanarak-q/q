"""Output summarizer for CTF agent.

Summarizes long tool outputs to save context tokens while preserving
critical findings like flags, IPs, credentials, and key data.
"""

from __future__ import annotations

import re


class OutputSummarizer:
    """Summarize long tool outputs to save tokens."""

    # Outputs longer than this get summarized
    MAX_RAW_CHARS = 3000

    def summarize(self, tool: str, command: str, output: str) -> str:
        """Summarize tool output if too long.

        Args:
            tool: Tool name (e.g. "shell", "network").
            command: Command or args string.
            output: Raw tool output.

        Returns:
            Original output if short enough, else summarized version.
        """
        if len(output) <= self.MAX_RAW_CHARS:
            return output

        # Always extract critical patterns regardless of length
        preserved = self._extract_critical(output)

        # Tool-specific summarization
        cmd_lower = command.lower()
        if "tshark" in cmd_lower:
            summary = self._summarize_tshark(output)
        elif "nmap" in cmd_lower:
            summary = self._summarize_nmap(output)
        elif "gobuster" in cmd_lower or "dirb" in cmd_lower:
            summary = self._summarize_dirscan(output)
        elif "strings" in cmd_lower:
            summary = self._summarize_strings(output)
        elif "curl" in cmd_lower or tool == "network":
            summary = self._summarize_http(output)
        else:
            summary = self._summarize_generic(output)

        # Append preserved critical findings
        if preserved:
            summary += "\n\n🔍 Key findings extracted:\n" + preserved

        return summary

    def _extract_critical(self, output: str) -> str:
        """Extract flags, IPs, credentials, and other key data."""
        findings: list[str] = []

        # Flags
        flags = re.findall(r'flag\{[^}]+\}', output, re.I)
        for f in flags:
            findings.append(f"FLAG: {f}")

        # IPs (deduplicated)
        ips = set(re.findall(
            r'\b(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}'
            r'(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\b',
            output,
        ))
        boring_ips = {'0.0.0.0', '127.0.0.1', '255.255.255.255'}
        interesting_ips = ips - boring_ips
        if interesting_ips:
            findings.append(
                f"IPs: {', '.join(list(interesting_ips)[:10])}"
            )

        # Credentials
        creds = re.findall(
            r'(?:password|passwd|pass|pwd|secret|token|key)'
            r'\s*[:=]\s*["\']?(\S+)["\']?',
            output, re.I,
        )
        if creds:
            findings.append(f"Possible credentials: {creds[:5]}")

        # URLs/paths
        paths = re.findall(r'(?:https?://\S+|/[\w./\-]+)', output)
        unique_paths = list(set(paths))[:10]
        if unique_paths:
            findings.append(f"URLs/paths: {unique_paths}")

        # SQL errors
        if re.search(
            r'(sql|mysql|sqlite|postgres|oracle).*?(error|syntax|warning)',
            output, re.I,
        ):
            findings.append("SQL error detected — injection likely works")

        return "\n".join(findings)

    def _summarize_tshark(self, output: str) -> str:
        lines = output.strip().split('\n')
        summary = f"[tshark output: {len(lines)} lines]\n"

        # Keep conversation stats
        stats_lines = [
            line for line in lines[:20]
            if any(c in line for c in ['<->', 'Frames', 'Bytes', 'TCP', 'UDP'])
        ]
        if stats_lines:
            summary += "Traffic stats:\n" + "\n".join(stats_lines[:10])

        # Keep HTTP requests if present
        http_lines = [
            line for line in lines
            if 'HTTP' in line or 'GET' in line or 'POST' in line
        ]
        if http_lines:
            summary += f"\n\nHTTP requests ({len(http_lines)} total):\n"
            summary += "\n".join(http_lines[:15])
            if len(http_lines) > 15:
                summary += f"\n... and {len(http_lines) - 15} more"

        return summary

    def _summarize_nmap(self, output: str) -> str:
        lines = output.strip().split('\n')
        port_lines = [
            line for line in lines
            if '/open/' in line or 'open' in line.lower()
        ]
        summary = f"[nmap: {len(lines)} lines total]\n"
        summary += "Open ports:\n" + "\n".join(port_lines[:20])
        return summary

    def _summarize_dirscan(self, output: str) -> str:
        lines = output.strip().split('\n')
        found = [
            line for line in lines
            if re.search(r'Status:\s*(200|301|302|403)', line)
        ]
        summary = f"[directory scan: {len(found)} paths found]\n"
        summary += "\n".join(found[:20])
        return summary

    def _summarize_strings(self, output: str) -> str:
        lines = output.strip().split('\n')
        interesting: list[str] = []
        keywords = [
            'flag', 'password', 'secret', 'admin', 'login',
            'key', 'token', 'http', 'ftp', 'ssh', 'sql',
            'base64', 'hack', '.php', '.html', '.txt',
        ]
        for line in lines:
            stripped = line.strip()
            if len(stripped) < 4:
                continue
            if any(kw in stripped.lower() for kw in keywords):
                interesting.append(stripped)

        summary = (
            f"[strings: {len(lines)} total, "
            f"{len(interesting)} interesting]\n"
        )
        summary += "\n".join(interesting[:30])
        return summary

    def _summarize_http(self, output: str) -> str:
        lines = output.strip().split('\n')
        summary = f"[HTTP response: {len(lines)} lines]\n"
        summary += "\n".join(lines[:60])
        if len(lines) > 60:
            summary += f"\n... ({len(lines) - 60} lines truncated)"
        return summary

    def _summarize_generic(self, output: str) -> str:
        lines = output.strip().split('\n')
        summary = f"[output: {len(lines)} lines]\n"
        summary += "\n".join(lines[:20])
        if len(lines) > 30:
            summary += f"\n... ({len(lines) - 30} lines omitted) ...\n"
            summary += "\n".join(lines[-10:])
        return summary
