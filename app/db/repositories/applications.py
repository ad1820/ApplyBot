"""Application record persistence and status transitions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.db.repositories.base import BaseRepository

VALID_STATUSES = {"APPLIED", "INTERVIEW", "REJECTED", "OFFER", "WITHDRAWN"}


class ApplicationRepository(BaseRepository):
    table_name = "applications"

    def get_by_job(self, job_id: str) -> Optional[dict]:
        response = self._table().select("*").eq("job_id", job_id).limit(1).execute()
        return self._single(response)

    def record_applied(self, job_id: str, resume_version: Optional[str] = None, notes: Optional[str] = None) -> dict:
        """Create or update the application record for a job, setting it to APPLIED.

        Idempotent: calling /done twice for the same job updates the existing
        record instead of creating a duplicate application.
        """
        existing = self.get_by_job(job_id)
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "job_id": job_id,
            "status": "APPLIED",
            "applied_at": now,
            "resume_version": resume_version,
            "notes": notes,
            "last_updated": now,
        }
        if existing:
            response = self._table().update(payload).eq("id", existing["id"]).execute()
        else:
            response = self._table().insert(payload).execute()
        return self._single(response)

    def set_status(self, job_id: str, status: str, notes: Optional[str] = None) -> Optional[dict]:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid application status: {status}")
        existing = self.get_by_job(job_id)
        if not existing:
            return None
        payload: dict[str, Any] = {
            "status": status,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        if notes is not None:
            payload["notes"] = notes
        response = self._table().update(payload).eq("id", existing["id"]).execute()
        return self._single(response)

    def list_all(self) -> list[dict]:
        response = self._table().select("*").execute()
        return self._many(response)
