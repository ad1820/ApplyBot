"""Shared repository helpers.

All repositories take a Supabase client (or a compatible fake, e.g. in
tests) through their constructor - dependency injection rather than a
module-level singleton makes the repositories fully unit-testable without
any network access.
"""
from __future__ import annotations

from typing import Any, Optional


class BaseRepository:
    table_name: str = ""

    def __init__(self, client: Any) -> None:
        self.client = client

    def _table(self):
        return self.client.table(self.table_name)

    @staticmethod
    def _single(response: Any) -> Optional[dict]:
        data = getattr(response, "data", None)
        if not data:
            return None
        if isinstance(data, list):
            return data[0] if data else None
        return data

    @staticmethod
    def _many(response: Any) -> list[dict]:
        data = getattr(response, "data", None)
        return data or []
