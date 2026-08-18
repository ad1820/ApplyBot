"""Notification tracking - prevents duplicate Telegram messages after restart."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.db.repositories.base import BaseRepository


class NotificationRepository(BaseRepository):
    table_name = "notifications"

    def already_sent(self, job_id: str, channel: str = "telegram") -> bool:
        response = (
            self._table()
            .select("*")
            .eq("job_id", job_id)
            .eq("channel", channel)
            .eq("status", "SENT")
            .limit(1)
            .execute()
        )
        return self._single(response) is not None

    def get(self, job_id: str, channel: str = "telegram") -> Optional[dict]:
        response = (
            self._table().select("*").eq("job_id", job_id).eq("channel", channel).limit(1).execute()
        )
        return self._single(response)

    def record_pending(self, job_id: str, channel: str = "telegram") -> dict:
        existing = self.get(job_id, channel)
        if existing:
            return existing
        payload = {"job_id": job_id, "channel": channel, "status": "PENDING"}
        response = self._table().insert(payload).execute()
        return self._single(response)

    def mark_sent(self, job_id: str, telegram_message_id: Optional[str], channel: str = "telegram") -> dict:
        existing = self.get(job_id, channel)
        payload = {
            "status": "SENT",
            "telegram_message_id": telegram_message_id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        if existing:
            response = self._table().update(payload).eq("id", existing["id"]).execute()
        else:
            payload.update({"job_id": job_id, "channel": channel})
            response = self._table().insert(payload).execute()
        return self._single(response)

    def mark_failed(self, job_id: str, error_message: str, channel: str = "telegram") -> dict:
        existing = self.get(job_id, channel)
        payload = {"status": "FAILED", "error_message": error_message}
        if existing:
            response = self._table().update(payload).eq("id", existing["id"]).execute()
        else:
            payload.update({"job_id": job_id, "channel": channel})
            response = self._table().insert(payload).execute()
        return self._single(response)
