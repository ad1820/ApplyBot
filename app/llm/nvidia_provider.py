"""NVIDIA NIM-backed LLM provider.

NVIDIA's hosted NIM API (https://integrate.api.nvidia.com/v1) exposes an
OpenAI-compatible /chat/completions endpoint. The primary model used here is
meta/muse-glimmer-30b -- a strong 30B reasoning/tool-calling model --
configurable via NVIDIA_NIM_MODEL.

The model name and API key must not be hard-coded outside centralised config:
NvidiaNIMProvider always receives them from settings (see app.llm.provider).

Muse Glimmer 30B is a reasoning-capable model: without disabling internal
chain-of-thought it can consume its entire token budget before emitting the
actual answer. {"chat_template_kwargs": {"enable_thinking": False}} is
NVIDIA's documented way to disable this for NIM-hosted models, confirmed
via live API testing to produce fast, clean answers directly in content.
"""
from __future__ import annotations

import httpx

from app.llm.openai_provider import OpenAICompatibleProvider

_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_DEFAULT_MODEL = "meta/muse-glimmer-30b"


class NvidiaNIMProvider(OpenAICompatibleProvider):
    name = "nvidia_nim"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL, client: httpx.Client | None = None):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=_API_URL,
            client=client,
            extra_request_fields={"chat_template_kwargs": {"enable_thinking": False}},
        )
