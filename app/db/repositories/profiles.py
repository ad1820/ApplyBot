"""Candidate profile & job preference persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.db.repositories.base import BaseRepository


class CandidateProfileRepository(BaseRepository):
    table_name = "candidate_profiles"

    def get(self) -> Optional[dict]:
        """A single-user system - return the first (and only) profile."""
        response = self._table().select("*").limit(1).execute()
        return self._single(response)

    def upsert(self, profile: dict[str, Any]) -> dict:
        existing = self.get()
        payload = {**profile, "updated_at": datetime.now(timezone.utc).isoformat()}
        if existing:
            response = self._table().update(payload).eq("id", existing["id"]).execute()
        else:
            response = self._table().insert(payload).execute()
        return self._single(response)


class JobPreferencesRepository(BaseRepository):
    table_name = "job_preferences"

    def get_for_profile(self, profile_id: str) -> Optional[dict]:
        response = (
            self._table().select("*").eq("profile_id", profile_id).limit(1).execute()
        )
        return self._single(response)

    def upsert(self, profile_id: str, preferences: dict[str, Any]) -> dict:
        existing = self.get_for_profile(profile_id)
        payload = {
            **preferences,
            "profile_id": profile_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if existing:
            response = self._table().update(payload).eq("id", existing["id"]).execute()
        else:
            response = self._table().insert(payload).execute()
        return self._single(response)
