"""Factory that selects the configured LLMProvider implementation."""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    provider_name = (settings.llm_provider or "null").lower()

    if provider_name == "openai" and settings.llm_api_key:
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=settings.llm_api_key, model=settings.llm_model)

    if provider_name == "anthropic" and settings.llm_api_key:
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.llm_api_key, model=settings.llm_model)

    from app.llm.null_provider import NullProvider

    return NullProvider()


def reset_provider_cache() -> None:
    get_llm_provider.cache_clear()
