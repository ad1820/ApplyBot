"""Google Gemini-backed LLM provider (HTTP via httpx, no heavy SDK).

Uses the Gemini REST API:
  POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
  ?key={api_key}

Request body: {"contents": [{"role": "user", "parts": [{"text": "..."}]}],
               "systemInstruction": {"parts": [{"text": "..."}]},
               "generationConfig": {"maxOutputTokens": N}}

Response: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}

Both model names (primary / fallback) come from settings
(GEMINI_PRIMARY_MODEL, GEMINI_FALLBACK_MODEL) -- never hardcoded here.
All prompts come from app.llm.prompts -- no new prompt logic in this file.

Transient errors (429, 5xx, timeout) raise LLMTransientError so the
ProviderChain can fail over to the next provider in the chain.
Non-transient errors (400, 401, 403) raise plain LLMError -- these are
config / implementation bugs that should surface clearly.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from app.llm.base import LLMError, LLMProvider, LLMTransientError
from app.llm.openai_provider import _raise_for_status, _strip_code_fence
from app.llm.prompts import cover_letter_prompt, generative_answer_prompt, resume_analysis_prompt

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class GeminiProvider(LLMProvider):
    """Google Gemini provider using the Gemini generateContent REST API."""

    name = "gemini"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.model = model
        self.name = f"gemini:{model}"
        self._client = client or httpx.Client(timeout=30.0)

    def _url(self) -> str:
        return f"{_BASE_URL}/{self.model}:generateContent"

    def _post(self, payload: dict[str, Any]) -> str:
        """POST to Gemini API and return the text content.

        Raises LLMTransientError for retryable failures, LLMError otherwise.
        The API key is passed as a query parameter -- it must never appear in
        log messages (only the provider name and model are safe to log).
        """
        try:
            response = self._client.post(
                self._url(),
                params={"key": self.api_key},
                json=payload,
            )
            _raise_for_status(response, self.name)
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except LLMError:
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise LLMTransientError(
                f"{self.name} transient network error: {type(exc).__name__}"
            ) from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"{self.name} completion failed: {exc}") from exc

    def complete(self, prompt: str, *, system: Optional[str] = None, max_tokens: int = 512) -> str:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return self._post(payload)

    def analyze_resume(
        self, job_description: str, master_resume: str, candidate_profile: dict[str, Any]
    ) -> dict[str, Any]:
        system, user = resume_analysis_prompt(job_description, master_resume, candidate_profile)
        try:
            response = self.complete(user, system=system, max_tokens=1500)
        except LLMError:
            return {}
        try:
            parsed = json.loads(_strip_code_fence(response))
        except (ValueError, TypeError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def generate_cover_letter(
        self, job_description: str, resume_content: str, candidate_profile: dict[str, Any]
    ) -> str:
        system, user = cover_letter_prompt(job_description, resume_content, candidate_profile)
        return self.complete(user, system=system, max_tokens=600)

    def answer_generative_question(
        self, question: str, candidate_profile: dict[str, Any], job_description: str
    ) -> str:
        system, user = generative_answer_prompt(question, candidate_profile, job_description)
        return self.complete(user, system=system, max_tokens=300)
