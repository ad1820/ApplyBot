"""Tests for LLM providers, ProviderChain, and the chain factory.

All tests are fully offline -- mock httpx transports only, no real API calls.
"""
import httpx
import pytest

from app.llm.base import LLMError, LLMTransientError
from app.llm.chain import ProviderChain
from app.llm.groq_provider import GroqProvider
from app.llm.null_provider import NullProvider
from app.llm.nvidia_provider import NvidiaNIMProvider
from app.llm.openai_provider import OpenAIProvider, _raise_for_status
from app.llm.provider import (
    build_job_matching_chain,
    build_reasoning_chain,
    get_job_matching_provider,
    get_llm_provider,
    reset_provider_cache,
)
from app.config import get_settings


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ok_client(content: str) -> httpx.Client:
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _status_client(status_code: int) -> httpx.Client:
    def handler(request):
        return httpx.Response(status_code, json={"error": "boom"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _make_provider(name: str, reply: str | None = None, *, fail: bool = False, transient: bool = False):
    """Fake provider for chain tests."""
    provider = NullProvider()
    provider.name = name
    calls = []

    def complete(prompt, *, system=None, max_tokens=512):
        calls.append(prompt)
        if transient:
            raise LLMTransientError(f"{name} transient")
        if fail:
            raise LLMError(f"{name} permanent error")
        return reply or f"{name}-reply"

    provider.complete = complete
    provider.calls = calls
    return provider


# ─── NullProvider ─────────────────────────────────────────────────────────────

def test_null_provider_never_raises_and_returns_safe_defaults():
    provider = NullProvider()
    assert provider.complete("hi") == ""
    resume_analysis = provider.analyze_resume("jd", "master resume text", {})
    assert resume_analysis["tailored_resume"] == "master resume text"
    assert provider.generate_cover_letter("jd", "resume", {}) == ""


# ─── OpenAIProvider ───────────────────────────────────────────────────────────

def test_openai_provider_raises_llm_error_on_500():
    provider = OpenAIProvider(api_key="fake", client=_status_client(500))
    with pytest.raises(LLMTransientError):
        provider.complete("hello")


def test_openai_provider_raises_llm_transient_error_on_429():
    provider = OpenAIProvider(api_key="fake", client=_status_client(429))
    with pytest.raises(LLMTransientError):
        provider.complete("hello")


def test_openai_provider_raises_non_transient_llm_error_on_401():
    provider = OpenAIProvider(api_key="bad-key", client=_status_client(401))
    with pytest.raises(LLMError) as exc_info:
        provider.complete("hello")
    # Must be plain LLMError, not LLMTransientError
    assert type(exc_info.value) is LLMError


def test_openai_provider_raises_non_transient_llm_error_on_400():
    provider = OpenAIProvider(api_key="fake", client=_status_client(400))
    with pytest.raises(LLMError) as exc_info:
        provider.complete("hello")
    assert type(exc_info.value) is LLMError


def test_openai_provider_parses_successful_completion():
    provider = OpenAIProvider(api_key="fake", client=_ok_client("hi there"))
    assert provider.complete("hello") == "hi there"


def test_openai_analyze_resume_parses_valid_json():
    payload = '{"strong_skills": ["python"], "missing_skills": ["aws"], "suggested_changes": ["Emphasize python"], "tailored_resume": "My resume"}'
    provider = OpenAIProvider(api_key="fake", client=_ok_client(payload))
    result = provider.analyze_resume("Job needs Python", "My resume", {"skills": ["python"]})
    assert result["strong_skills"] == ["python"]
    assert result["tailored_resume"] == "My resume"


def test_openai_analyze_resume_strips_markdown_code_fence():
    payload = '```json\n{"strong_skills": [], "missing_skills": [], "suggested_changes": [], "tailored_resume": "R"}\n```'
    provider = OpenAIProvider(api_key="fake", client=_ok_client(payload))
    result = provider.analyze_resume("jd", "R", {})
    assert result["tailored_resume"] == "R"


def test_openai_analyze_resume_returns_empty_dict_on_malformed_json():
    provider = OpenAIProvider(api_key="fake", client=_ok_client("not json at all"))
    result = provider.analyze_resume("jd", "resume", {})
    assert result == {}


def test_openai_analyze_resume_returns_empty_dict_on_llm_failure():
    provider = OpenAIProvider(api_key="fake", client=_status_client(500))
    result = provider.analyze_resume("jd", "resume", {})
    assert result == {}


def test_openai_generate_cover_letter_returns_text():
    provider = OpenAIProvider(api_key="fake", client=_ok_client("Dear hiring manager, ..."))
    result = provider.generate_cover_letter("jd", "resume", {"name": "Alice"})
    assert result == "Dear hiring manager, ..."


def test_openai_answer_generative_question_returns_text():
    provider = OpenAIProvider(api_key="fake", client=_ok_client("Because I love building things."))
    result = provider.answer_generative_question("Why do you want to work here?", {"name": "Alice"}, "jd")
    assert result == "Because I love building things."


# ─── _raise_for_status helper ─────────────────────────────────────────────────

def test_raise_for_status_success_does_not_raise():
    resp = httpx.Response(200)
    _raise_for_status(resp, "test")  # should not raise


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_raise_for_status_transient_codes_raise_transient_error(code):
    resp = httpx.Response(code)
    with pytest.raises(LLMTransientError):
        _raise_for_status(resp, "test")


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_raise_for_status_permanent_codes_raise_llm_error(code):
    resp = httpx.Response(code)
    with pytest.raises(LLMError) as exc_info:
        _raise_for_status(resp, "test")
    assert type(exc_info.value) is LLMError  # not transient subclass


def test_raise_for_status_api_key_not_in_error_message():
    """API keys must never appear in error messages (no secrets in logs)."""
    resp = httpx.Response(401)
    try:
        _raise_for_status(resp, "test_provider")
    except LLMError as exc:
        assert "sk-" not in str(exc)
        assert "Bearer" not in str(exc)


# ─── NvidiaNIMProvider ────────────────────────────────────────────────────────

def test_nvidia_nim_provider_name_is_nvidia_nim():
    provider = NvidiaNIMProvider(api_key="fake", client=_ok_client("ok"))
    assert provider.name == "nvidia_nim"


def test_nvidia_nim_provider_default_model_is_muse_glimmer():
    from app.llm.nvidia_provider import _DEFAULT_MODEL
    assert _DEFAULT_MODEL == "meta/muse-glimmer-30b"


def test_nvidia_nim_provider_disables_thinking_by_default():
    """meta/muse-glimmer-30b is a reasoning model; thinking must be disabled
    so it does not consume its entire token budget on chain-of-thought."""
    captured = {}

    def handler(request):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = NvidiaNIMProvider(api_key="fake", client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider.complete("hello")
    assert captured["body"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_nvidia_nim_provider_parses_openai_compatible_response():
    def handler(request):
        assert "integrate.api.nvidia.com" in str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "nvidia reply"}}]})

    provider = NvidiaNIMProvider(api_key="fake", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.complete("hello") == "nvidia reply"


def test_nvidia_nim_provider_raises_transient_error_on_429():
    provider = NvidiaNIMProvider(api_key="fake", client=_status_client(429))
    with pytest.raises(LLMTransientError):
        provider.complete("hello")


def test_nvidia_nim_provider_raises_llm_error_on_401():
    provider = NvidiaNIMProvider(api_key="bad", client=_status_client(401))
    with pytest.raises(LLMError) as exc_info:
        provider.complete("hello")
    assert type(exc_info.value) is LLMError


# ─── GroqProvider ─────────────────────────────────────────────────────────────

def test_groq_provider_uses_low_reasoning_effort_for_gpt_oss_models():
    captured = {}

    def handler(request):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = GroqProvider(api_key="fake", model="openai/gpt-oss-120b",
                            client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider.complete("hello")
    assert captured["body"]["reasoning_effort"] == "low"


def test_groq_provider_uses_none_reasoning_effort_for_qwen_models():
    captured = {}

    def handler(request):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = GroqProvider(api_key="fake", model="qwen/qwen3.6-27b",
                            client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider.complete("hello")
    assert captured["body"]["reasoning_effort"] == "none"


def test_groq_provider_no_reasoning_effort_override_for_unknown_models():
    captured = {}

    def handler(request):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = GroqProvider(api_key="fake", model="some-future-model",
                            client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider.complete("hello")
    assert "reasoning_effort" not in captured["body"]


def test_groq_provider_parses_openai_compatible_response():
    def handler(request):
        assert "api.groq.com" in str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "groq reply"}}]})

    provider = GroqProvider(api_key="fake", model="openai/gpt-oss-120b",
                            client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.complete("hello") == "groq reply"
    assert provider.name == "groq"


def test_groq_provider_strips_inline_think_block_from_content():
    raw_content = "\n<think>\nSome internal reasoning here.\nMore reasoning.\n</think>\n\nOK"

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": raw_content}}]})

    provider = GroqProvider(api_key="fake", model="qwen/qwen3.6-27b",
                            client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.complete("hello") == "OK"


def test_groq_provider_raises_transient_error_on_429():
    provider = GroqProvider(api_key="fake", model="openai/gpt-oss-120b", client=_status_client(429))
    with pytest.raises(LLMTransientError):
        provider.complete("hello")


def test_groq_provider_raises_llm_error_on_401():
    provider = GroqProvider(api_key="bad", model="openai/gpt-oss-120b", client=_status_client(401))
    with pytest.raises(LLMError) as exc_info:
        provider.complete("hello")
    assert type(exc_info.value) is LLMError


# ─── ProviderChain ────────────────────────────────────────────────────────────

def test_provider_chain_returns_first_successful_result():
    a = _make_provider("a", reply="a-reply")
    b = _make_provider("b", reply="b-reply")
    chain = ProviderChain([a, b])
    assert chain.complete("hi") == "a-reply"
    assert len(a.calls) == 1
    assert len(b.calls) == 0


def test_provider_chain_fails_over_on_transient_error():
    a = _make_provider("a", transient=True)
    b = _make_provider("b", reply="b-reply")
    chain = ProviderChain([a, b])
    assert chain.complete("hi") == "b-reply"


def test_provider_chain_does_not_fail_over_on_permanent_error():
    """Non-transient LLMError stops the chain -- next provider is NOT tried."""
    a = _make_provider("a", fail=True)  # raises LLMError (non-transient)
    b = _make_provider("b", reply="b-reply")
    chain = ProviderChain([a, b])
    result = chain.complete("hi")
    # Chain stopped after provider a's permanent error; provider b not called
    assert result == ""
    assert len(b.calls) == 0


def test_provider_chain_returns_empty_string_when_all_transient_fail():
    a = _make_provider("a", transient=True)
    b = _make_provider("b", transient=True)
    chain = ProviderChain([a, b])
    result = chain.complete("hi")
    assert result == ""  # safe default from NullProvider fallback


def test_provider_chain_with_empty_list_returns_safe_defaults():
    chain = ProviderChain([])
    assert chain.complete("hi") == ""
    assert chain.analyze_resume("jd", "resume", {}) == {
        "strong_skills": [],
        "missing_skills": [],
        "suggested_changes": [],
        "tailored_resume": "resume",
    }


def test_provider_chain_analyze_resume_preserves_master_resume_on_failure():
    a = _make_provider("a", transient=True)
    chain = ProviderChain([a])
    result = chain.analyze_resume("jd", "my original resume", {})
    assert result["tailored_resume"] == "my original resume"


def test_provider_chain_name_shows_provider_order():
    a = _make_provider("nvidia_nim")
    b = _make_provider("gemini:primary")
    chain = ProviderChain([a, b])
    assert "nvidia_nim" in chain.name
    assert "gemini:primary" in chain.name


# ─── ProviderChain failover scenarios (job matching chain) ────────────────────

def test_job_matching_chain_gemini_primary_succeeds():
    gemini_primary = _make_provider("gemini:primary", reply="yes")
    gemini_fallback = _make_provider("gemini:fallback", reply="yes")
    nim = _make_provider("nvidia_nim", reply="yes")
    groq = _make_provider("groq", reply="yes")
    chain = ProviderChain([gemini_primary, gemini_fallback, nim, groq])
    assert chain.complete("hi") == "yes"
    assert len(gemini_primary.calls) == 1
    assert len(gemini_fallback.calls) == 0


def test_job_matching_chain_gemini_primary_429_fallback_succeeds():
    gemini_primary = _make_provider("gemini:primary", transient=True)
    gemini_fallback = _make_provider("gemini:fallback", reply="fallback-reply")
    nim = _make_provider("nvidia_nim", reply="nim-reply")
    chain = ProviderChain([gemini_primary, gemini_fallback, nim])
    assert chain.complete("hi") == "fallback-reply"
    assert len(gemini_fallback.calls) == 1
    assert len(nim.calls) == 0


def test_job_matching_chain_both_gemini_fail_nim_succeeds():
    gemini_primary = _make_provider("gemini:primary", transient=True)
    gemini_fallback = _make_provider("gemini:fallback", transient=True)
    nim = _make_provider("nvidia_nim", reply="nim-reply")
    groq = _make_provider("groq", reply="groq-reply")
    chain = ProviderChain([gemini_primary, gemini_fallback, nim, groq])
    assert chain.complete("hi") == "nim-reply"
    assert len(groq.calls) == 0


def test_job_matching_chain_gemini_and_nim_fail_groq_succeeds():
    gemini_primary = _make_provider("gemini:primary", transient=True)
    gemini_fallback = _make_provider("gemini:fallback", transient=True)
    nim = _make_provider("nvidia_nim", transient=True)
    groq = _make_provider("groq", reply="groq-reply")
    chain = ProviderChain([gemini_primary, gemini_fallback, nim, groq])
    assert chain.complete("hi") == "groq-reply"


def test_job_matching_chain_all_fail_returns_safe_default():
    """When all providers fail transiently, NullProvider safe behaviour applies."""
    a = _make_provider("a", transient=True)
    b = _make_provider("b", transient=True)
    chain = ProviderChain([a, b])
    # analyze_resume returns safe dict (master_resume preserved)
    result = chain.analyze_resume("jd", "master", {})
    assert result["tailored_resume"] == "master"
    # complete returns empty string
    assert chain.complete("hi") == ""


# ─── ProviderChain failover scenarios (reasoning chain) ───────────────────────

def test_reasoning_chain_nim_succeeds_immediately():
    nim = _make_provider("nvidia_nim", reply="nim-reply")
    gemini = _make_provider("gemini:primary", reply="gemini-reply")
    chain = ProviderChain([nim, gemini])
    assert chain.complete("plan this") == "nim-reply"
    assert len(gemini.calls) == 0


def test_reasoning_chain_nim_unavailable_gemini_primary_succeeds():
    nim = _make_provider("nvidia_nim", transient=True)
    gemini_primary = _make_provider("gemini:primary", reply="gemini-reply")
    gemini_fallback = _make_provider("gemini:fallback", reply="fallback-reply")
    chain = ProviderChain([nim, gemini_primary, gemini_fallback])
    assert chain.complete("plan") == "gemini-reply"
    assert len(gemini_fallback.calls) == 0


def test_reasoning_chain_gemini_primary_fails_fallback_succeeds():
    nim = _make_provider("nvidia_nim", transient=True)
    gemini_primary = _make_provider("gemini:primary", transient=True)
    gemini_fallback = _make_provider("gemini:fallback", reply="fallback-reply")
    groq = _make_provider("groq", reply="groq-reply")
    chain = ProviderChain([nim, gemini_primary, gemini_fallback, groq])
    assert chain.complete("plan") == "fallback-reply"
    assert len(groq.calls) == 0


def test_reasoning_chain_all_earlier_fail_groq_succeeds():
    nim = _make_provider("nvidia_nim", transient=True)
    gemini_primary = _make_provider("gemini:primary", transient=True)
    gemini_fallback = _make_provider("gemini:fallback", transient=True)
    groq = _make_provider("groq", reply="groq-reply")
    chain = ProviderChain([nim, gemini_primary, gemini_fallback, groq])
    assert chain.complete("plan") == "groq-reply"


def test_reasoning_chain_complete_failure_safe_behavior():
    nim = _make_provider("nvidia_nim", transient=True)
    gemini = _make_provider("gemini:primary", transient=True)
    groq = _make_provider("groq", transient=True)
    chain = ProviderChain([nim, gemini, groq])
    # Must never raise, must return safe defaults
    assert chain.complete("plan") == ""
    assert chain.generate_cover_letter("jd", "resume", {}) == ""
    assert chain.answer_generative_question("Q", {}, "jd") == ""


# ─── Reliability: error classification ───────────────────────────────────────

@pytest.mark.parametrize("code", [429, 502, 503, 504])
def test_transient_status_codes_trigger_chain_failover(code):
    """429/5xx from any OpenAI-compatible provider triggers chain failover."""
    primary = NvidiaNIMProvider(api_key="fake", client=_status_client(code))
    fallback = _make_provider("fallback", reply="ok")
    chain = ProviderChain([primary, fallback])
    assert chain.complete("hi") == "ok"


def test_401_does_not_trigger_failover():
    """Invalid API key is a permanent error; next provider must NOT be tried."""
    primary = NvidiaNIMProvider(api_key="bad-key", client=_status_client(401))
    fallback = _make_provider("fallback", reply="ok")
    chain = ProviderChain([primary, fallback])
    result = chain.complete("hi")
    # Fallback not used -- permanent error stops chain
    assert len(fallback.calls) == 0
    assert result == ""


def test_400_does_not_trigger_failover():
    """Malformed request (code bug) stops chain, does not retry."""
    primary = NvidiaNIMProvider(api_key="fake", client=_status_client(400))
    fallback = _make_provider("fallback", reply="ok")
    chain = ProviderChain([primary, fallback])
    result = chain.complete("hi")
    assert len(fallback.calls) == 0
    assert result == ""


# ─── A. Provider configuration tests (chain factory) ─────────────────────────

def _make_settings(**kwargs):
    from app.config import Settings
    defaults = dict(
        gemini_api_key="",
        gemini_primary_model="gemini-3.5-flash-lite",
        gemini_fallback_model="gemini-3.1-flash-lite",
        nvidia_nim_api_key="",
        nvidia_nim_model="meta/muse-glimmer-30b",
        groq_api_key="",
        groq_models="",
    )
    defaults.update(kwargs)
    return Settings(_env_file=None, **defaults)


def test_no_providers_configured_reasoning_chain_is_null():
    s = _make_settings()
    chain = build_reasoning_chain(s)
    assert chain.complete("hi") == ""


def test_no_providers_configured_job_matching_chain_is_null():
    s = _make_settings()
    chain = build_job_matching_chain(s)
    assert chain.complete("hi") == ""


def test_only_gemini_configured_reasoning_chain():
    s = _make_settings(gemini_api_key="gk")
    chain = build_reasoning_chain(s)
    assert "gemini" in chain.name
    assert "nvidia" not in chain.name
    assert "groq" not in chain.name
    # Two Gemini instances (primary + fallback) -- chain has one '->' separator between them
    # Name format: chain(gemini:primary-model->gemini:fallback-model)
    assert chain.name.count("->") == 1


def test_only_gemini_configured_single_instance_when_models_same():
    s = _make_settings(gemini_api_key="gk",
                       gemini_primary_model="same-model",
                       gemini_fallback_model="same-model")
    chain = build_reasoning_chain(s)
    assert chain.name.count("gemini") == 1


def test_only_nvidia_configured_reasoning_chain():
    s = _make_settings(nvidia_nim_api_key="nk")
    chain = build_reasoning_chain(s)
    assert "nvidia_nim" in chain.name
    assert "gemini" not in chain.name


def test_only_groq_configured_reasoning_chain():
    s = _make_settings(groq_api_key="gq", groq_models="openai/gpt-oss-120b")
    chain = build_reasoning_chain(s)
    assert "groq" in chain.name
    assert "nvidia" not in chain.name
    assert "gemini" not in chain.name


def test_groq_without_model_is_excluded_from_chain():
    """GROQ_MODELS must be set; key alone is not enough to include Groq."""
    s = _make_settings(groq_api_key="gq", groq_models="")
    chain = build_reasoning_chain(s)
    assert "groq" not in chain.name


def test_all_providers_reasoning_chain_order():
    """Reasoning chain: NIM first, then Gemini, then Groq."""
    s = _make_settings(
        nvidia_nim_api_key="nk",
        gemini_api_key="gk",
        groq_api_key="gq",
        groq_models="openai/gpt-oss-120b",
    )
    chain = build_reasoning_chain(s)
    names = chain.name
    nim_pos = names.index("nvidia_nim")
    gemini_pos = names.index("gemini")
    groq_pos = names.index("groq")
    assert nim_pos < gemini_pos < groq_pos


def test_all_providers_job_matching_chain_order():
    """Job matching chain: Gemini first, then NIM, then Groq."""
    s = _make_settings(
        nvidia_nim_api_key="nk",
        gemini_api_key="gk",
        groq_api_key="gq",
        groq_models="openai/gpt-oss-120b",
    )
    chain = build_job_matching_chain(s)
    names = chain.name
    nim_pos = names.index("nvidia_nim")
    gemini_pos = names.index("gemini")
    groq_pos = names.index("groq")
    assert gemini_pos < nim_pos < groq_pos


# ─── Factory cache ─────────────────────────────────────────────────────────────

def test_provider_factory_defaults_to_null_when_unconfigured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GROQ_MODELS", "")
    get_settings.cache_clear()
    reset_provider_cache()

    provider = get_llm_provider()
    assert provider.complete("hi") == ""  # null behaviour

    get_settings.cache_clear()
    reset_provider_cache()


def test_job_matching_provider_is_independent_from_reasoning_provider(monkeypatch):
    """The two cached chains are independent; resetting one does not affect the other."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GROQ_MODELS", "")
    get_settings.cache_clear()
    reset_provider_cache()

    r = get_llm_provider()
    j = get_job_matching_provider()
    assert r is not j  # independent objects, but both valid chains

    get_settings.cache_clear()
    reset_provider_cache()
