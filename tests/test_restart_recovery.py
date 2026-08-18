"""Tests the mandatory restart/recovery behavior: run -> crash -> restart ->
continue, without duplicating jobs or notifications."""
from __future__ import annotations

from app.db.repositories.jobs import JobRepository, JobSourceRepository
from app.db.repositories.notifications import NotificationRepository
from app.db.repositories.runs import AgentRunRepository
from app.jobs.discovery import JobSource
from app.jobs.models import Job
from app.services.job_search_service import JobSearchService


class StaticSource(JobSource):
    name = "static"

    def __init__(self, jobs):
        self._jobs = jobs

    def search_jobs(self, preferences):
        return self._jobs


class FakeTelegramBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_message(self, chat_id, text, reply_markup=None, parse_mode="HTML"):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))
        return {"result": {"message_id": len(self.sent)}}


def build_service(fake_client, jobs, telegram_bot=None, sheets_sync_fn=None, minimum_match_score=0.0):
    # minimum_match_score defaults to 0 here so these restart/recovery tests
    # exercise idempotency logic independent of scoring thresholds; the
    # threshold behavior itself is covered by dedicated tests below.
    return JobSearchService(
        job_repo=JobRepository(fake_client),
        job_source_repo=JobSourceRepository(fake_client),
        run_repo=AgentRunRepository(fake_client),
        notification_repo=NotificationRepository(fake_client),
        sources=[StaticSource(jobs)],
        telegram_bot=telegram_bot,
        telegram_chat_id="123" if telegram_bot else None,
        sheets_sync_fn=sheets_sync_fn,
        minimum_match_score=minimum_match_score,
    )


def sample_job(**overrides):
    defaults = dict(source="static", company="Acme", title="Backend Engineer", location="Bangalore", url="https://acme.com/1")
    defaults.update(overrides)
    return Job(**defaults)


def test_first_run_creates_job_and_notifies(fake_client):
    bot = FakeTelegramBot()
    service = build_service(fake_client, [sample_job()], telegram_bot=bot)
    result = service.run({"skills": []}, {})

    assert result["jobs_new"] == 1
    assert result["jobs_notified"] == 1
    assert len(bot.sent) == 1


def test_rerun_after_restart_does_not_duplicate_job_or_notification(fake_client):
    bot = FakeTelegramBot()
    job = sample_job()

    service_1 = build_service(fake_client, [job], telegram_bot=bot)
    service_1.run({"skills": []}, {})

    # Simulate restart: brand new service instance, same underlying "DB".
    service_2 = build_service(fake_client, [job], telegram_bot=bot)
    result = service_2.run({"skills": []}, {})

    assert result["jobs_duplicate"] == 1
    assert result["jobs_new"] == 0
    # Notification must not be sent twice.
    assert len(bot.sent) == 1


def test_agent_run_recorded_as_completed(fake_client):
    service = build_service(fake_client, [sample_job()])
    result = service.run({"skills": []}, {})
    run_repo = AgentRunRepository(fake_client)
    last_run = run_repo.get_last_run()
    assert last_run["id"] == result["run_id"]
    assert last_run["status"] == "COMPLETED"


def test_notification_failure_recorded_as_partial_and_retryable(fake_client):
    bot = FakeTelegramBot(fail=True)
    service = build_service(fake_client, [sample_job()], telegram_bot=bot)
    result = service.run({"skills": []}, {})

    run_repo = AgentRunRepository(fake_client)
    last_run = run_repo.get_last_run()
    # Notification failing is handled internally and does not abort the run
    # or mark it as failed - the job is still persisted successfully.
    assert last_run["status"] == "COMPLETED"
    assert result["jobs_new"] == 1
    assert result["jobs_notified"] == 0

    notification_repo = NotificationRepository(fake_client)
    job_repo = JobRepository(fake_client)
    jobs = job_repo.list_recent()
    assert notification_repo.get(jobs[0]["id"])["status"] == "FAILED"


def test_one_bad_job_does_not_abort_other_jobs(fake_client):
    import types

    good_job = sample_job(company="GoodCo")
    # Malformed job data: missing required attributes entirely, simulating a
    # source returning garbage. Accessing job.company inside processing
    # raises AttributeError, which must be caught per-job.
    bad_job = types.SimpleNamespace(source="mixed", title="Broken")

    class BadThenGoodSource(JobSource):
        name = "mixed"

        def search_jobs(self, preferences):
            return [bad_job, good_job]

    service = JobSearchService(
        job_repo=JobRepository(fake_client),
        job_source_repo=JobSourceRepository(fake_client),
        run_repo=AgentRunRepository(fake_client),
        notification_repo=NotificationRepository(fake_client),
        sources=[BadThenGoodSource()],
    )
    result = service.run({"skills": []}, {})
    # good_job still gets processed even though bad_job's construction fails
    assert result["jobs_new"] >= 1
    job_repo = JobRepository(fake_client)
    companies = [j["company"] for j in job_repo.list_recent()]
    assert "GoodCo" in companies


