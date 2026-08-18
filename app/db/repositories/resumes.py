"""V2: Master resume, tailored resumes and cover letters.

Master resume versions are never overwritten - each update creates a new
version row so every application can reference the exact resume version
used.
"""
from __future__ import annotations

from typing import Any, Optional

from app.db.repositories.base import BaseRepository


class MasterResumeRepository(BaseRepository):
    table_name = "master_resumes"

    def get_latest(self) -> Optional[dict]:
        response = self._table().select("*").order("version", desc=True).limit(1).execute()
        return self._single(response)

    def create_new_version(self, content: str) -> dict:
        latest = self.get_latest()
        next_version = (latest["version"] + 1) if latest else 1
        payload = {"version": next_version, "content": content}
        response = self._table().insert(payload).execute()
        return self._single(response)

    def get_version(self, version: int) -> Optional[dict]:
        response = self._table().select("*").eq("version", version).limit(1).execute()
        return self._single(response)


class TailoredResumeRepository(BaseRepository):
    table_name = "tailored_resumes"

    def create(self, data: dict[str, Any]) -> dict:
        response = self._table().insert(data).execute()
        return self._single(response)

    def list_for_job(self, job_id: str) -> list[dict]:
        response = self._table().select("*").eq("job_id", job_id).execute()
        return self._many(response)

    def approve(self, tailored_resume_id: str) -> dict:
        response = self._table().update({"approved": True}).eq("id", tailored_resume_id).execute()
        return self._single(response)


class CoverLetterRepository(BaseRepository):
    table_name = "cover_letters"

    def create(self, job_id: str, content: str) -> dict:
        response = self._table().insert({"job_id": job_id, "content": content}).execute()
        return self._single(response)

    def approve(self, cover_letter_id: str) -> dict:
        response = self._table().update({"approved": True}).eq("id", cover_letter_id).execute()
        return self._single(response)

    def list_for_job(self, job_id: str) -> list[dict]:
        response = self._table().select("*").eq("job_id", job_id).execute()
        return self._many(response)
