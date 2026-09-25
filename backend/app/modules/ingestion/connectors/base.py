"""Connector contract and the write-once ``land()`` step (architecture §6.2)."""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Literal, Protocol

from app.modules.ingestion.models import RawRecord
from app.modules.store import Row, now_iso, table


class Connector(Protocol):
    type: str
    mode: Literal["pull", "push"]

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawRecord], str | None]: ...
    async def handle_push(self, headers: dict[str, str], body: bytes) -> list[RawRecord]: ...


class SignatureError(ValueError):
    pass


def verify_hmac_sha256(secret: str, body: bytes, provided: str | None) -> bool:
    if not provided:
        return False
    provided = provided.strip()
    if provided.startswith("sha256="):
        provided = provided[7:]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class LandResult:
    def __init__(self) -> None:
        self.landed: list[Row] = []
        self.duplicates: int = 0

    @property
    def ids(self) -> list[str]:
        return [r["id"] for r in self.landed]


async def land(
    records: list[RawRecord],
    *,
    connector_id: str | None,
    workspace_id: str,
) -> LandResult:
    """Persist raw records before any processing; idempotent on content hash."""
    raw = table("raw_lead_records", workspace_id)
    result = LandResult()
    for record in records:
        digest = record.hash()
        existing = await raw.get(content_hash=digest)
        if existing:
            result.duplicates += 1
            continue
        row = await raw.insert(
            {
                "connector_id": connector_id,
                "external_id": record.external_id,
                "payload": record.payload,
                "content_hash": digest,
                "status": "landed",
                "attempts": 0,
                "error": None,
                "lead_id": None,
                "source_hint": record.source_hint,
                "received_at": record.received_at.isoformat(),
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        )
        result.landed.append(row)
    return result


async def get_connector(connector_id: str, workspace_id: str) -> Row | None:
    return await table("connectors", workspace_id).get(id=connector_id)


async def record_run(connector_id: str, workspace_id: str, *, ok: bool, error: str | None = None) -> Row | None:
    """Update run bookkeeping; pause after 5 consecutive failures (§6.2)."""
    connectors = table("connectors", workspace_id)
    row = await connectors.get(id=connector_id)
    if not row:
        return None
    failures = 0 if ok else int(row.get("consecutive_failures") or 0) + 1
    updates: dict[str, Any] = {
        "last_run_at": now_iso(),
        "consecutive_failures": failures,
        "last_error": error,
        "updated_at": now_iso(),
    }
    if ok:
        updates["last_success_at"] = now_iso()
    elif failures >= 5:
        updates["status"] = "paused"
    updated = await connectors.update(updates, id=connector_id)
    return updated[0] if updated else None
