"""Job persistence, dedup lookups and status transitions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.db.repositories.base import BaseRepository

VALID_STATUSES = {
    "DISCOVERED",
    "NOTIFIED",
    "INTERESTED",
    "SKIPPED",
    "APPLIED",
    "INTERVIEW",
    "REJECTED",
    "OFFER",
    "WITHDRAWN",
}


class JobRepository(BaseRepository):
    table_name = "jobs"

    def find_by_canonical_key(self, canonical_key: str) -> Optional[dict]:
        response = (
            self._table().select("*").eq("canonical_key", canonical_key).limit(1).execute()
        )
        return self._single(response)

    def get(self, job_id: str) -> Optional[dict]:
        response = self._table().select("*").eq("id", job_id).limit(1).execute()
        return self._single(response)

    def create(self, job: dict[str, Any]) -> dict:
        response = self._table().insert(job).execute()
        return self._single(response)

    def update(self, job_id: str, fields: dict[str, Any]) -> dict:
        payload = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
        response = self._table().update(payload).eq("id", job_id).execute()
        return self._single(response)

    def set_status(self, job_id: str, status: str) -> dict:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid job status: {status}")
        return self.update(job_id, {"status": status})

    def list_by_status(self, status: str) -> list[dict]:
        response = self._table().select("*").eq("status", status).execute()
        return self._many(response)

    def list_recent(self, limit: int = 20) -> list[dict]:
        response = (
            self._table()
            .select("*")
            .order("discovered_at", desc=True)
            .limit(limit)
            .execute()
        )
        return self._many(response)


class JobSourceRepository(BaseRepository):
    table_name = "job_sources"

    def add_source(self, job_id: str, source: str, external_id: Optional[str], url: Optional[str]) -> dict:
        """Idempotently record that `source` also found this job.

        Uses upsert semantics via the unique (job_id, source, external_id)
        constraint so re-processing the same discovery never duplicates rows.
        """
        payload = {
            "job_id": job_id,
            "source": source,
            "external_id": external_id,
            "url": url,
        }
        response = self._table().upsert(payload, on_conflict="job_id,source,external_id").execute()
        return self._single(response)

    def list_for_job(self, job_id: str) -> list[dict]:
        response = self._table().select("*").eq("job_id", job_id).execute()
        return self._many(response)
