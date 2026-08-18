from app.db.repositories.analytics import compute_funnel_stats
from app.agents.analytics_agent import breakdown_by_field, interview_rate_by_match_bucket


def test_compute_funnel_stats_basic_rates():
    events = (
        [{"event_type": "DISCOVERED"} for _ in range(10)]
        + [{"event_type": "APPLIED"} for _ in range(4)]
        + [{"event_type": "INTERVIEW"} for _ in range(2)]
        + [{"event_type": "OFFER"} for _ in range(1)]
    )
    stats = compute_funnel_stats(events)
    assert stats["applications"] == 4
    assert stats["interviews"] == 2
    assert stats["interview_rate"] == 50.0
    assert stats["offer_rate"] == 25.0


def test_compute_funnel_stats_handles_empty():
    stats = compute_funnel_stats([])
    assert stats["application_rate"] == 0.0
    assert stats["interview_rate"] == 0.0


def test_breakdown_by_field_role():
    jobs_by_id = {"1": {"title": "Backend"}, "2": {"title": "Frontend"}}
    applications = [
        {"job_id": "1", "status": "INTERVIEW"},
        {"job_id": "1", "status": "APPLIED"},
        {"job_id": "2", "status": "REJECTED"},
    ]
    result = breakdown_by_field(applications, jobs_by_id, "title")
    assert result["Backend"]["applications"] == 2
    assert result["Backend"]["interviews"] == 1
    assert result["Frontend"]["interviews"] == 0


def test_interview_rate_by_match_bucket():
    jobs_by_id = {"1": {"match_score": 90}, "2": {"match_score": 60}}
    applications = [
        {"job_id": "1", "status": "INTERVIEW"},
        {"job_id": "2", "status": "REJECTED"},
    ]
    result = interview_rate_by_match_bucket(applications, jobs_by_id)
    assert result["> 85"] == 100.0
    assert result["< 70"] == 0.0
