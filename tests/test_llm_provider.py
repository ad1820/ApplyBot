import httpx
import pytest

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMError
from app.llm.null_provider import NullProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.provider import get_llm_provider, reset_provider_cache
from app.config import get_settings


def test_null_provider_never_raises_and_returns_safe_defaults():
    provider = NullProvider()
    assert provider.complete("hi") == ""
    resume_analysis = provider.analyze_resume("jd", "master resume text", {})
    assert resume_analysis["tailored_resume"] == "master resume text"
    assert provider.generate_cover_letter("jd", "resume", {}) == ""


def test_openai_provider_raises_llm_error_on_failure():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAIProvider(api_key="fake", client=client)

    with pytest.raises(LLMError):
        provider.complete("hello")


def test_openai_provider_parses_successful_completion():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi there"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAIProvider(api_key="fake", client=client)

    assert provider.complete("hello") == "hi there"


def _openai_chat_client(content: str) -> httpx.Client:
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _anthropic_chat_client(content: str, with_thinking_block: bool = False) -> httpx.Client:
    blocks = []
    if with_thinking_block:
        blocks.append({"type": "thinking", "thinking": "", "signature": "abc"})
    blocks.append({"type": "text", "text": content})

    def handler(request):
        return httpx.Response(200, json={"content": blocks})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_anthropic_provider_extracts_text_after_thinking_block():
    # Regression test: models with extended thinking enabled return a
    # "thinking" block before the actual "text" block - complete() must not
    # assume content[0] is always the answer.
    provider = AnthropicProvider(api_key="fake", client=_anthropic_chat_client("Hi there!", with_thinking_block=True))
    assert provider.complete("hello") == "Hi there!"


def test_anthropic_provider_raises_llm_error_when_no_text_block_present():
    def handler(request):
        return httpx.Response(200, json={"content": [{"type": "thinking", "thinking": ""}]})

    provider = AnthropicProvider(api_key="fake", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMError):
        provider.complete("hello")


def test_openai_analyze_resume_parses_valid_json():
    payload = '{"strong_skills": ["python"], "missing_skills": ["aws"], "suggested_changes": ["Emphasize python"], "tailored_resume": "My resume"}'
    provider = OpenAIProvider(api_key="fake", client=_openai_chat_client(payload))

    result = provider.analyze_resume("Job needs Python", "My resume", {"skills": ["python"]})

    assert result["strong_skills"] == ["python"]
    assert result["tailored_resume"] == "My resume"


def test_openai_analyze_resume_strips_markdown_code_fence():
    payload = '```json\n{"strong_skills": [], "missing_skills": [], "suggested_changes": [], "tailored_resume": "R"}\n```'
    provider = OpenAIProvider(api_key="fake", client=_openai_chat_client(payload))

    result = provider.analyze_resume("jd", "R", {})
    assert result["tailored_resume"] == "R"


def test_openai_analyze_resume_returns_empty_dict_on_malformed_json():
    provider = OpenAIProvider(api_key="fake", client=_openai_chat_client("not json at all"))
    result = provider.analyze_resume("jd", "resume", {})
    assert result == {}


def test_openai_analyze_resume_returns_empty_dict_on_llm_failure():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    provider = OpenAIProvider(api_key="fake", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.analyze_resume("jd", "resume", {})
    assert result == {}


def test_openai_generate_cover_letter_returns_text():
    provider = OpenAIProvider(api_key="fake", client=_openai_chat_client("Dear hiring manager, ..."))
    result = provider.generate_cover_letter("jd", "resume", {"name": "Alice"})
    assert result == "Dear hiring manager, ..."


def test_openai_answer_generative_question_returns_text():
    provider = OpenAIProvider(api_key="fake", client=_openai_chat_client("Because I love building things."))
    result = provider.answer_generative_question("Why do you want to work here?", {"name": "Alice"}, "jd")
    assert result == "Because I love building things."


def test_anthropic_analyze_resume_parses_valid_json():
    payload = '{"strong_skills": ["python"], "missing_skills": [], "suggested_changes": [], "tailored_resume": "R"}'
    provider = AnthropicProvider(api_key="fake", client=_anthropic_chat_client(payload))

    result = provider.analyze_resume("jd", "R", {"skills": ["python"]})
    assert result["strong_skills"] == ["python"]


def test_anthropic_analyze_resume_returns_empty_dict_on_malformed_json():
    provider = AnthropicProvider(api_key="fake", client=_anthropic_chat_client("nonsense"))
    result = provider.analyze_resume("jd", "resume", {})
    assert result == {}


def test_anthropic_generate_cover_letter_returns_text():
    provider = AnthropicProvider(api_key="fake", client=_anthropic_chat_client("Dear team, ..."))
    result = provider.generate_cover_letter("jd", "resume", {"name": "Alice"})
    assert result == "Dear team, ..."


def test_anthropic_answer_generative_question_returns_text():
    provider = AnthropicProvider(api_key="fake", client=_anthropic_chat_client("Because of the mission."))
    result = provider.answer_generative_question("Why us?", {"name": "Alice"}, "jd")
    assert result == "Because of the mission."


def test_provider_factory_defaults_to_null_when_unconfigured(monkeypatch):
    # Explicitly override (not just delete) LLM_API_KEY, since pydantic-settings
    # falls back to the real .env file's value when the env var is merely
    # deleted from os.environ - the local .env may have a real key configured.
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    reset_provider_cache()

    provider = get_llm_provider()
    assert provider.name == "null"

    get_settings.cache_clear()
    reset_provider_cache()
