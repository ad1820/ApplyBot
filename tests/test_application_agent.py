from app.agents.adapters.ashby import AshbyAdapter
from app.agents.adapters.generic import GenericAdapter, detect_adapter
from app.agents.adapters.greenhouse import GreenhouseAdapter
from app.agents.adapters.lever import LeverAdapter
from app.agents.application_agent import DEFAULT_ADAPTERS, prepare_answers
from app.llm.null_provider import NullProvider


def test_detect_adapter_greenhouse():
    adapter = detect_adapter("https://boards.greenhouse.io/acme/jobs/123", DEFAULT_ADAPTERS)
    assert isinstance(adapter, GreenhouseAdapter)


def test_detect_adapter_lever():
    adapter = detect_adapter("https://jobs.lever.co/acme/123", DEFAULT_ADAPTERS)
    assert isinstance(adapter, LeverAdapter)


def test_detect_adapter_ashby():
    adapter = detect_adapter("https://jobs.ashbyhq.com/acme/123", DEFAULT_ADAPTERS)
    assert isinstance(adapter, AshbyAdapter)


def test_detect_adapter_falls_back_to_generic():
    adapter = detect_adapter("https://careers.somecompany.com/apply/123", DEFAULT_ADAPTERS)
    assert isinstance(adapter, GenericAdapter)


def test_greenhouse_extract_questions():
    adapter = GreenhouseAdapter()
    page_data = {"questions": [{"label": "What is your email?", "required": True, "type": "text"}]}
    questions = adapter.extract_questions(page_data)
    assert len(questions) == 1
    assert questions[0].text == "What is your email?"
    assert questions[0].required is True


def test_prepare_answers_classifies_and_answers_questions():
    page_data = {
        "questions": [
            {"label": "What is your email?", "required": True},
            {"label": "Will you require sponsorship?", "required": True},
        ]
    }
    profile = {"email": "alice@example.com"}

    def lookup_approved(question_text):
        return None

    results = prepare_answers(
        "https://boards.greenhouse.io/acme/jobs/1",
        page_data,
        profile,
        "job description",
        NullProvider(),
        lookup_approved,
    )

    assert len(results) == 2
    email_result = next(r for r in results if "email" in r.question.text.lower())
    assert email_result.result.answer == "alice@example.com"

    sponsorship_result = next(r for r in results if "sponsorship" in r.question.text.lower())
    assert sponsorship_result.result.answer is None
    assert sponsorship_result.result.source == "NEEDS_USER_INPUT"


def test_prepare_answers_reuses_previously_approved_sensitive_answer():
    page_data = {"questions": [{"label": "Are you willing to relocate?", "required": True}]}

    def lookup_approved(question_text):
        return "Yes"

    results = prepare_answers(
        "https://careers.somecompany.com/apply/1",
        page_data,
        {},
        "job description",
        NullProvider(),
        lookup_approved,
    )
    assert results[0].result.answer == "Yes"
    assert results[0].result.source == "USER_APPROVED"