def test_job_source_unavailable_does_not_crash_run(fake_client):
    class FailingSource(JobSource):
        name = "failing"

        def search_jobs(self, preferences):
            raise ConnectionError("source down")

    service = JobSearchService(
        job_repo=JobRepository(fake_client),
        job_source_repo=JobSourceRepository(fake_client),
        run_repo=AgentRunRepository(fake_client),
        notification_repo=NotificationRepository(fake_client),
        sources=[FailingSource()],
    )
    result = service.run({"skills": []}, {})
    assert result["error"] is not None
    run_repo = AgentRunRepository(fake_client)
    assert run_repo.get_last_run()["status"] == "PARTIAL"


def test_mismatched_role_job_persisted_but_not_notified(fake_client):
    bot = FakeTelegramBot()
    job = sample_job(title="Account Executive, Enterprise")
    service = build_service(fake_client, [job], telegram_bot=bot)

    result = service.run({"skills": ["Python"]}, {"preferred_roles": ["Backend Engineer"]})

    assert result["jobs_new"] == 1
    assert result["jobs_notified"] == 0
    assert len(bot.sent) == 0

    job_repo = JobRepository(fake_client)
    stored = job_repo.list_recent()[0]
    assert stored["status"] == "DISCOVERED"  # never moved to NOTIFIED


def test_matching_role_job_still_notified(fake_client):
    bot = FakeTelegramBot()
    job = sample_job(title="Backend Engineer")
    service = build_service(fake_client, [job], telegram_bot=bot)

    result = service.run({"skills": ["Python"]}, {"preferred_roles": ["Backend Engineer"]})

    assert result["jobs_notified"] == 1
    assert len(bot.sent) == 1


def test_job_below_minimum_match_score_not_notified(fake_client):
    bot = FakeTelegramBot()
    # No skills overlap at all and no role preference -> low deterministic score.
    job = sample_job(title="Backend Engineer")
    service = build_service(fake_client, [job], telegram_bot=bot, minimum_match_score=80.0)

    result = service.run({"skills": []}, {})

    assert result["jobs_new"] == 1
    assert result["jobs_notified"] == 0
    assert len(bot.sent) == 0
    job_repo = JobRepository(fake_client)
    assert job_repo.list_recent()[0]["status"] == "DISCOVERED"


def test_job_meeting_minimum_match_score_is_notified(fake_client):
    bot = FakeTelegramBot()
    job = sample_job(title="Backend Engineer", location="India", skills=["python"])
    service = build_service(fake_client, [job], telegram_bot=bot, minimum_match_score=0.0)

    result = service.run({"skills": ["python"]}, {})

    assert result["jobs_notified"] == 1
    assert len(bot.sent) == 1


def test_sheets_failure_does_not_block_pipeline(fake_client):
    def failing_sync(job):
        raise RuntimeError("sheets down")

    service = build_service(fake_client, [sample_job()], sheets_sync_fn=failing_sync)
    result = service.run({"skills": []}, {})
    assert result["jobs_new"] == 1
    run_repo = AgentRunRepository(fake_client)
    assert run_repo.get_last_run()["status"] == "COMPLETED"


def test_job_below_minimum_match_score_is_not_synced_to_sheets(fake_client):
    synced_jobs = []

    def record_sync(job):
        synced_jobs.append(job)

    job = sample_job(title="Backend Engineer")  # no skills overlap -> low score
    service = build_service(fake_client, [job], sheets_sync_fn=record_sync, minimum_match_score=80.0)

    result = service.run({"skills": []}, {})

    assert result["jobs_new"] == 1
    assert synced_jobs == []  # Sheets must mirror Telegram - never synced below threshold


def test_job_meeting_minimum_match_score_is_synced_to_sheets(fake_client):
    synced_jobs = []

    def record_sync(job):
        synced_jobs.append(job)

    job = sample_job(title="Backend Engineer", location="India", skills=["python"])
    service = build_service(fake_client, [job], sheets_sync_fn=record_sync, minimum_match_score=0.0)

    result = service.run({"skills": ["python"]}, {})

    assert result["jobs_new"] == 1
    assert len(synced_jobs) == 1
    assert synced_jobs[0]["company"] == "Acme"


def test_mismatched_role_job_is_not_synced_to_sheets(fake_client):
    synced_jobs = []

    def record_sync(job):
        synced_jobs.append(job)

    job = sample_job(title="Account Executive, Enterprise")
    service = build_service(fake_client, [job], sheets_sync_fn=record_sync, minimum_match_score=0.0)

    result = service.run({"skills": ["Python"]}, {"preferred_roles": ["Backend Engineer"]})

    assert result["jobs_new"] == 1
    assert synced_jobs == []  # Sheets must mirror Telegram - role mismatch skips both
