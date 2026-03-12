"""Agent handoff system — CAI-inspired transfer_to_X pattern.

Provides tool-based agent handoffs where the primary solver can transfer
control to specialized sub-agents:

- transfer_to_flag_discriminator: validate a candidate flag
- transfer_to_recon: run focused reconnaissance
- transfer_to_exploit: attempt a specific exploit vector

Each handoff runs a short sub-loop with a specialized prompt and tool set,
then returns its result to the parent agent.
"""
from __future__ import annotations

import json
from typing import Any

from tools.base import BaseTool, ToolParameter
from utils.logger import get_logger


class HandoffTool(BaseTool):
    """Agent handoff tool — transfers control to specialized sub-agents.

    The LLM calls this tool to delegate work to a specialist. The specialist
    runs a short focused loop and returns its findings.
    """

    name = "agent_handoff"
    description = (
        "Transfer control to a specialized sub-agent. Available targets: "
        "'flag_discriminator' (validate a candidate flag), "
        "'recon' (focused reconnaissance on a target), "
        "'exploit' (attempt a specific exploit technique). "
        "Returns the sub-agent's findings."
    )
    parameters = [
        ToolParameter(
            name="target",
            type="string",
            description="The sub-agent to transfer to.",
            enum=["flag_discriminator", "recon", "exploit"],
        ),
        ToolParameter(
            name="context",
            type="string",
            description=(
                "Context for the sub-agent. For flag_discriminator: the candidate "
                "flag and surrounding text. For recon: the target URL/host. "
                "For exploit: the technique and target details."
            ),
        ),
        ToolParameter(
            name="challenge_info",
            type="string",
            description="Brief challenge description for context.",
            required=False,
        ),
    ]

    def __init__(
        self,
        provider: Any = None,
        config: Any = None,
        custom_flag_pattern: str | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._custom_flag_pattern = custom_flag_pattern
        self._log = get_logger()

    def execute(
        self,
        target: str = "flag_discriminator",
        context: str = "",
        challenge_info: str = "",
        **kwargs: Any,
    ) -> str:
        """Execute the handoff to the specified sub-agent."""
        if target == "flag_discriminator":
            return self._handoff_flag_discriminator(context, challenge_info)
        elif target == "recon":
            return self._handoff_recon(context, challenge_info)
        elif target == "exploit":
            return self._handoff_exploit(context, challenge_info)
        else:
            return f"Unknown handoff target: {target}"

    def _handoff_flag_discriminator(self, context: str, challenge_info: str) -> str:
        """Validate a candidate flag using the FlagDiscriminator agent."""
        from agent.flag_discriminator import FlagDiscriminator

        discriminator = FlagDiscriminator(
            provider=self._provider,
            config=self._config,
            custom_pattern=self._custom_flag_pattern,
        )

        # Extract the candidate flag from context
        candidate = context.strip()
        # If context has more than just the flag, try to find flag-like patterns
        import re
        flag_match = re.search(r"[a-zA-Z0-9_]+\{[^}]+\}", candidate)
        if flag_match:
            candidate = flag_match.group(0)

        verdict = discriminator.validate(
            candidate=candidate,
            context=context,
            challenge_description=challenge_info,
        )

        if verdict.is_valid:
            return (
                f"FLAG VALIDATED ({verdict.confidence} confidence): {verdict.flag}\n"
                f"Reason: {verdict.reason}\n"
                f"Action: Submit this flag via answer_user."
            )
        else:
            return (
                f"FLAG REJECTED ({verdict.confidence} confidence): {verdict.flag}\n"
                f"Reason: {verdict.reason}\n"
                f"Action: This is likely a false positive. Continue investigating."
            )

    def _handoff_recon(self, context: str, challenge_info: str) -> str:
        """Run focused reconnaissance via a sub-agent loop."""
        if not self._provider or not self._config:
            return "Recon handoff unavailable: no LLM provider configured."

        try:
            model = self._config.model.fast_model
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a CTF reconnaissance specialist. Given a target, "
                        "provide a concise recon plan with specific commands to run. "
                        "Focus on: port scanning, service enumeration, directory "
                        "brute-forcing, and technology fingerprinting. "
                        "Output ONLY the commands and expected findings, no fluff."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Target: {context}\n"
                        f"Challenge: {challenge_info}\n\n"
                        f"Provide a focused recon plan."
                    ),
                },
            ]
            result = self._provider.chat(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=500,
            )
            return f"Recon specialist report:\n{result['message'].get('content', '')}"
        except Exception as exc:
            self._log.debug(f"Recon handoff failed: {exc}")
            return f"Recon handoff failed: {exc}"

    def _handoff_exploit(self, context: str, challenge_info: str) -> str:
        """Get exploit guidance from a specialist sub-agent."""
        if not self._provider or not self._config:
            return "Exploit handoff unavailable: no LLM provider configured."

        try:
            model = self._config.model.default_model
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a CTF exploitation specialist. Given a vulnerability "
                        "description and target, provide a precise exploitation strategy. "
                        "Include: exact payloads, tool commands, and expected output. "
                        "Be specific and actionable. Output the exploit steps only."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Vulnerability/technique: {context}\n"
                        f"Challenge: {challenge_info}\n\n"
                        f"Provide the exploitation strategy."
                    ),
                },
            ]
            result = self._provider.chat(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=800,
            )
            return f"Exploit specialist report:\n{result['message'].get('content', '')}"
        except Exception as exc:
            self._log.debug(f"Exploit handoff failed: {exc}")
            return f"Exploit handoff failed: {exc}"
