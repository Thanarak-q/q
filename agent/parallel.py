"""Parallel approach solver.

When the primary single-agent solve fails and the challenge has
multiple viable attack vectors, this module spawns concurrent
attempts — each with a different approach hint and a small step
budget — and returns the first successful result.

Because the existing agent loop is synchronous (blocking OpenAI
client), parallelism is achieved via ``concurrent.futures.ThreadPoolExecutor``.
Each thread gets its own ``Orchestrator`` instance (and thus its own
OpenAI client, context, and cost tracker).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger


@dataclass
class AttemptResult:
    """Outcome of a single parallel attempt."""

    approach: str
    success: bool
    answer: str = ""
    flag: str = ""
    flags: list[str] = field(default_factory=list)
    steps: int = 0
    tokens: int = 0
    cost: float = 0.0
    error: str = ""


# Default approaches per category
CATEGORY_APPROACHES: dict[str, list[dict[str, Any]]] = {
    "web": [
        {
            "name": "SQL Injection",
            "hint": (
                "Focus on SQL injection: test all input fields, URL parameters, "
                "and cookies with SQLi payloads. Try UNION-based, boolean-blind, "
                "and time-based techniques."
            ),
            "max_steps": 6,
        },
        {
            "name": "Auth Bypass",
            "hint": (
                "Focus on authentication bypass: try default credentials, "
                "JWT manipulation (alg:none, weak secret), cookie tampering, "
                "mass assignment, PHP type juggling."
            ),
            "max_steps": 6,
        },
        {
            "name": "SSTI / LFI / Command Injection",
            "hint": (
                "Focus on server-side attacks: try SSTI ({{7*7}}), "
                "LFI (../../etc/passwd, php://filter), "
                "and command injection (; id, | id, $(id))."
            ),
            "max_steps": 6,
        },
    ],
    "crypto": [
        {
            "name": "Encoding Chain",
            "hint": (
                "Try decoding chains: base64, hex, rot13, URL-encoding, "
                "binary. Look for nested encodings."
            ),
            "max_steps": 4,
        },
        {
            "name": "RSA Attack",
            "hint": (
                "Try RSA attacks: factor small n, Wiener's attack for "
                "large e, common modulus, Hastad's broadcast attack."
            ),
            "max_steps": 6,
        },
        {
            "name": "Classical Cipher",
            "hint": (
                "Try classical ciphers: Caesar/ROT, Vigenere, substitution, "
                "XOR with common keys, transposition."
            ),
            "max_steps": 5,
        },
    ],
    "forensics": [
        {
            "name": "Network Analysis",
            "hint": (
                "Use tshark to analyze traffic: conversations, HTTP objects, "
                "follow TCP streams, look for credentials or flags in transit."
            ),
            "max_steps": 5,
        },
        {
            "name": "File Carving",
            "hint": (
                "Use binwalk/foremost to extract hidden files. "
                "Check for embedded archives, images, or executables."
            ),
            "max_steps": 5,
        },
        {
            "name": "Metadata / Strings",
            "hint": (
                "Check exiftool metadata, strings output with grep for flag, "
                "hex editor patterns, steganography tools."
            ),
            "max_steps": 4,
        },
    ],
    "reverse": [
        {
            "name": "Static Analysis",
            "hint": (
                "Disassemble with objdump/radare2, decompile if possible, "
                "look for string comparisons, hardcoded keys, XOR loops."
            ),
            "max_steps": 6,
        },
        {
            "name": "Dynamic Analysis",
            "hint": (
                "Run the binary with test inputs, use ltrace/strace, "
                "set breakpoints at comparison functions with gdb."
            ),
            "max_steps": 6,
        },
    ],
}


class ParallelSolver:
    """Try multiple approaches concurrently, return first success."""

    def __init__(
        self,
        config: Any,
        docker_manager: Any = None,
        workspace: Path | None = None,
        max_parallel: int = 3,
        callbacks: Any = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._config = config
        self._docker = docker_manager
        self._workspace = workspace or Path.cwd()
        self._max_parallel = max_parallel
        self._cb = callbacks
        self._cancel_event = cancel_event or threading.Event()
        self._log = get_logger()

    def solve_parallel(
        self,
        description: str,
        category: str,
        approaches: list[dict[str, Any]] | None = None,
        files: list[Path] | None = None,
        target_url: str | None = None,
        flag_pattern: str | None = None,
    ) -> AttemptResult | None:
        """Try multiple approaches in parallel.

        Args:
            description: Challenge description.
            category: Challenge category string.
            approaches: Optional custom approaches. If None, uses defaults.
            files: Challenge files.
            target_url: Target URL.
            flag_pattern: Custom flag regex.

        Returns:
            AttemptResult of the first success, or the best partial, or None.
        """
        if approaches is None:
            approaches = CATEGORY_APPROACHES.get(category, [])

        if not approaches:
            self._log.info(f"No parallel approaches defined for category: {category}")
            return None

        # Check cancellation before spawning threads
        if self._cancel_event.is_set():
            self._log.info("Parallel solver cancelled before start")
            return None

        approaches = approaches[: self._max_parallel]

        self._log.info(
            f"Parallel solve: {len(approaches)} approaches for '{category}'"
        )

        # Notify UI
        if self._cb:
            names = [a["name"] for a in approaches]
            self._cb.on_phase(
                "Parallel",
                f"Trying {len(approaches)} approaches: {', '.join(names)}",
            )

        results: list[AttemptResult] = []

        with ThreadPoolExecutor(max_workers=len(approaches)) as pool:
            futures = {
                pool.submit(
                    self._try_approach,
                    description=description,
                    approach=approach,
                    files=files,
                    target_url=target_url,
                    flag_pattern=flag_pattern,
                ): approach["name"]
                for approach in approaches
            }

            for future in as_completed(futures):
                # Check cancellation between completed futures
                if self._cancel_event.is_set():
                    self._log.info("Parallel solver cancelled")
                    for f in futures:
                        f.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    return None

                name = futures[future]
                try:
                    result = future.result(timeout=180)
                except Exception as exc:
                    self._log.warning(f"Approach '{name}' raised: {exc}")
                    result = AttemptResult(
                        approach=name,
                        success=False,
                        error=str(exc),
                    )

                results.append(result)

                if result.success:
                    self._log.info(f"Approach '{name}' succeeded!")
                    if self._cb:
                        self._cb.on_phase("Parallel", f"'{name}' succeeded!")
                    # Cancel remaining futures
                    for f in futures:
                        f.cancel()
                    return result
                else:
                    self._log.info(f"Approach '{name}' failed")
                    if self._cb:
                        self._cb.on_phase("Parallel", f"'{name}' failed")

        # All failed — return best partial
        if results:
            return self._best_partial(results)
        return None

    def _try_approach(
        self,
        description: str,
        approach: dict[str, Any],
        files: list[Path] | None,
        target_url: str | None,
        flag_pattern: str | None,
    ) -> AttemptResult:
        """Run a single approach in its own Orchestrator."""
        # Import here to avoid circular imports
        from agent.orchestrator import NullCallbacks, Orchestrator

        modified_desc = (
            f"{description}\n\n"
            f"APPROACH HINT: {approach['hint']}\n"
            f"Focus on this specific approach. "
            f"If it doesn't work within {approach.get('max_steps', 5)} steps, "
            f"call answer_user with whatever you found."
        )

        try:
            orch = Orchestrator(
                config=self._config,
                docker_manager=self._docker,
                workspace=self._workspace,
                callbacks=NullCallbacks(),
            )
            # Share the cancel event so Ctrl+C propagates into threads
            orch._cancel_event = self._cancel_event

            result = orch.solve(
                description=modified_desc,
                files=files,
                target_url=target_url,
                flag_pattern=flag_pattern,
            )

            return AttemptResult(
                approach=approach["name"],
                success=result.success,
                answer=result.answer,
                flag=result.flags[0] if result.flags else "",
                flags=result.flags,
                steps=result.iterations,
                tokens=result.total_tokens,
                cost=result.cost_usd,
            )
        except Exception as exc:
            return AttemptResult(
                approach=approach["name"],
                success=False,
                error=str(exc),
            )

    @staticmethod
    def _best_partial(results: list[AttemptResult]) -> AttemptResult:
        """Pick the best partial result from failed attempts."""
        # Prefer those with an answer
        with_answer = [r for r in results if r.answer]
        if with_answer:
            return max(with_answer, key=lambda r: r.steps)
        # Otherwise pick the one that ran most steps
        return max(results, key=lambda r: r.steps)
