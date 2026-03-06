"""Multi-provider LLM support.

Abstracts the LLM client so Q can use OpenAI, Anthropic (Claude),
and Google (Gemini) models with automatic routing by model name prefix.
"""
from agent.providers.router import ProviderRouter
from agent.providers.base import LLMProvider, SimpleUsage


def create_provider(model_config) -> ProviderRouter:
    """Factory: build a ProviderRouter from ModelConfig."""
    from agent.providers.openai_provider import OpenAIProvider
    from agent.providers.anthropic_provider import AnthropicProvider
    from agent.providers.google_provider import GoogleProvider

    providers = {}

    # OpenAI (always available if api_key set)
    if model_config.api_key:
        providers["openai"] = OpenAIProvider(api_key=model_config.api_key)

    # Anthropic (optional)
    anthropic_key = getattr(model_config, "anthropic_api_key", "")
    if anthropic_key:
        providers["anthropic"] = AnthropicProvider(api_key=anthropic_key)

    # Google (optional — requires google-generativeai package)
    google_key = getattr(model_config, "google_api_key", "")
    if google_key:
        try:
            import google.generativeai  # noqa: F401
            providers["google"] = GoogleProvider(api_key=google_key)
        except ImportError:
            import logging
            logging.getLogger(__name__).warning(
                "Google API key set but google-generativeai not installed. "
                "Run: pip install google-generativeai"
            )

    fallback = getattr(model_config, "fallback_model", "")
    return ProviderRouter(providers=providers, fallback_model=fallback)
