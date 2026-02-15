"""Reconnaissance tools for web target analysis.

Provides structured recon capabilities: port scanning (nmap),
technology detection (whatweb), directory brute-force (gobuster),
vulnerability scanning (nikto), subdomain enumeration (subfinder),
and a fast combined quick-recon mode.

All tools are registered as a single ``recon`` BaseTool with an
``action`` parameter that selects the sub-tool.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any
from urllib.parse import urlparse

from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger


class ReconTool(BaseTool):
    """Reconnaissance toolkit for web and network targets."""

    name = "recon"
    description = (
        "Reconnaissance toolkit for web targets. Actions: "
        "'quick' (fast headers + common paths + tech detection — use FIRST), "
        "'nmap' (port scan + service detection), "
        "'gobuster' (directory brute-force), "
        "'nikto' (web vulnerability scanner), "
        "'subfinder' (subdomain enumeration), "
        "'whatweb' (technology fingerprinting)."
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description=(
                "Recon action: 'quick', 'nmap', 'gobuster', "
                "'nikto', 'subfinder', 'whatweb'."
            ),
            enum=["quick", "nmap", "gobuster", "nikto", "subfinder", "whatweb"],
        ),
        ToolParameter(
            name="target",
            type="string",
            description="Target URL, hostname, or IP address.",
        ),
        ToolParameter(
            name="ports",
            type="string",
            description="Port range for nmap (e.g. '1-10000'). Default: '1-10000'.",
            required=False,
        ),
        ToolParameter(
            name="wordlist",
            type="string",
            description="Wordlist path for gobuster. Auto-detected if omitted.",
            required=False,
        ),
    ]

    def __init__(self) -> None:
        self.timeout = 120
        self._log = get_logger()

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        target = kwargs["target"]

        dispatch = {
            "quick": self._quick_recon,
            "nmap": self._nmap_scan,
            "gobuster": self._gobuster,
            "nikto": self._nikto,
            "subfinder": self._subfinder,
            "whatweb": self._whatweb,
        }

        handler = dispatch.get(action)
        if handler is None:
            return f"Unknown recon action: {action}"

        result = handler(target, **kwargs)
        return json.dumps(result, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Quick recon (default for web challenges)
    # ------------------------------------------------------------------

    def _quick_recon(self, url: str, **kwargs: Any) -> dict:
        """Fast recon: headers + common paths + tech detection."""
        parsed = urlparse(url)
        if not parsed.scheme:
            url = f"http://{url}"
            parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        results: dict[str, Any] = {
            "url": url,
            "headers": {},
            "interesting_paths": [],
            "tech_stack": [],
        }

        # 1. Response headers
        try:
            import httpx

            resp = httpx.get(url, timeout=10, follow_redirects=True, verify=False)
            interesting_headers = {
                "server", "x-powered-by", "x-debug", "x-flag",
                "set-cookie", "content-security-policy", "x-frame-options",
                "x-aspnet-version", "x-generator",
            }
            results["headers"] = {
                k: v for k, v in resp.headers.items()
                if k.lower() in interesting_headers
            }
            results["status_code"] = resp.status_code

            # Infer tech from headers
            for hdr_val in resp.headers.values():
                val_lower = hdr_val.lower()
                if "php" in val_lower:
                    results["tech_stack"].append("PHP")
                if "express" in val_lower:
                    results["tech_stack"].append("Express/Node.js")
                if "asp.net" in val_lower:
                    results["tech_stack"].append("ASP.NET")

            # Check cookie names
            cookies = resp.headers.get_list("set-cookie")
            for cookie in cookies:
                if "PHPSESSID" in cookie:
                    results["tech_stack"].append("PHP")
                elif "connect.sid" in cookie:
                    results["tech_stack"].append("Node.js")
                elif "JSESSIONID" in cookie:
                    results["tech_stack"].append("Java")
                elif "csrftoken" in cookie:
                    results["tech_stack"].append("Django")

        except Exception as exc:
            results["headers_error"] = str(exc)

        # 2. Common CTF paths
        common_paths = [
            "/robots.txt", "/flag.txt", "/admin", "/.git/HEAD",
            "/.env", "/.DS_Store", "/api", "/debug", "/backup",
            "/sitemap.xml", "/console", "/swagger", "/graphql",
            "/.well-known/", "/wp-login.php", "/phpmyadmin",
        ]

        try:
            import httpx

            for path in common_paths:
                try:
                    resp = httpx.get(
                        base + path,
                        timeout=5,
                        follow_redirects=False,
                        verify=False,
                    )
                    if resp.status_code in (200, 301, 302, 403):
                        entry: dict[str, Any] = {
                            "path": path,
                            "status": resp.status_code,
                            "size": len(resp.content),
                        }
                        # Show body for small 200 responses (flag.txt, robots.txt, etc.)
                        if resp.status_code == 200 and len(resp.content) < 500:
                            entry["body"] = resp.text[:500]
                        results["interesting_paths"].append(entry)
                except Exception:
                    continue
        except Exception:
            pass

        # 3. WhatWeb (if installed)
        whatweb_result = self._whatweb(url)
        if "technologies" in whatweb_result:
            results["tech_stack"].extend(whatweb_result["technologies"])

        # Deduplicate tech stack
        results["tech_stack"] = list(dict.fromkeys(results["tech_stack"]))

        return results

    # ------------------------------------------------------------------
    # Nmap
    # ------------------------------------------------------------------

    def _nmap_scan(self, target: str, **kwargs: Any) -> dict:
        """Port scan + service detection."""
        ports = kwargs.get("ports", "1-10000")
        try:
            result = subprocess.run(
                [
                    "nmap", "-sV", "--open", "-p", ports,
                    "--max-retries", "1", "-T4",
                    "-oG", "-", target,
                ],
                capture_output=True, text=True, timeout=90,
            )
            return self._parse_nmap(result.stdout, target)
        except FileNotFoundError:
            return {"error": "nmap not installed. Run: apt install nmap"}
        except subprocess.TimeoutExpired:
            return {"error": "nmap timed out after 90s"}

    def _parse_nmap(self, output: str, target: str) -> dict:
        ports: list[dict] = []
        for line in output.split("\n"):
            if "/open/" in line:
                for match in re.finditer(r"(\d+)/open/(\w+)//([^/]*)", line):
                    ports.append({
                        "port": int(match.group(1)),
                        "state": "open",
                        "service": match.group(2),
                        "version": match.group(3).strip(),
                    })
        return {"host": target, "ports": ports}

    # ------------------------------------------------------------------
    # WhatWeb
    # ------------------------------------------------------------------

    def _whatweb(self, url: str, **kwargs: Any) -> dict:
        """Identify web technologies."""
        try:
            result = subprocess.run(
                ["whatweb", "--color=never", "-q", url],
                capture_output=True, text=True, timeout=30,
            )
            techs: list[str] = []
            for match in re.finditer(r"\[([^\]]+)\]", result.stdout):
                tech = match.group(1).strip()
                if tech and tech not in ("200 OK", "301", "302", "403", "404"):
                    techs.append(tech)
            return {"url": url, "technologies": techs}
        except FileNotFoundError:
            return {"url": url, "technologies": []}
        except subprocess.TimeoutExpired:
            return {"error": f"whatweb timed out"}

    # ------------------------------------------------------------------
    # Gobuster
    # ------------------------------------------------------------------

    def _gobuster(self, url: str, **kwargs: Any) -> dict:
        """Directory brute-force."""
        wordlist = kwargs.get("wordlist") or self._find_wordlist()
        if not wordlist:
            return {"error": "No wordlist found. Provide one via 'wordlist' parameter."}

        try:
            result = subprocess.run(
                [
                    "gobuster", "dir",
                    "-u", url,
                    "-w", wordlist,
                    "-q", "--no-error",
                    "-t", "20",
                ],
                capture_output=True, text=True, timeout=90,
            )
            found: list[dict] = []
            for line in result.stdout.split("\n"):
                match = re.match(r"(/\S+)\s+\(Status:\s*(\d+)\)", line)
                if match:
                    found.append({
                        "path": match.group(1),
                        "status": int(match.group(2)),
                    })
            return {"url": url, "found": found}
        except FileNotFoundError:
            return {"error": "gobuster not installed"}
        except subprocess.TimeoutExpired:
            return {"error": "gobuster timed out after 90s"}

    # ------------------------------------------------------------------
    # Nikto
    # ------------------------------------------------------------------

    def _nikto(self, url: str, **kwargs: Any) -> dict:
        """Web vulnerability scanner."""
        try:
            result = subprocess.run(
                [
                    "nikto", "-h", url, "-maxtime", "100",
                    "-nointeractive", "-C", "none",
                ],
                capture_output=True, text=True, timeout=120,
            )
            findings: list[str] = []
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line.startswith("+") and "host" not in line.lower():
                    finding = line.lstrip("+ ").strip()
                    if finding and len(finding) > 10:
                        findings.append(finding)
            return {"url": url, "findings": findings[:20]}
        except FileNotFoundError:
            return {"error": "nikto not installed. Run: apt install nikto"}
        except subprocess.TimeoutExpired:
            return {"error": "nikto timed out after 120s"}

    # ------------------------------------------------------------------
    # Subfinder
    # ------------------------------------------------------------------

    def _subfinder(self, domain: str, **kwargs: Any) -> dict:
        """Subdomain enumeration."""
        # Extract bare domain from URL if needed
        parsed = urlparse(domain)
        if parsed.netloc:
            domain = parsed.netloc
        domain = domain.split(":")[0]  # remove port

        try:
            result = subprocess.run(
                ["subfinder", "-d", domain, "-silent"],
                capture_output=True, text=True, timeout=30,
            )
            subs = [
                line.strip() for line in result.stdout.split("\n")
                if line.strip()
            ]
            return {"domain": domain, "subdomains": subs}
        except FileNotFoundError:
            return {"error": "subfinder not installed"}
        except subprocess.TimeoutExpired:
            return {"error": "subfinder timed out after 30s"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_wordlist() -> str | None:
        """Find a usable wordlist on the system."""
        candidates = [
            "/usr/share/wordlists/dirb/common.txt",
            "/usr/share/wordlists/dirbuster/directory-list-2.3-small.txt",
            "/usr/share/seclists/Discovery/Web-Content/common.txt",
            "/usr/share/wordlists/english.txt",
        ]
        for wl in candidates:
            if os.path.exists(wl):
                return wl
        return None
