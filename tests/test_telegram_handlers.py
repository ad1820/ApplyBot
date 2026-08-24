from app.db.repositories.analytics import AnalyticsEventRepository
from app.db.repositories.applications import ApplicationRepository
from app.db.repositories.jobs import JobRepository
from app.telegram.handlers import (
    BotContext,
    dispatch_callback_query,
    dispatch_command_with_markup,
    handle_companies,
    handle_company_jobs_callback,
    handle_done,
    handle_job,
    handle_skip,
    handle_status,
    handle_status_transition,
)
from app.telegram.messages import company_callback_hash


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


def test_handle_companies_groups_notified_jobs_by_company(fake_client):
    create_job(fake_client, company="Acme", title="Backend Engineer", canonical_key="k1")
    create_job(fake_client, company="Acme", title="Platform Engineer", canonical_key="k2")
    create_job(fake_client, company="OpenAI", title="Research Engineer", canonical_key="k3")
    # A non-NOTIFIED job must not appear in the grouping.
    create_job(fake_client, company="Ignored Co", title="Something", canonical_key="k4", status="DISCOVERED")
    ctx = make_ctx(fake_client)

    text, markup = handle_companies(ctx)

    buttons = [btn for row in markup["inline_keyboard"] for btn in row]
    labels = {btn["text"] for btn in buttons}
    assert labels == {"Acme (2)", "OpenAI (1)"}
    assert "Ignored Co" not in text


def test_handle_companies_empty_when_no_notified_jobs(fake_client):
    ctx = make_ctx(fake_client)
    text, markup = handle_companies(ctx)
    assert "No notified jobs yet" in text
    assert markup == {}


def test_handle_company_jobs_callback_returns_matching_company_jobs(fake_client):
    create_job(fake_client, company="Acme", title="Backend Engineer", canonical_key="k1")
    create_job(fake_client, company="Acme", title="Platform Engineer", canonical_key="k2")
    create_job(fake_client, company="OpenAI", title="Research Engineer", canonical_key="k3")
    ctx = make_ctx(fake_client)

    callback_data = f"co:{company_callback_hash('Acme')}"
    reply = handle_company_jobs_callback(ctx, callback_data)

    assert "Acme" in reply
    assert "Backend Engineer" in reply
    assert "Platform Engineer" in reply
    assert "Research Engineer" not in reply


def test_handle_company_jobs_callback_unknown_hash(fake_client):
    create_job(fake_client, company="Acme", title="Backend Engineer", canonical_key="k1")
    ctx = make_ctx(fake_client)
    reply = handle_company_jobs_callback(ctx, "co:doesnotexist")
    assert "no longer available" in reply


def test_dispatch_callback_query_routes_company_selection(fake_client):
    create_job(fake_client, company="Acme", title="Backend Engineer", canonical_key="k1")
    ctx = make_ctx(fake_client)
    reply = dispatch_callback_query(ctx, f"co:{company_callback_hash('Acme')}")
    assert "Acme" in reply
    assert "Backend Engineer" in reply


def test_dispatch_callback_query_unrecognized_prefix(fake_client):
    ctx = make_ctx(fake_client)
    reply = dispatch_callback_query(ctx, "unknown:abc")
    assert "Unrecognized selection" in reply


def test_dispatch_command_with_markup_returns_buttons_for_companies(fake_client):
    create_job(fake_client, company="Acme", title="Backend Engineer", canonical_key="k1")
    ctx = make_ctx(fake_client)
    reply, markup = dispatch_command_with_markup(ctx, "/companies")
    assert markup is not None
    assert "inline_keyboard" in markup


def test_dispatch_command_with_markup_no_buttons_for_other_commands(fake_client):
    ctx = make_ctx(fake_client)
    reply, markup = dispatch_command_with_markup(ctx, "/help")
    assert markup is None
    assert "Available commands" in reply
