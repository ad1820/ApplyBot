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
        self.sent_markup = []
        self.fail = fail

    def send_message(self, chat_id, text, reply_markup=None, parse_mode="HTML"):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))
        self.sent_markup.append(reply_markup)
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


def test_multiple_matching_jobs_sent_as_single_grouped_digest(fake_client):
    """Regression test: a run finding several matching jobs must send ONE
    grouped-by-company digest message, not one push per job."""
    bot = FakeTelegramBot()
    jobs = [
        sample_job(title="Backend Engineer", company="Acme", location="India", skills=["python"]),
        sample_job(title="Platform Engineer", company="Acme", location="India", skills=["python"], external_id="2"),
        sample_job(title="Backend Engineer", company="OpenAI", location="India", skills=["python"], external_id="3"),
    ]
    service = build_service(fake_client, jobs, telegram_bot=bot, minimum_match_score=0.0)

    result = service.run({"skills": ["python"]}, {})

    assert result["jobs_notified"] == 3
    assert len(bot.sent) == 1  # exactly one digest message, not three
    digest_text = bot.sent[0][1]
    assert "3 new matching jobs" in digest_text
    assert "2 companies" in digest_text

    # Company names/counts are on the inline-keyboard buttons, not the text.
    markup = bot.sent_markup[0]
    button_labels = [btn["text"] for row in markup["inline_keyboard"] for btn in row]
    assert "Acme (2)" in button_labels
    assert "OpenAI (1)" in button_labels

    job_repo = JobRepository(fake_client)
    statuses = {j["status"] for j in job_repo.list_recent(limit=10)}
    assert statuses == {"NOTIFIED"}


def test_no_matching_jobs_sends_no_digest(fake_client):
    bot = FakeTelegramBot()
    job = sample_job(title="Backend Engineer")  # low score, no telegram config match
    service = build_service(fake_client, [job], telegram_bot=bot, minimum_match_score=100.0)

    service.run({"skills": []}, {})

    assert bot.sent == []


def test_fresher_hiring_roles_are_merged_into_preferred_roles(fake_client, tmp_path, monkeypatch):
    """A job whose title matches a fresher_hiring_roles.txt phrase (but not
    anything explicitly listed in preferences) must still be notified."""
    roles_file = tmp_path / "fresher_hiring_roles.txt"
    roles_file.write_text("Software Development Engineer (SDE)\n", encoding="utf-8")
    monkeypatch.setattr("app.jobs.fresher_roles._ROLES_FILE", roles_file)

    bot = FakeTelegramBot()
    job = sample_job(title="SDE", location="India", skills=["python"])
    service = build_service(fake_client, [job], telegram_bot=bot, minimum_match_score=0.0)

    # preferences only lists an unrelated role - "SDE" only matches via the
    # fresher_hiring_roles.txt augmentation.
    result = service.run({"skills": ["python"]}, {"preferred_roles": ["Data Scientist"]})

    assert result["jobs_notified"] == 1
    assert len(bot.sent) == 1
