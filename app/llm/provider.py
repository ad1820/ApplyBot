"""Factory that builds the two independent LLM provider chains.

Two chains are constructed dynamically from available credentials:

  reasoning_chain     -- for agent reasoning / tool-calling workflows
  job_matching_chain  -- for job-search skill classification

Both chains contain only providers whose credentials are actually configured;
the NullProvider is always the terminal fallback so the system starts cleanly
even when no API keys are present.

Chain priority order
--------------------
Reasoning chain:
  1. NvidiaNIMProvider    (meta/muse-glimmer-30b) -- preferred reasoning model
  2. GeminiProvider       (GEMINI_PRIMARY_MODEL)
  3. GeminiProvider       (GEMINI_FALLBACK_MODEL, if different from primary)
  4. GroqProvider         (GROQ_MODEL)
  5. NullProvider         (terminal)

Job matching chain:
  1. GeminiProvider       (GEMINI_PRIMARY_MODEL)
  2. GeminiProvider       (GEMINI_FALLBACK_MODEL, if different from primary)
  3. NvidiaNIMProvider    (meta/muse-glimmer-30b)
  4. GroqProvider         (GROQ_MODEL)
  5. NullProvider         (terminal)

Supported configurations (any subset of providers is valid):
  - No providers configured    -> NullProvider only
  - Gemini only                -> Gemini primary -> fallback -> Null
  - NVIDIA NIM only            -> NIM -> Null
  - Groq only                  -> Groq -> Null
  - All providers              -> full workflow-specific order above

Application startup never fails because an optional provider key is absent.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMProvider
from app.llm.chain import ProviderChain
from app.llm.null_provider import NullProvider

logger = logging.getLogger(__name__)


def _build_gemini_providers(settings) -> list[LLMProvider]:
    """Return 1-2 GeminiProviders (primary + optional fallback) if key set."""
    if not settings.gemini_api_key:
        return []
    from app.llm.gemini_provider import GeminiProvider

    providers: list[LLMProvider] = [
        GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_primary_model)
    ]
    if settings.gemini_fallback_model and settings.gemini_fallback_model != settings.gemini_primary_model:
        providers.append(
            GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_fallback_model)
        )
    return providers


def _build_nvidia_provider(settings) -> LLMProvider | None:
    if not settings.nvidia_nim_api_key:
        return None
    from app.llm.nvidia_provider import NvidiaNIMProvider

    return NvidiaNIMProvider(api_key=settings.nvidia_nim_api_key, model=settings.nvidia_nim_model)


def _build_groq_providers(settings) -> list[LLMProvider]:
    if not settings.groq_api_key or not settings.groq_models:
        return []
    from app.llm.groq_provider import GroqProvider
    
    models = [m.strip() for m in settings.groq_models.split(",") if m.strip()]
    return [GroqProvider(api_key=settings.groq_api_key, model=model) for model in models]


def build_reasoning_chain(settings) -> ProviderChain:
    """Build the agent reasoning / tool-calling provider chain.

    Priority: NvidiaNIM -> Gemini primary -> Gemini fallback -> Groq(s) -> Null
    """
    providers: list[LLMProvider] = []

    nvidia = _build_nvidia_provider(settings)
    if nvidia:
        providers.append(nvidia)

    providers.extend(_build_gemini_providers(settings))
    providers.extend(_build_groq_providers(settings))

    if not providers:
        logger.info("No LLM providers configured for reasoning chain -- using NullProvider")
        providers = [NullProvider()]

    logger.info(
        "Reasoning chain: %s",
        " -> ".join(p.name for p in providers),
    )
    return ProviderChain(providers)


def build_job_matching_chain(settings) -> ProviderChain:
    """Build the job-search / skill-classification provider chain.

    Priority: Gemini primary -> Gemini fallback -> NvidiaNIM -> Groq(s) -> Null
    """
    providers: list[LLMProvider] = []

    providers.extend(_build_gemini_providers(settings))

    nvidia = _build_nvidia_provider(settings)
    if nvidia:
        providers.append(nvidia)

    providers.extend(_build_groq_providers(settings))

    if not providers:
        logger.info("No LLM providers configured for job matching chain -- using NullProvider")
        providers = [NullProvider()]

    logger.info(
        "Job matching chain: %s",
        " -> ".join(p.name for p in providers),
    )
    return ProviderChain(providers)


@lru_cache
def get_llm_provider() -> LLMProvider:
    """Return the reasoning chain provider (used by agents).

    Cached so provider instances are reused across calls; call
    reset_provider_cache() to rebuild (e.g. in tests after monkeypatching).
    """
    return build_reasoning_chain(get_settings())


@lru_cache
def get_job_matching_provider() -> LLMProvider:
    """Return the job-matching chain provider (used by the skill checker).

    Cached independently from get_llm_provider() so the two chains can be
    constructed and reset separately in tests.
    """
    return build_job_matching_chain(get_settings())


def reset_provider_cache() -> None:
    """Clear both cached provider chains (for tests / config reload)."""
    get_llm_provider.cache_clear()
    get_job_matching_provider.cache_clear()
