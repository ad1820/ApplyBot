"""A minimal in-memory fake of the supabase-py client/query-builder chain,
sufficient to exercise the repository layer without any network access.

Supports: select/insert/update/upsert, eq filters, order, limit, execute.
"""
from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any


class _Response:
    def __init__(self, data: list[dict]):
        self.data = data


class _QueryBuilder:
    def __init__(self, store: dict[str, list[dict]], table_name: str):
        self._store = store
        self._table_name = table_name
        self._op: str | None = None
        self._payload: Any = None
        self._filters: list[tuple[str, Any]] = []
        self._order_field: str | None = None
        self._order_desc = False
        self._limit: int | None = None
        self._on_conflict: str | None = None

    # --- write ops ---
    def insert(self, payload: dict) -> "_QueryBuilder":
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict) -> "_QueryBuilder":
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload: dict, on_conflict: str | None = None) -> "_QueryBuilder":
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    # --- read ops ---
    def select(self, *_args, **_kwargs) -> "_QueryBuilder":
        self._op = self._op or "select"
        return self

    def eq(self, field: str, value: Any) -> "_QueryBuilder":
        self._filters.append((field, value))
        return self

    def order(self, field: str, desc: bool = False) -> "_QueryBuilder":
        self._order_field = field
        self._order_desc = desc
        return self

    def limit(self, count: int) -> "_QueryBuilder":
        self._limit = count
        return self

    def _rows(self) -> list[dict]:
        rows = self._store.setdefault(self._table_name, [])
        for field, value in self._filters:
            rows = [r for r in rows if r.get(field) == value]
        return rows

    def execute(self) -> _Response:
        table = self._store.setdefault(self._table_name, [])

        if self._op == "insert":
            row = deepcopy(self._payload)
            row.setdefault("id", str(uuid.uuid4()))
            table.append(row)
            return _Response([row])

        if self._op == "update":
            matched = self._rows()
            for row in matched:
                row.update(self._payload)
            return _Response(deepcopy(matched))

        if self._op == "upsert":
            conflict_fields = (self._on_conflict or "id").split(",")
            existing = None
            for row in table:
                if all(row.get(f) == self._payload.get(f) for f in conflict_fields):
                    existing = row
                    break
            if existing:
                existing.update(self._payload)
                return _Response([deepcopy(existing)])
            row = deepcopy(self._payload)
            row.setdefault("id", str(uuid.uuid4()))
            table.append(row)
            return _Response([row])

        # select
        rows = self._rows()
        if self._order_field:
            rows = sorted(rows, key=lambda r: r.get(self._order_field) or "", reverse=self._order_desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Response(deepcopy(rows))


class FakeSupabaseClient:
    def __init__(self):
        self._store: dict[str, list[dict]] = {}

    def table(self, name: str) -> _QueryBuilder:
        return _QueryBuilder(self._store, name)
