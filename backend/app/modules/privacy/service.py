"""PDPL data-subject requests.

* ``export_lead``   – every row we hold about one buyer, as one JSON document.
* ``erase_lead``    – irreversible: personal data is removed from the lead row
  (the id survives so counts/funnels stay correct), conversation, raw records,
  briefs, voice sessions and events are deleted, and the contact points are
  added to ``suppression_list`` so a later import cannot resurrect the buyer.
* ``record_consent`` – append-only consent ledger on the lead (``consent`` jsonb).
* ``retention_purge`` – scheduled: raw records past ``RETENTION_RAW_DAYS`` are
  deleted; unconverted leads idle past ``RETENTION_LEAD_DAYS`` are erased.

Every request is written to ``privacy_requests`` before any data changes so
the audit trail exists even if the erasure is interrupted (it is idempotent
and retried by the same call).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.database import get_lead_repository
from app.modules.ingestion.pipeline.processor import suppress_contact
from app.modules.store import Row, new_id, now_iso, table

logger = logging.getLogger(__name__)

PII_FIELDS = (
    "first_name",
    "last_name",
    "name",
    "phone",
    "phone_e164",
    "email",
    "notes",
    "nationality",
    "crm_external_id",
    "raw_payload",
)

LEAD_LINKED_TABLES = (
    "messages",
    "conversation_states",
    "voice_sessions",
    "handoffs",
    "followups",
    "viewings",
    "lead_events",
    "lead_sources",
    "lead_change_log",
    "review_queue",
)

ERASED_MARKER = "[erased]"


async def export_lead(lead_id: str, workspace_id: str, *, requested_by: str | None) -> dict[str, Any] | None:
    lead = await get_lead_repository(workspace_id).get_by_id(lead_id)
    if not lead:
        return None
    bundle: dict[str, Any] = {"lead": lead, "exported_at": now_iso(), "workspace_id": workspace_id}
    for name in LEAD_LINKED_TABLES:
        bundle[name] = await table(name, workspace_id).select(lead_id=lead_id, limit=5_000)
    bundle["raw_lead_records"] = await table("raw_lead_records", workspace_id).select(lead_id=lead_id, limit=5_000)
    await _log_request(workspace_id, lead_id, kind="export", requested_by=requested_by, status="completed")
    return bundle


async def erase_lead(lead_id: str, workspace_id: str, *, requested_by: str | None, reason: str = "data_subject_request") -> dict[str, Any] | None:
    repo = get_lead_repository(workspace_id)
    lead = await repo.get_by_id(lead_id)
    if not lead:
        return None
    request = await _log_request(workspace_id, lead_id, kind="erase", requested_by=requested_by, status="in_progress", reason=reason)

    await suppress_contact(workspace_id, phone=lead.get("phone_e164") or lead.get("phone"), email=lead.get("email"), reason="erased")

    deleted: dict[str, int] = {}
    for name in LEAD_LINKED_TABLES:
        deleted[name] = await table(name, workspace_id).delete(lead_id=lead_id)
    deleted["raw_lead_records"] = await table("raw_lead_records", workspace_id).delete(lead_id=lead_id)

    scrub = {f: None for f in PII_FIELDS if f in lead}
    scrub.update(
        {
            "first_name": ERASED_MARKER,
            "status": "erased",
            "stage": "erased",
            "erased_at": now_iso(),
            "opted_out_at": lead.get("opted_out_at") or now_iso(),
            "buyer_confirmed_fields": [],
            "broker_edited_fields": [],
            "consent": {"erased": True, "at": now_iso()},
        }
    )
    await repo.update(lead_id, scrub)
    await table("privacy_requests", workspace_id).update({"status": "completed", "completed_at": now_iso(), "detail": deleted}, id=request["id"])
    return {"lead_id": lead_id, "deleted": deleted, "request_id": request["id"]}


async def record_consent(lead_id: str, workspace_id: str, *, purpose: str, granted: bool, channel: str, source: str) -> Row | None:
    repo = get_lead_repository(workspace_id)
    lead = await repo.get_by_id(lead_id)
    if not lead:
        return None
    consent = dict(lead.get("consent") or {})
    history = list(consent.get("history") or [])
    entry = {"purpose": purpose, "granted": granted, "channel": channel, "source": source, "at": now_iso()}
    history.append(entry)
    consent["history"] = history[-50:]
    consent[purpose] = granted
    updates: dict[str, Any] = {"consent": consent}
    if purpose == "marketing":
        updates["consent_marketing"] = granted
    if not granted and purpose in ("marketing", "contact"):
        updates["opted_out_at"] = now_iso()
    await table("lead_events", workspace_id).insert({"lead_id": lead_id, "type": "consent.recorded", "payload": entry})
    return await repo.update(lead_id, updates)


async def retention_purge(workspace_id: str, now: datetime | None = None) -> dict[str, int]:
    """Delete raw payloads and erase idle unconverted leads past retention."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    raw_cutoff = (now - timedelta(days=settings.RETENTION_RAW_DAYS)).isoformat()
    lead_cutoff = (now - timedelta(days=settings.RETENTION_LEAD_DAYS)).isoformat()

    raw = table("raw_lead_records", workspace_id)
    stale_raw = [r for r in await raw.select(limit=10_000) if (r.get("created_at") or "") < raw_cutoff]
    for r in stale_raw:
        await raw.delete(id=r["id"])

    erased = 0
    repo = get_lead_repository(workspace_id)
    for lead in await repo.list_all(limit=5_000):
        if lead.get("status") == "erased" or lead.get("assigned_broker"):
            continue
        if lead.get("stage") in ("handed_off", "viewing_booked", "closed"):
            continue
        last = lead.get("updated_at") or lead.get("created_at") or ""
        if last and last < lead_cutoff:
            await erase_lead(lead["id"], workspace_id, requested_by="retention", reason="retention_expired")
            erased += 1
    result = {"raw_records_deleted": len(stale_raw), "leads_erased": erased}
    logger.info("retention purge for %s: %s", workspace_id, result)
    return result


async def list_requests(workspace_id: str, limit: int = 100) -> list[Row]:
    return await table("privacy_requests", workspace_id).select(order="created_at", desc=True, limit=limit)


async def _log_request(workspace_id: str, lead_id: str, *, kind: str, requested_by: str | None, status: str, reason: str | None = None) -> Row:
    return await table("privacy_requests", workspace_id).insert(
        {
            "id": new_id(),
            "lead_id": lead_id,
            "kind": kind,
            "status": status,
            "reason": reason,
            "requested_by": requested_by,
            "created_at": now_iso(),
        }
    )
