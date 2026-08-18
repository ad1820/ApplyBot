"""V2: Referral potential assessments."""
from __future__ import annotations

from typing import Optional

from app.db.repositories.base import BaseRepository


class ReferralAssessmentRepository(BaseRepository):
    table_name = "referral_assessments"

    def create(self, job_id: str, potential: str, reasoning: str, draft_message: Optional[str] = None) -> dict:
        payload = {
            "job_id": job_id,
            "potential": potential,
            "reasoning": reasoning,
            "draft_message": draft_message,
        }
        response = self._table().insert(payload).execute()
        return self._single(response)

    def get_for_job(self, job_id: str) -> Optional[dict]:
        response = (
            self._table()
            .select("*")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return self._single(response)
