"""Web search tool for looking up CVEs, writeups, documentation, and exploits.

Uses DuckDuckGo HTML search (no API key required) with an optional
Brave Search API key for higher quality results.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger


class WebSearchTool(BaseTool):
    """Search the web for CVEs, exploit writeups, documentation, and tools."""

    name = "web_search"
    description = (
        "Search the web for information relevant to CTF challenges. "
        "Use for: CVE details, exploit writeups, crypto attack techniques, "
        "tool documentation, similar challenge writeups, steganography tools. "
        "Returns titles, URLs, and snippets from search results."
    )
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="Search query (e.g. 'CVE-2021-3156 exploit', 'RSA wiener attack python', 'CTF heap pwn writeup')",
            required=True,
        ),
        ToolParameter(
            name="max_results",
            type="integer",
            description="Number of results to return (default 5, max 10)",
            required=False,
        ),
    ]

    def __init__(self, brave_api_key: str = "") -> None:
        self._brave_key = brave_api_key
        self._log = get_logger()

    def execute(self, query: str, max_results: int = 5, **_: Any) -> str:
        max_results = min(int(max_results), 10)

        try:
            import requests  # type: ignore
        except ImportError:
            raise RuntimeError(
                "web_search requires the requests library: pip install requests"
            )

        # Try Brave Search first if key is configured
        if self._brave_key:
            try:
                results = self._search_brave(requests, query, max_results)
                return self._format(results, query)
            except Exception as exc:
                self._log.debug(f"Brave search failed: {exc}, falling back to DDG")

        # DuckDuckGo HTML fallback (no key needed)
        try:
            results = self._search_ddg(requests, query, max_results)
            return self._format(results, query)
        except Exception as exc:
            return f"Web search failed: {exc}"

    def _search_brave(self, requests: Any, query: str, max_results: int) -> list[dict]:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "X-Subscription-Token": self._brave_key,
                "Accept": "application/json",
            },
            params={"q": query, "count": max_results},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        return results

    def _search_ddg(self, requests: Any, query: str, max_results: int) -> list[dict]:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            timeout=10,
        )
        resp.raise_for_status()

        # Extract result titles, snippets, and URLs from DDG HTML
        title_re = re.compile(r'class="result__a"[^>]*>([^<]+)</a>', re.IGNORECASE)
        snippet_re = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
        url_re = re.compile(r'class="result__url"[^>]*>\s*([^\s<]+)', re.IGNORECASE)

        titles = title_re.findall(resp.text)
        snippets = [re.sub(r"<[^>]+>", "", s).strip() for s in snippet_re.findall(resp.text)]
        urls = url_re.findall(resp.text)

        results = []
        for i in range(min(max_results, len(titles))):
            results.append({
                "title": titles[i].strip() if i < len(titles) else "",
                "url": urls[i].strip() if i < len(urls) else "",
                "snippet": snippets[i] if i < len(snippets) else "",
            })
        return results

    @staticmethod
    def _format(results: list[dict], query: str) -> str:
        if not results:
            return f"No results found for: {query}"
        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            if r["url"]:
                lines.append(f"   {r['url']}")
            if r["snippet"]:
                lines.append(f"   {r['snippet']}")
            lines.append("")
        return "\n".join(lines).strip()
