from app.db.repositories.analytics import AnalyticsEventRepository
from app.db.repositories.applications import ApplicationRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.profiles import CandidateProfileRepository
from app.db.repositories.resumes import MasterResumeRepository, TailoredResumeRepository
from app.llm.null_provider import NullProvider
from app.telegram.handlers import (
    BotContext,
    handle_approve_resume,
    handle_resume_analysis,
    handle_set_resume,
)


def make_ctx(fake_client) -> BotContext:
    return BotContext(
        jobs=JobRepository(fake_client),
        applications=ApplicationRepository(fake_client),
        analytics=AnalyticsEventRepository(fake_client),
        profiles=CandidateProfileRepository(fake_client),
        master_resumes=MasterResumeRepository(fake_client),
        tailored_resumes=TailoredResumeRepository(fake_client),
        llm_provider=NullProvider(),
    )


def create_job(fake_client, **overrides):
    payload = {
        "external_id": "1",
        "source": "greenhouse",
        "company": "Acme",
        "title": "Backend Engineer",
        "location": "Bangalore",
        "canonical_key": "abc",
        "status": "NOTIFIED",
        "skills": ["Python", "FastAPI", "Kubernetes"],
        "description": "We use Python and FastAPI heavily.",
    }
    payload.update(overrides)
    return JobRepository(fake_client).create(payload)


def test_set_resume_creates_new_version(fake_client):
    ctx = make_ctx(fake_client)
    reply = handle_set_resume(ctx, "My resume content: Python, FastAPI, Docker experience.")
    assert "version 1" in reply

    reply2 = handle_set_resume(ctx, "Updated resume content.")
    assert "version 2" in reply2

    # Old version must not be overwritten.
    assert ctx.master_resumes.get_version(1)["content"].startswith("My resume content")


def test_set_resume_requires_text(fake_client):
    ctx = make_ctx(fake_client)
    reply = handle_set_resume(ctx, "")
    assert "send your resume text" in reply.lower()


def test_resume_analysis_requires_master_resume_first(fake_client):
    ctx = make_ctx(fake_client)
    job = create_job(fake_client)
    reply = handle_resume_analysis(ctx, job["id"])
    assert "no master resume" in reply.lower()


def test_resume_analysis_never_fabricates_and_flags_missing_skills(fake_client):
    ctx = make_ctx(fake_client)
    ctx.profiles.upsert({"name": "Alice", "email": "a@example.com", "skills": ["Python", "FastAPI"]})
    handle_set_resume(ctx, "Alice's resume: Python, FastAPI developer.")
    job = create_job(fake_client)

    reply = handle_resume_analysis(ctx, job["id"])

    assert "Resume Analysis" in reply
    assert "kubernetes" in reply.lower()  # flagged as missing, never claimed as owned
    assert "Do not claim" in reply or "do not claim" in reply.lower()

    drafts = ctx.tailored_resumes.list_for_job(job["id"])
    assert len(drafts) == 1
    assert drafts[0]["approved"] is False


def test_resume_analysis_unknown_job(fake_client):
    ctx = make_ctx(fake_client)
    reply = handle_resume_analysis(ctx, "does-not-exist")
    assert "not found" in reply


def test_approve_resume_requires_prior_analysis(fake_client):
    ctx = make_ctx(fake_client)
    job = create_job(fake_client)
    reply = handle_approve_resume(ctx, job["id"])
    assert "no tailored resume draft" in reply.lower()


def test_approve_resume_marks_latest_draft_approved(fake_client):
    ctx = make_ctx(fake_client)
    ctx.profiles.upsert({"name": "Alice", "email": "a@example.com", "skills": ["Python"]})
    handle_set_resume(ctx, "Alice's resume")
    job = create_job(fake_client)
    handle_resume_analysis(ctx, job["id"])

    reply = handle_approve_resume(ctx, job["id"])
    assert "approved" in reply.lower()

    drafts = ctx.tailored_resumes.list_for_job(job["id"])
    assert drafts[0]["approved"] is True
