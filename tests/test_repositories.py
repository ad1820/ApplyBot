from app.db.repositories.applications import ApplicationRepository
from app.db.repositories.jobs import JobRepository, JobSourceRepository
from app.db.repositories.notifications import NotificationRepository
from app.db.repositories.profiles import CandidateProfileRepository
from app.db.repositories.runs import AgentRunRepository


def make_job(client, **overrides):
    payload = {
        "external_id": "1",
        "source": "greenhouse",
        "company": "Acme",
        "title": "Backend Engineer",
        "location": "Bangalore",
        "canonical_key": "abc123",
        "status": "DISCOVERED",
    }
    payload.update(overrides)
    return JobRepository(client).create(payload)


def test_job_repository_create_and_get(fake_client):
    repo = JobRepository(fake_client)
    created = make_job(fake_client)
    fetched = repo.get(created["id"])
    assert fetched["company"] == "Acme"


def test_job_repository_find_by_canonical_key(fake_client):
    repo = JobRepository(fake_client)
    make_job(fake_client, canonical_key="dupkey")
    found = repo.find_by_canonical_key("dupkey")
    assert found is not None
    assert repo.find_by_canonical_key("missing") is None


def test_job_repository_set_status_validates(fake_client):
    repo = JobRepository(fake_client)
    created = make_job(fake_client)
    updated = repo.set_status(created["id"], "NOTIFIED")
    assert updated["status"] == "NOTIFIED"

    try:
        repo.set_status(created["id"], "NOT_A_STATUS")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_job_source_repository_preserves_multiple_sources(fake_client):
    job_repo = JobRepository(fake_client)
    source_repo = JobSourceRepository(fake_client)
    created = make_job(fake_client)

    source_repo.add_source(created["id"], "greenhouse", "1", "https://a.com/1")
    source_repo.add_source(created["id"], "lever", "2", "https://b.com/2")
    # Re-adding the same source should not duplicate.
    source_repo.add_source(created["id"], "greenhouse", "1", "https://a.com/1")

    sources = source_repo.list_for_job(created["id"])
    assert len(sources) == 2


def test_application_repository_record_applied_idempotent(fake_client):
    job = make_job(fake_client)
    repo = ApplicationRepository(fake_client)

    first = repo.record_applied(job["id"], resume_version="v1")
    second = repo.record_applied(job["id"], resume_version="v1")

    assert first["id"] == second["id"]
    assert repo.get_by_job(job["id"])["status"] == "APPLIED"


def test_application_repository_set_status(fake_client):
    job = make_job(fake_client)
    repo = ApplicationRepository(fake_client)
    repo.record_applied(job["id"])
    updated = repo.set_status(job["id"], "INTERVIEW")
    assert updated["status"] == "INTERVIEW"

    try:
        repo.set_status(job["id"], "NOT_VALID")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_notification_repository_idempotency(fake_client):
    job = make_job(fake_client)
    repo = NotificationRepository(fake_client)

    assert repo.already_sent(job["id"]) is False
    repo.record_pending(job["id"])
    assert repo.already_sent(job["id"]) is False

    repo.mark_sent(job["id"], "12345")
    assert repo.already_sent(job["id"]) is True


def test_agent_run_repository_lifecycle(fake_client):
    repo = AgentRunRepository(fake_client)
    run = repo.start_run(source="scheduled")
    assert run["status"] == "RUNNING"

    completed = repo.complete_run(run["id"], jobs_found=5, jobs_new=3)
    assert completed["status"] == "COMPLETED"
    assert completed["jobs_found"] == 5

    last = repo.get_last_run(source="scheduled")
    assert last["id"] == run["id"]


def test_agent_run_repository_incomplete_runs_detected(fake_client):
    repo = AgentRunRepository(fake_client)
    run = repo.start_run(source="scheduled")
    incomplete = repo.get_incomplete_runs()
    assert any(r["id"] == run["id"] for r in incomplete)

    repo.fail_run(run["id"], "boom")
    incomplete_after = repo.get_incomplete_runs()
    assert not any(r["id"] == run["id"] for r in incomplete_after)


def test_candidate_profile_repository_upsert_single_row(fake_client):
    repo = CandidateProfileRepository(fake_client)
    created = repo.upsert({"name": "Alice", "email": "alice@example.com"})
    updated = repo.upsert({"name": "Alice Updated", "email": "alice@example.com"})
    assert created["id"] == updated["id"]
    assert repo.get()["name"] == "Alice Updated"
