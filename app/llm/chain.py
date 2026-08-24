"""ProviderChain -- ordered failover across multiple LLMProviders.

Architecture
------------
Two independent chains are constructed by the factory (app.llm.provider):

  reasoning_chain     -- used by agents for complex reasoning / tool calling
  job_matching_chain  -- used by the job matcher for skill classification

Each chain is an ordered list of providers. On every call the chain:

  1. Tries the current provider.
  2. Returns immediately on success.
  3. On LLMTransientError (429, 5xx, timeout, network) -- logs a warning
     (no secrets) and moves to the next provider.
  4. On non-transient LLMError (401, 400, parse bug) -- logs an error and
     stops the chain (these are config / implementation bugs, not retryable).
  5. After all providers are exhausted (or a permanent error stops the chain)
     falls through to NullProvider safe-default behaviour.

The chain itself NEVER raises -- callers (resume_agent, cover_letter_agent,
job matcher) always receive a valid (possibly empty) response.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.llm.base import LLMError, LLMProvider, LLMTransientError
from app.llm.null_provider import NullProvider

logger = logging.getLogger(__name__)

_NULL = NullProvider()


class ProviderChain(LLMProvider):
    """Ordered failover chain across multiple LLMProviders.

    Failover only occurs on LLMTransientError (429, 5xx, timeout).
    Non-transient errors (401, 400) stop the chain immediately and are logged
    so implementation bugs surface clearly -- they are not silently swallowed.
    """

    def __init__(self, providers: list[LLMProvider]):
        if not providers:
            self._providers: list[LLMProvider] = [_NULL]
        else:
            self._providers = providers

    @property
    def name(self) -> str:  # type: ignore[override]
        names = "->".join(p.name for p in self._providers)
        return f"chain({names})"

    # ── Internal helpers ──────────────────────────────────────────────────

    def _try_providers(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call `method` on each provider in order, failing over on transient
        errors only. Returns the first successful result."""
        last_exc: Optional[Exception] = None
        for provider in self._providers:
            try:
                # Log which provider is handling this request
                logger.info(
                    "Routing LLM request",
                    extra={"extra_fields": {"provider": provider.name, "method": method, "status": "STARTED"}}
                )
                
                result = getattr(provider, method)(*args, **kwargs)
                
                logger.info(
                    "LLM request successful",
                    extra={"extra_fields": {"provider": provider.name, "method": method, "status": "SUCCESS"}}
                )
                return result
            except LLMTransientError as exc:
                logger.warning(
                    "LLM provider transient failure: provider=%s method=%s error=%s"
                    " — trying next provider",
                    provider.name,
                    method,
                    type(exc).__name__,
                )
                last_exc = exc
                continue
            except LLMError as exc:
                # Non-transient: bad request, auth error, or parse bug.
                # Log clearly so the issue surfaces; do NOT retry next provider.
                logger.error(
                    "LLM provider non-retryable error: provider=%s method=%s error=%s"
                    " — stopping chain",
                    provider.name,
                    method,
                    str(exc),
                )
                last_exc = exc
                break
        # All providers exhausted or chain stopped on permanent error.
        if last_exc:
            logger.warning(
                "All providers in chain exhausted/stopped for method=%s"
                " — falling back to null behaviour",
                method,
            )
        return None  # Callers map None to their own safe default

    # ── LLMProvider interface ─────────────────────────────────────────────

    def complete(self, prompt: str, *, system: Optional[str] = None, max_tokens: int = 512) -> str:
        result = self._try_providers("complete", prompt, system=system, max_tokens=max_tokens)
        return result if result is not None else ""

    def analyze_job_match(self, job_description: str, candidate_profile: dict[str, Any]) -> dict[str, Any]:
        result = self._try_providers("analyze_job_match", job_description, candidate_profile)
        return result if result is not None else {}

    def analyze_resume(
        self, job_description: str, master_resume: str, candidate_profile: dict[str, Any]
    ) -> dict[str, Any]:
        result = self._try_providers("analyze_resume", job_description, master_resume, candidate_profile)
        if result is not None:
            return result
        # Safe default matches NullProvider behaviour.
        return {
            "strong_skills": [],
            "missing_skills": [],
            "suggested_changes": [],
            "tailored_resume": master_resume,
        }

    def generate_cover_letter(
        self, job_description: str, resume_content: str, candidate_profile: dict[str, Any]
    ) -> str:
        result = self._try_providers("generate_cover_letter", job_description, resume_content, candidate_profile)
        return result if result is not None else ""

    def answer_generative_question(
        self, question: str, candidate_profile: dict[str, Any], job_description: str
    ) -> str:
        result = self._try_providers("answer_generative_question", question, candidate_profile, job_description)
        return result if result is not None else ""
