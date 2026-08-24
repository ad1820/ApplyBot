"""OpenAI-backed LLM provider (HTTP via httpx, no heavy SDK dependency)."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from app.llm.base import LLMError, LLMProvider, LLMTransientError
from app.llm.prompts import cover_letter_prompt, generative_answer_prompt, resume_analysis_prompt

_API_URL = "https://api.openai.com/v1/chat/completions"

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_inline_reasoning_block(content: str) -> str:
    """Some reasoning models (e.g. Groq's qwen/qwen3.6-27b) embed their
    chain-of-thought directly inside message.content as a <think>...</think>
    block, rather than in a separate field the way OpenAI/Nvidia's APIs
    expose reasoning_content - confirmed by direct API testing. Strip it so
    callers (semantic skill checks, resume JSON parsing, etc.) only ever see
    the actual answer, never the model's internal reasoning trace.
    """
    if not content:
        return content
    return _THINK_BLOCK_RE.sub("", content).strip()


# HTTP status codes that indicate a transient / retryable server-side failure
# (rate limit, capacity, gateway error). All other HTTP errors are treated as
# permanent (programming error, bad request, or auth failure) and are NOT
# retried - they should surface clearly for debugging.
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


def _raise_for_status(response: httpx.Response, provider_name: str) -> None:
    """Raise LLMTransientError or LLMError depending on the HTTP status code.

    Callers must NOT expose api_key or any auth header in the message.
    """
    if response.is_success:
        return
    code = response.status_code
    if code in _TRANSIENT_STATUS_CODES:
        raise LLMTransientError(
            f"{provider_name} transient HTTP {code} — will try next provider"
        )
    raise LLMError(
        f"{provider_name} non-retryable HTTP {code} — check API key / request format"
    )


class OpenAICompatibleProvider(LLMProvider):
    """Base class for any provider exposing an OpenAI-compatible
    /v1/chat/completions endpoint (model, messages[], max_tokens in;
    choices[0].message.content out). OpenAI itself, Nvidia NIM, and Groq
    Cloud all speak this exact shape, so a single implementation covers all
    three - only the base_url, default model and any extra request fields
    differ per concrete subclass (see app.llm.nvidia_provider /
    app.llm.groq_provider).

    `extra_request_fields` lets a subclass inject provider-specific
    parameters into every request - e.g. Nvidia's
    {"chat_template_kwargs": {"enable_thinking": False}} or Groq's
    {"reasoning_effort": "none"} - both confirmed via live API testing to
    suppress the model's internal reasoning trace so short, deterministic
    answers (e.g. the matcher's yes/no semantic skill check) come back
    quickly without needing an enormous max_tokens budget just to let a
    reasoning model "think" before it can answer.
    """

    name = "openai_compatible"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = _API_URL,
        client: httpx.Client | None = None,
        extra_request_fields: Optional[dict[str, Any]] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = client or httpx.Client(timeout=30.0)
        self.extra_request_fields = extra_request_fields or {}

    def complete(self, prompt: str, *, system: Optional[str] = None, max_tokens: int = 512) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        payload.update(self.extra_request_fields)
        try:
            response = self._client.post(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            _raise_for_status(response, self.name)
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return _strip_inline_reasoning_block(content)
        except LLMError:
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise LLMTransientError(f"{self.name} transient network error: {type(exc).__name__}") from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"{self.name} completion failed: {exc}") from exc

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


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", client: httpx.Client | None = None):
        super().__init__(api_key=api_key, model=model, base_url=_API_URL, client=client)


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap JSON in ```json ... ``` despite instructions
    not to - strip that defensively before parsing."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    return stripped.strip()
