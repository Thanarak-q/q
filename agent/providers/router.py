"""Provider router -- delegates to the correct LLM provider by model name."""
from __future__ import annotations

from typing import Any, Iterator

from agent.providers.base import LLMProvider, SimpleUsage
from utils.logger import get_logger

PROVIDER_PREFIXES: list[tuple[str, str]] = [
    ("gpt-", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("o1", "openai"),
    ("claude-", "anthropic"),
    ("gemini-", "google"),
]


def resolve_provider(model_name: str) -> str:
    """Resolve a model name to a provider key."""
    for prefix, provider in PROVIDER_PREFIXES:
        if model_name.startswith(prefix):
            return provider
    return "openai"  # default fallback


class ProviderRouter:
    """Routes LLM calls to the appropriate provider based on model name."""

    def __init__(self, providers: dict[str, LLMProvider], fallback_model: str = "") -> None:
        self._providers = providers
        self._fallback_model = fallback_model
        self._log = get_logger()

    def chat(self, model: str, messages: list[dict[str, Any]], **kwargs) -> dict[str, Any]:
        """Route a chat call to the appropriate provider."""
        provider_key = resolve_provider(model)
        provider = self._providers.get(provider_key)
        if provider is None:
            if self._fallback_model:
                self._log.warning(
                    f"Provider '{provider_key}' not configured for model '{model}', "
                    f"falling back to '{self._fallback_model}'"
                )
                return self.chat(self._fallback_model, messages, **kwargs)
            raise ValueError(
                f"No provider configured for model '{model}' (resolved to '{provider_key}')"
            )
        try:
            return provider.chat(model=model, messages=messages, **kwargs)
        except Exception as exc:
            if self._fallback_model and self._fallback_model != model:
                self._log.warning(
                    f"Provider '{provider_key}' failed for '{model}': {exc}. "
                    f"Falling back to '{self._fallback_model}'"
                )
                return self.chat(self._fallback_model, messages, **kwargs)
            raise

    def chat_stream(self, model: str, messages: list[dict[str, Any]], **kwargs) -> Iterator[dict[str, Any]]:
        """Route a streaming chat call to the appropriate provider."""
        provider_key = resolve_provider(model)
        provider = self._providers.get(provider_key)
        if provider is None:
            if self._fallback_model:
                self._log.warning(
                    f"Provider '{provider_key}' not configured, "
                    f"falling back to '{self._fallback_model}'"
                )
                yield from self.chat_stream(self._fallback_model, messages, **kwargs)
                return
            raise ValueError(f"No provider configured for model '{model}'")
        try:
            yield from provider.chat_stream(model=model, messages=messages, **kwargs)
        except Exception as exc:
            if self._fallback_model and self._fallback_model != model:
                self._log.warning(
                    f"Streaming failed for '{model}': {exc}. "
                    f"Falling back to '{self._fallback_model}'"
                )
                yield from self.chat_stream(self._fallback_model, messages, **kwargs)
                return
            raise
