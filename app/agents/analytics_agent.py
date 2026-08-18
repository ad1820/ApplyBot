"""V2: Analytics - simple statistics over application history, with
breakdowns by role/company type/location/technology/source/match-score
bucket. Deliberately simple (no ML) per project philosophy.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.db.repositories.analytics import compute_funnel_stats


def breakdown_by_field(applications: list[dict[str, Any]], jobs_by_id: dict[str, dict], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for app in applications:
        job = jobs_by_id.get(app["job_id"], {})
        key = job.get(field) or "Unknown"
        groups[key].append(app)

    result = {}
    for key, apps in groups.items():
        interviews = sum(1 for a in apps if a["status"] in ("INTERVIEW", "OFFER"))
        result[key] = {
            "applications": len(apps),
            "interviews": interviews,
            "interview_rate": round((interviews / len(apps)) * 100, 1) if apps else 0.0,
        }
    return result


def match_score_bucket(score: float) -> str:
    if score is None:
        return "unknown"
    if score > 85:
        return "> 85"
    if score >= 70:
        return "70-85"
    return "< 70"


def interview_rate_by_match_bucket(applications: list[dict[str, Any]], jobs_by_id: dict[str, dict]) -> dict[str, Any]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for app in applications:
        job = jobs_by_id.get(app["job_id"], {})
        bucket = match_score_bucket(job.get("match_score"))
        groups[bucket].append(app)

    result = {}
    for bucket, apps in groups.items():
        interviews = sum(1 for a in apps if a["status"] in ("INTERVIEW", "OFFER"))
        result[bucket] = round((interviews / len(apps)) * 100, 1) if apps else 0.0
    return result
