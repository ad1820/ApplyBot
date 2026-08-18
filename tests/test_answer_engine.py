from app.agents.answer_engine import answer_question, classify_question
from app.llm.base import LLMProvider
from app.llm.null_provider import NullProvider


def test_classify_profile_fact_question():
    assert classify_question("What is your email address?") == "PROFILE_FACT"
    assert classify_question("Please provide your phone number") == "PROFILE_FACT"


def test_classify_derived_fact_question():
    assert classify_question("How many years of experience do you have with Python?") == "DERIVED_FACT"


def test_classify_generative_question():
    assert classify_question("Why do you want to work here?") == "GENERATIVE"
    assert classify_question("Describe your most challenging project") == "GENERATIVE"


def test_classify_sensitive_question():
    assert classify_question("Will you require visa sponsorship?") == "SENSITIVE"
    assert classify_question("What is your expected salary?") == "SENSITIVE"


def test_classify_unknown_question_defaults_to_sensitive_never_guessed():
    assert classify_question("Completely ambiguous nonsense question") == "SENSITIVE"


def test_answer_profile_fact_question():
    result = answer_question("What is your email?", {"email": "alice@example.com"}, "", NullProvider())
    assert result.answer == "alice@example.com"
    assert result.source == "PROFILE"


def test_answer_sensitive_question_never_guessed_without_approval():
    result = answer_question("Will you require sponsorship?", {}, "", NullProvider())
    assert result.answer is None
    assert result.source == "NEEDS_USER_INPUT"


def test_answer_sensitive_question_reuses_approved_answer():
    result = answer_question(
        "Will you require sponsorship?", {}, "", NullProvider(), previously_approved_answer="No"
    )
    assert result.answer == "No"
    assert result.source == "USER_APPROVED"


def test_answer_generative_question_uses_llm_and_falls_back_gracefully():
    class StubProvider(LLMProvider):
        name = "stub"

        def complete(self, prompt, *, system=None, max_tokens=512):
            return ""

        def answer_generative_question(self, question, candidate_profile, job_description):
            return "Because I love building scalable systems."

    result = answer_question("Why do you want to work here?", {}, "jd", StubProvider())
    assert result.answer == "Because I love building scalable systems."
    assert result.source == "GENERATED"


def test_answer_derived_fact_uses_profile_skills():
    profile = {"skills": ["Python"], "years_of_experience": 5}
    result = answer_question("Experience with Python?", profile, "", NullProvider())
    assert result.source == "DERIVED"
    assert "5" in result.answer
