"""OpenAI-backed LLM provider (HTTP via httpx, no heavy SDK dependency)."""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from app.llm.base import LLMError, LLMProvider
from app.llm.prompts import cover_letter_prompt, generative_answer_prompt, resume_analysis_prompt

_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", client: httpx.Client | None = None):
        self.api_key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=30.0)

    def complete(self, prompt: str, *, system: Optional[str] = None, max_tokens: int = 512) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            response = self._client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "max_tokens": max_tokens},
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"OpenAI completion failed: {exc}") from exc

    def analyze_job_match(self, job_description: str, candidate_profile: dict[str, Any]) -> dict[str, Any]:
        # Left intentionally simple - callers must treat any LLMError as a
        # signal to fall back to deterministic matching only.
        return {}

    def analyze_resume(
        self, job_description: str, master_resume: str, candidate_profile: dict[str, Any]
    ) -> dict[str, Any]:
        system, user = resume_analysis_prompt(job_description, master_resume, candidate_profile)
        try:
            response = self.complete(user, system=system, max_tokens=1500)
        except LLMError:
            # Caller (app.agents.resume_agent) treats an empty dict as "no
            # LLM enrichment available" and falls back to deterministic-only
            # analysis, which is still fully valid.
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


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap JSON in ```json ... ``` despite instructions
    not to - strip that defensively before parsing."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    return stripped.strip()
