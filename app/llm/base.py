"""LLM provider abstraction.

The rest of the application must never hard-code a specific LLM vendor.
All LLM usage goes through this interface so a different provider can be
substituted without touching calling code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMError(RuntimeError):
    """Raised when an LLM call fails. Callers must catch this and degrade
    gracefully (e.g. fall back to deterministic logic) rather than crash."""


class LLMTransientError(LLMError):
    """Raised for retryable / transient provider failures: HTTP 429 (rate
    limit), quota exhausted, 5xx server errors, timeouts, and transient
    network failures. The ProviderChain uses this to decide whether to fail
    over to the next provider in the chain.

    Do NOT raise this for programming errors (400 bad request), auth failures
    (401 / 403), or response-parsing bugs — those are non-retryable and should
    be surfaced as plain LLMError so they are not silently swallowed."""


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str, *, system: Optional[str] = None, max_tokens: int = 512) -> str:
        """Return a raw text completion for the given prompt."""
        raise NotImplementedError

    def analyze_job_match(self, job_description: str, candidate_profile: dict[str, Any]) -> dict[str, Any]:
        """Optional semantic job-match analysis. Default implementation is a
        no-op so deterministic matching remains fully functional even if a
        provider doesn't implement this (or fails)."""
        return {}

    def analyze_resume(
        self, job_description: str, master_resume: str, candidate_profile: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError

    def generate_cover_letter(
        self, job_description: str, resume_content: str, candidate_profile: dict[str, Any]
    ) -> str:
        raise NotImplementedError

    def answer_generative_question(self, question: str, candidate_profile: dict[str, Any], job_description: str) -> str:
        raise NotImplementedError
