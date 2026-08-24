"""Tests for GeminiProvider -- all offline with mocked httpx transports."""
import json

import httpx
import pytest

from app.llm.base import LLMError, LLMTransientError
from app.llm.gemini_provider import GeminiProvider


_MODEL = "gemini-3.5-flash-lite"


def _gemini_ok_client(text: str) -> httpx.Client:
    def handler(request):
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
        )
    return httpx.Client(transport=httpx.MockTransport(handler))


def _gemini_status_client(status_code: int) -> httpx.Client:
    def handler(request):
        return httpx.Response(status_code, json={"error": {"message": "error"}})
    return httpx.Client(transport=httpx.MockTransport(handler))


# ─── Basic complete() ─────────────────────────────────────────────────────────

def test_gemini_complete_returns_text():
    provider = GeminiProvider(api_key="fake", model=_MODEL, client=_gemini_ok_client("hello from gemini"))
    assert provider.complete("hi") == "hello from gemini"


def test_gemini_complete_sends_to_correct_endpoint():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    provider = GeminiProvider(
        api_key="my-key", model=_MODEL, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    provider.complete("hi")
    assert "generativelanguage.googleapis.com" in captured["url"]
    assert _MODEL in captured["url"]


def test_gemini_complete_does_not_include_api_key_in_url_path():
    """API key is a query param, must never appear in path or as auth header."""
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    provider = GeminiProvider(
        api_key="super-secret-key", model=_MODEL,
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    provider.complete("hi")
    # Key appears as query param (not in the error message / path)
    assert "super-secret-key" not in captured["url"].split("?")[0]
    # No Authorization header
    assert "authorization" not in captured["headers"]


def test_gemini_complete_includes_system_instruction():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    provider = GeminiProvider(
        api_key="fake", model=_MODEL, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    provider.complete("hi", system="Be concise.")
    assert "systemInstruction" in captured["body"]
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "Be concise."


def test_gemini_complete_no_system_instruction_when_not_provided():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    provider = GeminiProvider(
        api_key="fake", model=_MODEL, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    provider.complete("hi")
    assert "systemInstruction" not in captured["body"]


# ─── Error handling ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_gemini_transient_status_raises_transient_error(code):
    provider = GeminiProvider(api_key="fake", model=_MODEL, client=_gemini_status_client(code))
    with pytest.raises(LLMTransientError):
        provider.complete("hi")


@pytest.mark.parametrize("code", [400, 401, 403])
def test_gemini_permanent_status_raises_llm_error_not_transient(code):
    provider = GeminiProvider(api_key="bad", model=_MODEL, client=_gemini_status_client(code))
    with pytest.raises(LLMError) as exc_info:
        provider.complete("hi")
    assert type(exc_info.value) is LLMError  # not LLMTransientError


def test_gemini_api_key_not_in_error_message():
    provider = GeminiProvider(api_key="my-secret-gemini-key", model=_MODEL, client=_gemini_status_client(401))
    try:
        provider.complete("hi")
    except LLMError as exc:
        assert "my-secret-gemini-key" not in str(exc)


# ─── analyze_resume ───────────────────────────────────────────────────────────

def test_gemini_analyze_resume_parses_valid_json():
    payload = json.dumps({
        "strong_skills": ["python"],
        "missing_skills": ["aws"],
        "suggested_changes": ["Emphasize python"],
        "tailored_resume": "My resume",
    })
    provider = GeminiProvider(api_key="fake", model=_MODEL, client=_gemini_ok_client(payload))
    result = provider.analyze_resume("jd", "My resume", {"skills": ["python"]})
    assert result["strong_skills"] == ["python"]
    assert result["tailored_resume"] == "My resume"


def test_gemini_analyze_resume_returns_empty_dict_on_malformed_json():
    provider = GeminiProvider(api_key="fake", model=_MODEL, client=_gemini_ok_client("not json"))
    result = provider.analyze_resume("jd", "resume", {})
    assert result == {}


def test_gemini_analyze_resume_returns_empty_dict_on_llm_failure():
    provider = GeminiProvider(api_key="fake", model=_MODEL, client=_gemini_status_client(500))
    result = provider.analyze_resume("jd", "resume", {})
    assert result == {}


def test_gemini_analyze_resume_strips_code_fence():
    payload = '```json\n{"strong_skills": [], "missing_skills": [], "suggested_changes": [], "tailored_resume": "R"}\n```'
    provider = GeminiProvider(api_key="fake", model=_MODEL, client=_gemini_ok_client(payload))
    result = provider.analyze_resume("jd", "R", {})
    assert result["tailored_resume"] == "R"


# ─── generate_cover_letter / answer_generative_question ───────────────────────

def test_gemini_generate_cover_letter_returns_text():
    provider = GeminiProvider(api_key="fake", model=_MODEL, client=_gemini_ok_client("Dear team, ..."))
    result = provider.generate_cover_letter("jd", "resume", {"name": "Alice"})
    assert result == "Dear team, ..."


def test_gemini_answer_generative_question_returns_text():
    provider = GeminiProvider(api_key="fake", model=_MODEL, client=_gemini_ok_client("Because of the mission."))
    result = provider.answer_generative_question("Why us?", {"name": "Alice"}, "jd")
    assert result == "Because of the mission."


# ─── name reflects model ─────────────────────────────────────────────────────

def test_gemini_provider_name_includes_model():
    provider = GeminiProvider(api_key="fake", model="gemini-3.5-flash-lite")
    assert "gemini" in provider.name
    assert "gemini-3.5-flash-lite" in provider.name
