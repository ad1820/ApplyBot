from app.db.repositories.analytics import AnalyticsEventRepository
from app.db.repositories.applications import ApplicationRepository
from app.db.repositories.jobs import JobRepository
from app.telegram.handlers import (
    BotContext,
    handle_done,
    handle_job,
    handle_skip,
    handle_status,
    handle_status_transition,
)


def make_ctx(fake_client) -> BotContext:
    return BotContext(
        jobs=JobRepository(fake_client),
        applications=ApplicationRepository(fake_client),
        analytics=AnalyticsEventRepository(fake_client),
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


def test_handle_done_marks_applied_and_confirms(fake_client):
    job = create_job(fake_client)
    ctx = make_ctx(fake_client)

    reply = handle_done(ctx, job["id"])

    assert "Application recorded" in reply
    assert ctx.jobs.get(job["id"])["status"] == "APPLIED"
    assert ctx.applications.get_by_job(job["id"])["status"] == "APPLIED"


def test_handle_done_idempotent_when_called_twice(fake_client):
    job = create_job(fake_client)
    ctx = make_ctx(fake_client)

    handle_done(ctx, job["id"])
    handle_done(ctx, job["id"])

    applications = ctx.applications.list_all()
    assert len(applications) == 1


def test_handle_done_unknown_job(fake_client):
    ctx = make_ctx(fake_client)
    reply = handle_done(ctx, "does-not-exist")
    assert "not found" in reply


def test_handle_skip_marks_job_skipped(fake_client):
    job = create_job(fake_client)
    ctx = make_ctx(fake_client)

    reply = handle_skip(ctx, job["id"])

    assert "skipped" in reply.lower()
    assert ctx.jobs.get(job["id"])["status"] == "SKIPPED"


def test_handle_skip_invalid_from_terminal_status(fake_client):
    job = create_job(fake_client, status="REJECTED")
    ctx = make_ctx(fake_client)

    reply = handle_skip(ctx, job["id"])
    assert "Cannot skip" in reply
    assert ctx.jobs.get(job["id"])["status"] == "REJECTED"


def test_handle_status_returns_current_status(fake_client):
    job = create_job(fake_client)
    ctx = make_ctx(fake_client)
    reply = handle_status(ctx, job["id"])
    assert "NOTIFIED" in reply


def test_handle_status_transition_interview_then_offer(fake_client):
    job = create_job(fake_client, status="APPLIED")
    ctx = make_ctx(fake_client)
    ctx.applications.record_applied(job["id"])

    reply = handle_status_transition(ctx, "interview", job["id"])
    assert "INTERVIEW" in reply
    assert ctx.jobs.get(job["id"])["status"] == "INTERVIEW"

    reply2 = handle_status_transition(ctx, "offer", job["id"])
    assert "OFFER" in reply2


def test_handle_status_transition_invalid_jump(fake_client):
    job = create_job(fake_client, status="DISCOVERED")
    ctx = make_ctx(fake_client)
    reply = handle_status_transition(ctx, "offer", job["id"])
    assert "Cannot move" in reply


def test_handle_job_detail(fake_client):
    job = create_job(fake_client)
    ctx = make_ctx(fake_client)
    reply = handle_job(ctx, job["id"])
    assert "Backend Engineer" in reply
    assert "Acme" in reply
