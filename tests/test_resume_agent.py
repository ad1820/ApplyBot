from app.agents.resume_agent import analyze_resume
from app.jobs.models import Job
from app.llm.base import LLMError, LLMProvider
from app.llm.null_provider import NullProvider


def make_job():
    return Job(source="test", company="Acme", title="Backend Engineer", skills=["Python", "FastAPI", "Kubernetes"])


def test_resume_agent_never_fabricates_missing_skills():
    job = make_job()
    profile = {"skills": ["Python", "FastAPI"]}
    result = analyze_resume(job, "Master resume content", profile, NullProvider())

    assert "kubernetes" in result.missing_skills
    assert any("kubernetes" in change.lower() and "do not claim" in change.lower() for change in result.suggested_changes)
    assert "python" in result.strong_skills


class FailingProvider(LLMProvider):
    name = "failing"

    def complete(self, prompt, *, system=None, max_tokens=512):
        raise LLMError("down")

    def analyze_resume(self, job_description, master_resume, candidate_profile):
        raise LLMError("llm down")


def test_resume_agent_degrades_gracefully_on_llm_failure():
    job = make_job()
    profile = {"skills": ["Python"]}
    result = analyze_resume(job, "Master resume", profile, FailingProvider())
    # Deterministic analysis still returned despite LLM failure.
    assert result.match_score >= 0
    assert result.tailored_resume == "Master resume"
