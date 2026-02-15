"""Evidence tracking for anti-hallucination.

Records all tool outputs so that every claim in the agent's answer
can be traced back to a concrete tool execution.  When the agent
produces an answer, extract_claims() pulls out verifiable data
(IPs, hashes, flags, credentials, file paths) and the tracker
checks whether each claim actually appeared in a tool output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceRecord:
    """Single piece of evidence from a tool execution."""

    tool: str
    command: str
    output: str  # truncated for storage


@dataclass
class EvidenceTracker:
    """Track what data actually came from tool outputs.

    Used by the orchestrator to verify that the agent's answer
    only contains data that was actually observed in tool results.
    """

    evidence: list[EvidenceRecord] = field(default_factory=list)

    def add(self, tool: str, command: str, output: str) -> None:
        """Record evidence from a tool execution.

        Args:
            tool: Tool name (e.g. "shell", "network").
            command: Stringified command / arguments.
            output: Raw tool output (truncated to 2000 chars).
        """
        self.evidence.append(EvidenceRecord(
            tool=tool,
            command=command,
            output=output[:2000],
        ))

    def contains(self, text: str) -> bool:
        """Check if *text* appears in any recorded tool output."""
        text_lower = text.lower()
        return any(
            text_lower in e.output.lower()
            for e in self.evidence
        )

    def get_source(self, text: str) -> str | None:
        """Return the tool+command that produced *text*, or ``None``."""
        text_lower = text.lower()
        for e in self.evidence:
            if text_lower in e.output.lower():
                return f"{e.tool}: {e.command}"
        return None

    def verify_claims(self, claims: list[str]) -> tuple[list[str], list[str]]:
        """Split *claims* into verified and unverified lists.

        Returns:
            (verified, unverified) — each a list of claim strings.
        """
        verified: list[str] = []
        unverified: list[str] = []
        for claim in claims:
            if self.contains(claim):
                verified.append(claim)
            else:
                unverified.append(claim)
        return verified, unverified

    def build_evidence_chain(self, claims: list[str]) -> list[dict[str, Any]]:
        """Build an evidence chain mapping each claim to its source.

        Returns:
            List of dicts with keys: claim, verified, source.
        """
        chain: list[dict[str, Any]] = []
        for claim in claims:
            source = self.get_source(claim)
            chain.append({
                "claim": claim,
                "verified": source is not None,
                "source": source or "UNVERIFIED",
            })
        return chain


# ------------------------------------------------------------------
# Claim extraction
# ------------------------------------------------------------------

# Common false-positive IPs that appear in many contexts
_IGNORE_IPS = {"0.0.0.0", "127.0.0.1", "255.255.255.255"}


def extract_claims(answer: str) -> list[str]:
    """Extract verifiable claims from the agent's answer.

    Looks for IP addresses, hashes, flags, file paths, and
    credentials mentioned in the answer text.

    Args:
        answer: The agent's final answer string.

    Returns:
        Deduplicated list of claim strings.
    """
    claims: list[str] = []

    # IP addresses
    ips = re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", answer)
    claims.extend(ip for ip in ips if ip not in _IGNORE_IPS)

    # Hashes (MD5 = 32 hex, SHA-1 = 40, SHA-256 = 64)
    hashes = re.findall(r"\b[a-fA-F0-9]{32,64}\b", answer)
    claims.extend(hashes)

    # Flags (common CTF formats)
    flags = re.findall(r"[a-zA-Z0-9_]+\{[^}]+\}", answer)
    claims.extend(flags)

    # File paths mentioned as findings
    paths = re.findall(r"/[\w./\-]+\.\w+", answer)
    claims.extend(paths)

    # Usernames/passwords in context of "the password is X"
    creds = re.findall(
        r"(?:password|username|user|pass|login)\s*(?:is|was|:)\s*[\"']?(\S+)[\"']?",
        answer,
        re.IGNORECASE,
    )
    claims.extend(creds)

    # Port numbers mentioned explicitly ("port 8080", "on port 443")
    ports = re.findall(r"(?:port)\s+(\d{2,5})\b", answer, re.IGNORECASE)
    claims.extend(ports)

    # Domain names / hostnames
    domains = re.findall(
        r"\b(?:[a-zA-Z0-9-]+\.)+(?:com|net|org|io|edu|gov|mil|info|xyz|onion)\b",
        answer,
    )
    claims.extend(domains)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in claims:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique
