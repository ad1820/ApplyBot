"""Anthropic-backed LLM provider (HTTP via httpx, no heavy SDK dependency)."""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from app.llm.base import LLMError, LLMProvider
from app.llm.prompts import cover_letter_prompt, generative_answer_prompt, resume_analysis_prompt

_API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307", client: httpx.Client | None = None):
        self.api_key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=30.0)

    def complete(self, prompt: str, *, system: Optional[str] = None, max_tokens: int = 512) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        try:
            response = self._client.post(
                _API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return _extract_text(data["content"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Anthropic completion failed: {exc}") from exc

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


def _extract_text(content_blocks: list[dict[str, Any]]) -> str:
    """Some Claude models (e.g. with extended thinking enabled) return one
    or more non-text blocks (type "thinking", "redacted_thinking", etc.)
    before the actual text block. Find the first block with type "text"
    rather than assuming index 0 is always the answer."""
    for block in content_blocks:
        if block.get("type") == "text" and "text" in block:
            return block["text"]
    raise KeyError("text")


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap JSON in ```json ... ``` despite instructions
    not to - strip that defensively before parsing."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    return stripped.strip()
