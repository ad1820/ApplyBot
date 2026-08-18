from datetime import datetime, timezone

from app.jobs.discovery import UserProvidedSource, _guess_work_mode
from app.jobs.models import Job, WorkMode


def test_user_provided_source_normalizes_jobs():
    source = UserProvidedSource(
        [
            {
                "company": "Acme",
                "title": "Backend Engineer",
                "location": "Bangalore, India",
                "description": "Remote friendly role using Python and FastAPI",
                "skills": ["Python", "FastAPI"],
                "url": "https://acme.com/careers/123",
            }
        ]
    )
    jobs = source.search_jobs({})
    assert len(jobs) == 1
    job = jobs[0]
    assert isinstance(job, Job)
    assert job.company == "Acme"
    assert job.title == "Backend Engineer"
    assert job.work_mode == WorkMode.REMOTE
    assert job.skills == ["Python", "FastAPI"]
    assert job.source == "user_provided"


def test_guess_work_mode():
    assert _guess_work_mode("This is a remote position") == WorkMode.REMOTE
    assert _guess_work_mode("Hybrid work from our SF office") == WorkMode.HYBRID
    assert _guess_work_mode("Onsite only") == WorkMode.ONSITE
    assert _guess_work_mode(None) == WorkMode.UNKNOWN
    assert _guess_work_mode("No hints here") == WorkMode.UNKNOWN


def test_job_model_malformed_data_defaults_gracefully():
    # Malformed / incomplete job data must not crash normalization.
    job = Job(source="test", company="Acme", title="Engineer")
    assert job.location is None
    assert job.skills == []
    assert job.work_mode == WorkMode.UNKNOWN
    assert job.status.value == "DISCOVERED"
