"""V2: Application question extraction & persistent, user-approved answers.

Persisted USER_APPROVED answers let the answer engine reuse previously
approved responses to sensitive/ambiguous questions instead of ever
guessing them again.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.db.repositories.base import BaseRepository


def normalize_question(question_text: str) -> str:
    return " ".join(question_text.strip().lower().split())


class ApplicationQuestionRepository(BaseRepository):
    table_name = "application_questions"

    def create(self, job_id: str, question_text: str, category: str, platform: Optional[str] = None) -> dict:
        payload = {
            "job_id": job_id,
            "question_text": question_text,
            "category": category,
            "platform": platform,
        }
        response = self._table().insert(payload).execute()
        return self._single(response)

    def list_for_job(self, job_id: str) -> list[dict]:
        response = self._table().select("*").eq("job_id", job_id).execute()
        return self._many(response)


class ApplicationAnswerRepository(BaseRepository):
    table_name = "application_answers"

    def find_answer(self, question_text: str) -> Optional[dict]:
        normalized = normalize_question(question_text)
        response = (
            self._table().select("*").eq("normalized_question", normalized).limit(1).execute()
        )
        return self._single(response)

    def save_answer(self, question_text: str, answer: str, source: str, approved: bool = False) -> dict:
        normalized = normalize_question(question_text)
        existing = self.find_answer(question_text)
        payload = {
            "question_text": question_text,
            "normalized_question": normalized,
            "answer": answer,
            "source": source,
            "approved_at": datetime.now(timezone.utc).isoformat() if approved else None,
        }
        if existing:
            response = self._table().update(payload).eq("id", existing["id"]).execute()
        else:
            response = self._table().insert(payload).execute()
        return self._single(response)
