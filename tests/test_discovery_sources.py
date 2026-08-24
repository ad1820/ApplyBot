"""Tests for the additional public job-board sources (all mocked via
httpx.MockTransport - no live network calls in the test suite)."""
from __future__ import annotations

import httpx

from app.jobs.discovery import (
    AshbySource,
    HimalayasSource,
    LeverSource,
    RemoteOKSource,
    RemotiveSource,
    WeWorkRemotelySource,
    WorkingNomadsSource,
)
from app.jobs.models import WorkMode


def make_client(json_response=None, text_response=None, status=200):
    def handler(request):
        if text_response is not None:
            return httpx.Response(status, text=text_response)
        return httpx.Response(status, json=json_response)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_remoteok_source_normalizes_and_skips_metadata_row():
    data = [
        {"legal": "notice"},
        {"id": "1", "position": "Backend Engineer", "company": "Acme", "tags": ["python"], "url": "https://x.com/1"},
    ]
    source = RemoteOKSource(client=make_client(json_response=data))
    jobs = source.search_jobs({})
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].work_mode == WorkMode.REMOTE
    assert jobs[0].source == "remoteok"


def test_remoteok_source_handles_failure_gracefully():
    source = RemoteOKSource(client=make_client(status=500, json_response={}))
    assert source.search_jobs({}) == []


def test_remotive_source_normalizes():
    data = {"jobs": [{"id": 5, "title": "Python Developer", "company_name": "Acme", "candidate_required_location": "Worldwide", "tags": ["python", "django"], "url": "https://x.com/5"}]}
    source = RemotiveSource(client=make_client(json_response=data))
    jobs = source.search_jobs({})
    assert len(jobs) == 1
    assert jobs[0].company == "Acme"
    assert jobs[0].skills == ["python", "django"]


def test_workingnomads_source_normalizes_comma_separated_tags():
    data = [{"title": "Backend Dev", "company_name": "Acme", "tags": "python, docker", "url": "https://x.com/1", "location": "Remote"}]
    source = WorkingNomadsSource(client=make_client(json_response=data))
    jobs = source.search_jobs({})
    assert len(jobs) == 1
    assert jobs[0].skills == ["python", "docker"]


def test_himalayas_source_normalizes():
    data = {"jobs": [{"title": "Data Engineer", "companyName": "Acme", "categories": ["Data-Engineering"], "locationRestrictions": ["Worldwide"], "applicationLink": "https://x.com/1"}]}
    source = HimalayasSource(client=make_client(json_response=data))
    jobs = source.search_jobs({})
    assert len(jobs) == 1
    assert jobs[0].company == "Acme"
    assert jobs[0].work_mode == WorkMode.REMOTE


def test_weworkremotely_source_parses_rss_and_splits_company_title():
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
    <item>
      <title>Acme: Backend Engineer</title>
      <link>https://weworkremotely.com/jobs/1</link>
      <description>Job details here</description>
      <region>Anywhere in the World</region>
    </item>
    </channel></rss>"""
    source = WeWorkRemotelySource(client=make_client(text_response=rss))
    jobs = source.search_jobs({})
    assert len(jobs) == 1
    assert jobs[0].company == "Acme"
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].work_mode == WorkMode.REMOTE


def test_weworkremotely_source_handles_malformed_xml_gracefully():
    source = WeWorkRemotelySource(client=make_client(text_response="not xml at all"))
    assert source.search_jobs({}) == []


def test_lever_source_normalizes():
    data = [
        {
            "id": "abc123",
            "text": "Backend Engineer",
            "categories": {"location": "Bangalore, India", "commitment": "Full-time"},
            "descriptionPlain": "Build things",
            "hostedUrl": "https://jobs.lever.co/acme/abc123",
            "createdAt": 1700000000000,
        }
    ]
    source = LeverSource(company_slugs=["acme"], client=make_client(json_response=data))
    jobs = source.search_jobs({})
    assert len(jobs) == 1
    assert jobs[0].company == "acme"
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].location == "Bangalore, India"
    assert jobs[0].url == "https://jobs.lever.co/acme/abc123"
    assert jobs[0].posted_at is not None


def test_lever_source_handles_failure_gracefully():
    source = LeverSource(company_slugs=["nope"], client=make_client(status=404, json_response={}))
    assert source.search_jobs({}) == []


def test_lever_source_ignores_non_list_response():
    source = LeverSource(company_slugs=["nope"], client=make_client(json_response={"ok": False}))
    assert source.search_jobs({}) == []


def test_ashby_source_normalizes():
    data = {
        "jobs": [
            {
                "id": "xyz789",
                "title": "Data Engineer",
                "location": "Remote - India",
                "workplaceType": "Remote",
                "descriptionPlain": "Work on data pipelines",
                "jobUrl": "https://jobs.ashbyhq.com/acme/xyz789",
                "publishedAt": "2026-08-01T00:00:00Z",
            }
        ]
    }
    source = AshbySource(company_slugs=["acme"], client=make_client(json_response=data))
    jobs = source.search_jobs({})
    assert len(jobs) == 1
    assert jobs[0].company == "acme"
    assert jobs[0].title == "Data Engineer"
    assert jobs[0].work_mode == WorkMode.REMOTE
    assert jobs[0].url == "https://jobs.ashbyhq.com/acme/xyz789"


def test_ashby_source_handles_failure_gracefully():
    source = AshbySource(company_slugs=["nope"], client=make_client(status=404, json_response={}))
    assert source.search_jobs({}) == []
