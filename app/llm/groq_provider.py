"""Groq Cloud-backed LLM provider.

Groq's API (https://api.groq.com/openai/v1) exposes an OpenAI-compatible
/chat/completions endpoint, so the same OpenAICompatibleProvider logic used
for OpenAI/Nvidia applies unchanged -- only the base_url and model differ.

The exact model is configured via GROQ_MODEL (see app.config.Settings).
Large production models recommended (>15B parameters):
    openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.6-27b

Reasoning effort control
------------------------
All three default models are reasoning-capable and can consume most of a
small max_tokens budget on chain-of-thought before emitting the answer.
Groq's reasoning_effort parameter minimises this; accepted values differ
per model family (confirmed via live 400 responses):
  qwen/qwen3.6-27b  -> "none" or "default"
  openai/gpt-oss-*  -> "low" | "medium" | "high"
_REASONING_EFFORT_BY_MODEL_PREFIX maps each known family to the lowest
value; unrecognized models get no override.

qwen/qwen3.6-27b also embeds reasoning inside message.content as a
<think>...</think> block -- OpenAICompatibleProvider.complete() strips
this automatically via _strip_inline_reasoning_block().
"""
from __future__ import annotations

import httpx

from app.llm.openai_provider import OpenAICompatibleProvider

_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Lowest/off reasoning_effort accepted by each known model family.
_REASONING_EFFORT_BY_MODEL_PREFIX = {
    "openai/gpt-oss": "low",
    "qwen/": "none",
}


def _reasoning_effort_for_model(model: str) -> str | None:
    for prefix, value in _REASONING_EFFORT_BY_MODEL_PREFIX.items():
        if model.startswith(prefix):
            return value
    return None


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None):
        effort = _reasoning_effort_for_model(model)
        extra_fields = {"reasoning_effort": effort} if effort else {}
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=_API_URL,
            client=client,
            extra_request_fields=extra_fields,
        )
