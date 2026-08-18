"""Agent run lifecycle tracking - the backbone of restart/recovery.

Every scheduled job-search execution starts a row here. If the process
crashes mid-run, the next invocation can inspect the last run's status and
safely resume/retry rather than assuming nothing happened.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.db.repositories.base import BaseRepository


class AgentRunRepository(BaseRepository):
    table_name = "agent_runs"

    def start_run(self, source: str) -> dict:
        payload = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING",
            "source": source,
            "jobs_found": 0,
            "jobs_new": 0,
            "jobs_duplicate": 0,
            "jobs_notified": 0,
        }
        response = self._table().insert(payload).execute()
        return self._single(response)

    def update_counters(self, run_id: str, **counters: int) -> dict:
        response = self._table().update(counters).eq("id", run_id).execute()
        return self._single(response)

    def complete_run(self, run_id: str, **counters: Any) -> dict:
        payload = {
            "status": "COMPLETED",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            **counters,
        }
        response = self._table().update(payload).eq("id", run_id).execute()
        return self._single(response)

    def partial_run(self, run_id: str, error_message: str, **counters: Any) -> dict:
        payload = {
            "status": "PARTIAL",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error_message": error_message,
            **counters,
        }
        response = self._table().update(payload).eq("id", run_id).execute()
        return self._single(response)

    def fail_run(self, run_id: str, error_message: str) -> dict:
        payload = {
            "status": "FAILED",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error_message": error_message,
        }
        response = self._table().update(payload).eq("id", run_id).execute()
        return self._single(response)

    def get_last_run(self, source: Optional[str] = None) -> Optional[dict]:
        query = self._table().select("*").order("started_at", desc=True).limit(1)
        if source:
            query = query.eq("source", source)
        response = query.execute()
        return self._single(response)

    def get_incomplete_runs(self) -> list[dict]:
        """Runs that never reached a terminal state - candidates for retry."""
        response = self._table().select("*").eq("status", "RUNNING").execute()
        return self._many(response)
