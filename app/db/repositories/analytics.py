"""V2: Analytics event logging + simple statistics (no ML)."""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from app.db.repositories.base import BaseRepository


class AnalyticsEventRepository(BaseRepository):
    table_name = "analytics_events"

    def record(self, event_type: str, job_id: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
        payload = {"event_type": event_type, "job_id": job_id, "metadata": metadata or {}}
        response = self._table().insert(payload).execute()
        return self._single(response)

    def list_all(self) -> list[dict]:
        response = self._table().select("*").execute()
        return self._many(response)


def compute_funnel_stats(events: list[dict]) -> dict[str, Any]:
    """Pure function: simple statistics over a list of analytics events.

    Kept separate from the repository so it can be unit tested without a
    database at all.
    """
    counts = Counter(event["event_type"] for event in events)
    applications = counts.get("APPLIED", 0)
    interviews = counts.get("INTERVIEW", 0)
    rejections = counts.get("REJECTED", 0)
    offers = counts.get("OFFER", 0)

    def rate(numerator: int, denominator: int) -> float:
        return round((numerator / denominator) * 100, 1) if denominator else 0.0

    return {
        "discovered": counts.get("DISCOVERED", 0),
        "viewed": counts.get("VIEWED", 0),
        "skipped": counts.get("SKIPPED", 0),
        "applications": applications,
        "interviews": interviews,
        "rejections": rejections,
        "offers": offers,
        "application_rate": rate(applications, counts.get("DISCOVERED", 0)),
        "interview_rate": rate(interviews, applications),
        "rejection_rate": rate(rejections, applications),
        "offer_rate": rate(offers, applications),
    }
