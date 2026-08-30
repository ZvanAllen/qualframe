from __future__ import annotations

from qualframe.models import ProviderConfig
from qualframe.providers.base import LLMProvider
from qualframe.providers.mock_provider import MockProvider


def build_provider(config: ProviderConfig) -> LLMProvider:
    """Instantiate the correct provider from a ProviderConfig."""
    if config.name == "cached_demo":
        from qualframe.providers.cached_demo_provider import CachedDemoProvider

        return CachedDemoProvider()
    if config.name == "anthropic":
        from qualframe.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            model=config.model or "claude-opus-4-6",
            api_key_env=config.api_key_env or "ANTHROPIC_API_KEY",
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
    if config.name == "openai":
        from qualframe.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            model=config.model or "gpt-4o",
            api_key_env=config.api_key_env or "OPENAI_API_KEY",
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
    if config.name == "google":
        from qualframe.providers.google_provider import GoogleProvider

        return GoogleProvider(
            model=config.model or "gemini-1.5-pro",
            api_key_env=config.api_key_env or "GOOGLE_API_KEY",
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
    return MockProvider(model=config.model or "mock")
