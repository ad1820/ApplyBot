"""Tests for app.telegram.handlers.dispatch_command - the shared command
router used by both scripts/telegram_polling.py and the FastAPI webhook
endpoint, so they behave identically regardless of transport."""
from __future__ import annotations

from app.db.repositories.analytics import AnalyticsEventRepository
from app.db.repositories.applications import ApplicationRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.profiles import CandidateProfileRepository
from app.db.repositories.resumes import MasterResumeRepository, TailoredResumeRepository
from app.llm.null_provider import NullProvider
from app.telegram.handlers import BotContext, dispatch_command


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
    }
    payload.update(overrides)
    return JobRepository(fake_client).create(payload)


def test_dispatch_start(fake_client):
    ctx = make_ctx(fake_client)
    reply = dispatch_command(ctx, "/start")
    assert "Welcome" in reply


def test_dispatch_help(fake_client):
    ctx = make_ctx(fake_client)
    reply = dispatch_command(ctx, "/help")
    assert "Available commands" in reply


def test_dispatch_jobs_with_no_jobs(fake_client):
    ctx = make_ctx(fake_client)
    reply = dispatch_command(ctx, "/jobs")
    assert "No jobs found" in reply


def test_dispatch_job_detail(fake_client):
    job = create_job(fake_client)
    ctx = make_ctx(fake_client)
    reply = dispatch_command(ctx, f"/job {job['id']}")
    assert "Backend Engineer" in reply


def test_dispatch_done(fake_client):
    job = create_job(fake_client)
    ctx = make_ctx(fake_client)
    reply = dispatch_command(ctx, f"/done {job['id']}")
    assert "Application recorded" in reply
    assert ctx.jobs.get(job["id"])["status"] == "APPLIED"


def test_dispatch_skip(fake_client):
    job = create_job(fake_client)
    ctx = make_ctx(fake_client)
    reply = dispatch_command(ctx, f"/skip {job['id']}")
    assert "skipped" in reply.lower()


def test_dispatch_status_transitions(fake_client):
    job = create_job(fake_client, status="APPLIED")
    ctx = make_ctx(fake_client)
    ctx.applications.record_applied(job["id"])
    reply = dispatch_command(ctx, f"/interview {job['id']}")
    assert "INTERVIEW" in reply


def test_dispatch_setresume_and_resume_flow(fake_client):
    ctx = make_ctx(fake_client)
    job = create_job(fake_client)

    reply1 = dispatch_command(ctx, "/setresume My resume text here")
    assert "version 1" in reply1

    reply2 = dispatch_command(ctx, f"/resume {job['id']}")
    assert "Resume Analysis" in reply2

    reply3 = dispatch_command(ctx, f"/approveresume {job['id']}")
    assert "approved" in reply3.lower()


def test_dispatch_unknown_command(fake_client):
    ctx = make_ctx(fake_client)
    reply = dispatch_command(ctx, "/notarealcommand")
    assert "Unknown command" in reply


def test_dispatch_empty_text_does_not_crash(fake_client):
    ctx = make_ctx(fake_client)
    reply = dispatch_command(ctx, "")
    assert "Unknown command" in reply


def test_dispatch_plain_text_without_slash(fake_client):
    ctx = make_ctx(fake_client)
    reply = dispatch_command(ctx, "hi there")
    assert "Unknown command" in reply
