"""Workspace-scoped row store used by the new modules.

One small abstraction so ingestion, conversation and handoff code can be
tested without Postgres. ``SupabaseTable`` targets PostgREST; ``MemoryTable``
is the in-process fallback used when ``DatabaseClient`` returns ``None``.
Every operation is scoped by ``workspace_id``; RLS enforces the same in SQL.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

from app.config import get_settings
from app.database import DatabaseClient, current_workspace_id

Row = dict[str, Any]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class Table(Protocol):
    name: str
    workspace_id: str

    async def insert(self, row: Row) -> Row: ...
    async def upsert(self, row: Row, on_conflict: str) -> Row: ...
    async def get(self, **filters: Any) -> Row | None: ...
    async def select(self, *, order: str | None = None, desc: bool = False, limit: int = 100, offset: int = 0, **filters: Any) -> list[Row]: ...
    async def update(self, updates: Row, **filters: Any) -> list[Row]: ...
    async def delete(self, **filters: Any) -> int: ...
    async def count(self, **filters: Any) -> int: ...


_MEMORY: dict[str, list[Row]] = defaultdict(list)
_LOCKS: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def reset_memory() -> None:
    _MEMORY.clear()


def _matches(row: Row, filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if key.endswith("__in"):
            if row.get(key[:-4]) not in expected:
                return False
        elif key.endswith("__gte"):
            v = row.get(key[:-5])
            if v is None or v < expected:
                return False
        elif key.endswith("__lte"):
            v = row.get(key[:-5])
            if v is None or v > expected:
                return False
        elif key.endswith("__isnull"):
            if (row.get(key[:-8]) is None) != bool(expected):
                return False
        elif key.endswith("__ne"):
            if row.get(key[:-4]) == expected:
                return False
        elif row.get(key) != expected:
            return False
    return True


class MemoryTable:
    def __init__(self, name: str, workspace_id: str) -> None:
        self.name = name
        self.workspace_id = workspace_id

    @property
    def _rows(self) -> list[Row]:
        return _MEMORY[self.name]

    def _scoped(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"workspace_id": self.workspace_id, **filters}

    async def insert(self, row: Row) -> Row:
        record = {**row, "workspace_id": self.workspace_id}
        record.setdefault("id", new_id())
        record.setdefault("created_at", now_iso())
        self._rows.append(record)
        return deepcopy(record)

    async def upsert(self, row: Row, on_conflict: str) -> Row:
        keys = [k.strip() for k in on_conflict.split(",") if k.strip() != "workspace_id"]
        filters = {k: row.get(k) for k in keys}
        existing = await self.get(**filters)
        if existing is None:
            return await self.insert(row)
        for stored in self._rows:
            if stored.get("id") == existing["id"]:
                stored.update({k: v for k, v in row.items() if k != "id"})
                stored["updated_at"] = now_iso()
                return deepcopy(stored)
        return await self.insert(row)  # pragma: no cover

    async def get(self, **filters: Any) -> Row | None:
        scoped = self._scoped(filters)
        for row in self._rows:
            if _matches(row, scoped):
                return deepcopy(row)
        return None

    async def select(self, *, order: str | None = None, desc: bool = False, limit: int = 100, offset: int = 0, **filters: Any) -> list[Row]:
        scoped = self._scoped(filters)
        rows = [deepcopy(r) for r in self._rows if _matches(r, scoped)]
        if order:
            rows.sort(key=lambda r: (r.get(order) is None, r.get(order)), reverse=desc)
        return rows[offset : offset + limit]

    async def update(self, updates: Row, **filters: Any) -> list[Row]:
        scoped = self._scoped(filters)
        out: list[Row] = []
        for row in self._rows:
            if _matches(row, scoped):
                row.update(updates)
                row["updated_at"] = now_iso()
                out.append(deepcopy(row))
        return out

    async def delete(self, **filters: Any) -> int:
        scoped = self._scoped(filters)
        before = len(self._rows)
        _MEMORY[self.name] = [r for r in self._rows if not _matches(r, scoped)]
        return before - len(_MEMORY[self.name])

    async def count(self, **filters: Any) -> int:
        scoped = self._scoped(filters)
        return sum(1 for r in self._rows if _matches(r, scoped))


class SupabaseTable:
    def __init__(self, client: Any, name: str, workspace_id: str) -> None:
        self.client = client
        self.name = name
        self.workspace_id = workspace_id

    def _q(self):
        return self.client.table(self.name)

    @staticmethod
    def _apply(query: Any, filters: dict[str, Any]) -> Any:
        for key, value in filters.items():
            if key.endswith("__in"):
                query = query.in_(key[:-4], list(value))
            elif key.endswith("__gte"):
                query = query.gte(key[:-5], value)
            elif key.endswith("__lte"):
                query = query.lte(key[:-5], value)
            elif key.endswith("__isnull"):
                query = query.is_(key[:-8], None) if value else query.not_.is_(key[:-8], None)
            elif key.endswith("__ne"):
                query = query.neq(key[:-4], value)
            else:
                query = query.eq(key, value)
        return query

    async def insert(self, row: Row) -> Row:
        result = self._q().insert({**row, "workspace_id": self.workspace_id}).execute()
        return result.data[0] if result.data else {**row, "workspace_id": self.workspace_id}

    async def upsert(self, row: Row, on_conflict: str) -> Row:
        result = self._q().upsert({**row, "workspace_id": self.workspace_id}, on_conflict=on_conflict).execute()
        return result.data[0] if result.data else {**row, "workspace_id": self.workspace_id}

    async def get(self, **filters: Any) -> Row | None:
        query = self._apply(self._q().select("*").eq("workspace_id", self.workspace_id), filters)
        result = query.limit(1).execute()
        return result.data[0] if result.data else None

    async def select(self, *, order: str | None = None, desc: bool = False, limit: int = 100, offset: int = 0, **filters: Any) -> list[Row]:
        query = self._apply(self._q().select("*").eq("workspace_id", self.workspace_id), filters)
        if order:
            query = query.order(order, desc=desc)
        result = query.range(offset, offset + limit - 1).execute()
        return result.data or []

    async def update(self, updates: Row, **filters: Any) -> list[Row]:
        query = self._apply(self._q().update(updates).eq("workspace_id", self.workspace_id), filters)
        result = query.execute()
        return result.data or []

    async def delete(self, **filters: Any) -> int:
        query = self._apply(self._q().delete().eq("workspace_id", self.workspace_id), filters)
        result = query.execute()
        return len(result.data or [])

    async def count(self, **filters: Any) -> int:
        query = self._apply(self._q().select("id", count="exact").eq("workspace_id", self.workspace_id), filters)
        result = query.execute()
        return result.count or 0


def table(name: str, workspace_id: str | None = None) -> Table:
    resolved = workspace_id or current_workspace_id()
    client = DatabaseClient.get_client()
    base: Table = MemoryTable(name, resolved) if client is None else SupabaseTable(client, name, resolved)
    slow_ms = get_settings().FAULT_DB_SLOW_MS
    return SlowTable(base, slow_ms / 1000) if slow_ms > 0 else base


class SlowTable:
    """Fault-injection wrapper (FAULT_DB_SLOW_MS): adds latency to every call."""

    def __init__(self, inner: Table, delay_s: float) -> None:
        self.inner = inner
        self.delay_s = delay_s
        self.name = inner.name
        self.workspace_id = inner.workspace_id

    async def insert(self, row: Row) -> Row:
        await asyncio.sleep(self.delay_s)
        return await self.inner.insert(row)

    async def upsert(self, row: Row, on_conflict: str) -> Row:
        await asyncio.sleep(self.delay_s)
        return await self.inner.upsert(row, on_conflict)

    async def get(self, **filters: Any) -> Row | None:
        await asyncio.sleep(self.delay_s)
        return await self.inner.get(**filters)

    async def select(self, *, order: str | None = None, desc: bool = False, limit: int = 100, offset: int = 0, **filters: Any) -> list[Row]:
        await asyncio.sleep(self.delay_s)
        return await self.inner.select(order=order, desc=desc, limit=limit, offset=offset, **filters)

    async def update(self, updates: Row, **filters: Any) -> list[Row]:
        await asyncio.sleep(self.delay_s)
        return await self.inner.update(updates, **filters)

    async def delete(self, **filters: Any) -> int:
        await asyncio.sleep(self.delay_s)
        return await self.inner.delete(**filters)

    async def count(self, **filters: Any) -> int:
        await asyncio.sleep(self.delay_s)
        return await self.inner.count(**filters)


def lock_for(key: str) -> asyncio.Lock:
    """Process-local lock (the DB row lock covers multi-process deployments)."""
    return _LOCKS[key]


def chunked(items: Iterable[Row], size: int) -> Iterable[list[Row]]:
    batch: list[Row] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
