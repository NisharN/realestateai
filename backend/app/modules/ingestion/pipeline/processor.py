"""Runs a landed raw record through stages 1–6 and records the outcome.

The same function is used by the API (small batches, inline) and by Celery
(background). Every step saves the record status first, so a crash leaves the
record resumable and never doubles a lead: match+merge is idempotent on
phone/email and the raw record's ``lead_id``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import get_lead_repository
from app.modules.geo.communities import get_community
from app.modules.ingestion import events
from app.modules.ingestion.field_maps import approved_field_map
from app.modules.ingestion.models import CanonicalLead, MergeResult, PipelineOutcome
from app.modules.ingestion.pipeline.stages import clean_record, map_record, validate_record
from app.modules.store import Row, new_id, now_iso, table

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
NAME_MATCH_WINDOW_DAYS = 30

# Contact fields are owned by the CRM; buyer facts beat imports (§6.5).
CRM_OWNED = ("first_name", "last_name", "phone", "email")


async def process_record(raw_id: str, *, workspace_id: str) -> PipelineOutcome:
    raw = table("raw_lead_records", workspace_id)
    record = await raw.get(id=raw_id)
    if not record:
        return PipelineOutcome(raw_record_id=raw_id, status="error", reasons=["not_found"])
    if record.get("status") in ("published", "review"):
        return PipelineOutcome(raw_record_id=raw_id, status=record["status"], lead_id=record.get("lead_id"))

    async def set_status(status: str, **extra: Any) -> None:
        await raw.update({"status": status, "updated_at": now_iso(), **extra}, id=raw_id)

    try:
        field_map = await approved_field_map(record["connector_id"], workspace_id) if record.get("connector_id") else {}
        payload = dict(record["payload"])
        if record.get("source_hint"):
            payload.setdefault("__source_hint", record["source_hint"])
        draft = map_record(payload, field_map)
        if not draft.external_id and record.get("external_id"):
            draft.external_id = str(record["external_id"])
        await set_status("mapped")

        cleaned = clean_record(draft)
        await set_status("cleaned")

        suppression = await _suppression(workspace_id)
        validation = validate_record(cleaned, suppression)
        if not validation.ok:
            await _to_review(record, workspace_id, ", ".join(validation.reasons), validation.suggested_fix, cleaned)
            return PipelineOutcome(raw_record_id=raw_id, status="review", reasons=validation.reasons)
        await set_status("validated")

        merge = await match_and_merge(cleaned, record, workspace_id)
        if merge.suppressed:
            await _to_review(record, workspace_id, "suppressed", {"lead_id": merge.lead_id}, cleaned)
            return PipelineOutcome(raw_record_id=raw_id, status="review", lead_id=merge.lead_id, reasons=["suppressed"])
        await set_status("merged", lead_id=merge.lead_id)

        await enrich(cleaned, merge, workspace_id)
        await set_status("enriched", lead_id=merge.lead_id)

        await events.emit(
            merge.lead_id,
            "lead.created" if merge.created else "lead.updated",
            {"raw_record_id": raw_id, "source": cleaned.source, "changed_fields": merge.changed_fields, "matched_by": merge.matched_by},
            workspace_id=workspace_id,
        )
        await set_status("published", lead_id=merge.lead_id, error=None)
        if merge.needs_review:
            await _to_review(record, workspace_id, "possible_duplicate_name_match", {"lead_id": merge.lead_id}, cleaned, keep_status=True)
        return PipelineOutcome(raw_record_id=raw_id, status="published", lead_id=merge.lead_id, created=merge.created, reasons=cleaned.warnings)
    except Exception as exc:
        attempts = int(record.get("attempts") or 0) + 1
        logger.exception("pipeline failed for raw record %s", raw_id)
        if attempts >= MAX_ATTEMPTS:
            await set_status("error", attempts=attempts, error=str(exc))
            await _to_review(record, workspace_id, f"error: {exc}", {}, None)
            return PipelineOutcome(raw_record_id=raw_id, status="review", reasons=[str(exc)])
        await set_status("error", attempts=attempts, error=str(exc))
        return PipelineOutcome(raw_record_id=raw_id, status="error", reasons=[str(exc)])


async def process_many(raw_ids: list[str], *, workspace_id: str) -> list[PipelineOutcome]:
    return [await process_record(i, workspace_id=workspace_id) for i in raw_ids]


async def retry_errors(workspace_id: str, limit: int = 100) -> list[PipelineOutcome]:
    rows = await table("raw_lead_records", workspace_id).select(status="error", limit=limit)
    return await process_many([r["id"] for r in rows], workspace_id=workspace_id)


async def process_stranded(workspace_id: str, *, older_than_seconds: int = 300, limit: int = 500) -> list[PipelineOutcome]:
    """Pick up records that landed but were never dispatched (worker/broker outage between land and enqueue)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
    rows = await table("raw_lead_records", workspace_id).select(status="landed", order="received_at", limit=limit)
    return await process_many([r["id"] for r in rows if (r.get("received_at") or "") <= cutoff], workspace_id=workspace_id)


# --------------------------------------------------------- 4 Match+merge


async def match_and_merge(lead: CanonicalLead, record: Row, workspace_id: str) -> MergeResult:
    repo = get_lead_repository(workspace_id)
    existing: Row | None = None
    matched_by: str = "none"
    needs_review = False

    if record.get("lead_id"):
        existing = await repo.get_by_id(record["lead_id"])
        matched_by = "phone"
    if not existing and lead.phone_e164:
        existing = await repo.get_by_phone(lead.phone_e164)
        matched_by = "phone" if existing else matched_by
    if not existing and lead.email:
        existing = await repo.get_by_email(lead.email)
        matched_by = "email" if existing else matched_by
    if not existing and lead.first_name and lead.last_name:
        existing = await _name_match(repo, lead)
        if existing:
            matched_by, needs_review = "name_recent", True

    columns = lead_columns(lead)
    if existing:
        if existing.get("opted_out_at") or "opted_out" in (existing.get("stage"), existing.get("status")):
            return MergeResult(lead_id=existing["id"], created=False, matched_by=matched_by, suppressed=True, changed_fields=[])  # type: ignore[arg-type]
        updates, changed = merge_updates(existing, columns)
        if updates:
            updates["updated_at"] = now_iso()
            await repo.update(existing["id"], updates)
            await _log_changes(existing["id"], existing, updates, workspace_id, record.get("id"))
        return MergeResult(lead_id=existing["id"], created=False, matched_by=matched_by, needs_review=needs_review, changed_fields=changed)  # type: ignore[arg-type]

    columns.update({"status": "new", "stage": "new", "intent_score": 0, "score": 0, "created_at": now_iso(), "updated_at": now_iso()})
    created = await repo.create(columns)
    await _log_changes(created["id"], {}, columns, workspace_id, record.get("id"))
    return MergeResult(lead_id=created["id"], created=True, matched_by="none", changed_fields=sorted(columns))


def lead_columns(lead: CanonicalLead) -> dict[str, Any]:
    """Both the legacy dashboard columns and the §12 columns."""
    cols: dict[str, Any] = {
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "phone": lead.phone_e164,
        "phone_e164": lead.phone_e164,
        "email": lead.email,
        "source": lead.source,
        "preferred_language": lead.language,
        "language": lead.language,
        "purpose": lead.purpose,
        "budget_min": lead.budget_min_aed,
        "budget_max": lead.budget_max_aed,
        "budget_min_aed": lead.budget_min_aed,
        "budget_max_aed": lead.budget_max_aed,
        "budget_period": lead.budget_period,
        "community_ids": lead.community_ids or None,
        "area_preference": [c.name_en if (c := get_community(i)) else i for i in lead.community_ids] or None,
        "property_type": lead.property_type,
        "property_types": [lead.property_type] if lead.property_type else None,
        "bedrooms_min": lead.bedrooms,
        "timeline": lead.timeline,
        "payment": lead.payment,
        "consent": lead.consent or None,
        "crm_external_id": lead.external_id if lead.source == "crm" else None,
        "extra": lead.extra or None,
        "initial_message": lead.message,
    }
    return {k: v for k, v in cols.items() if v is not None}


def merge_updates(existing: Row, incoming: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Never overwrite with null; CRM owns contact fields; buyer-confirmed and broker-edited facts win."""
    buyer_fields = set(existing.get("buyer_confirmed_fields") or []) | set(existing.get("broker_edited_fields") or [])
    updates: dict[str, Any] = {}
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        current = existing.get(key)
        if current == value:
            continue
        if key in buyer_fields:
            continue
        if key in CRM_OWNED and current not in (None, "") and existing.get("source") == "crm" and incoming.get("source") != "crm":
            continue
        if key in ("created_at", "status", "stage", "intent_score", "score"):
            continue
        if isinstance(current, list) and isinstance(value, list):
            merged = list(dict.fromkeys([*current, *value]))
            if merged != current:
                updates[key] = merged
            continue
        updates[key] = value
    return updates, sorted(updates)


async def _name_match(repo: Any, lead: CanonicalLead) -> Row | None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=NAME_MATCH_WINDOW_DAYS)).isoformat()
    target = f"{lead.first_name} {lead.last_name}".strip().lower()
    for row in await repo.list_all(limit=500):
        name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip().lower()
        if name == target and (row.get("created_at") or "") >= cutoff:
            return row
    return None


async def _log_changes(lead_id: str, before: Row, updates: dict[str, Any], workspace_id: str, raw_id: str | None) -> None:
    log = table("lead_change_log", workspace_id)
    for field, value in updates.items():
        if field in ("updated_at", "created_at"):
            continue
        await log.insert(
            {
                "id": new_id(),
                "lead_id": lead_id,
                "field": field,
                "old_value": before.get(field),
                "new_value": value,
                "changed_by": "import",
                "raw_record_id": raw_id,
                "at": now_iso(),
            }
        )


# ----------------------------------------------------------- 5 Enrich


async def enrich(lead: CanonicalLead, merge: MergeResult, workspace_id: str) -> None:
    sources = table("lead_sources", workspace_id)
    already = lead.external_id and await sources.get(lead_id=merge.lead_id, source=lead.source, external_id=lead.external_id)
    if not already:
        await sources.insert(
            {
                "id": new_id(),
                "lead_id": merge.lead_id,
                "raw_record_id": None,
                "source": lead.source,
                "external_id": lead.external_id,
                "listing_ref": lead.listing_ref,
                "first_seen_at": now_iso(),
            }
        )
    if lead.listing_ref:
        prop = await table("properties", workspace_id).get(source_ref=lead.listing_ref) or await table("properties", workspace_id).get(id=lead.listing_ref)
        if prop:
            await get_lead_repository(workspace_id).update(merge.lead_id, {"interested_property_id": prop["id"]})


# ---------------------------------------------------------- review queue


async def _to_review(record: Row, workspace_id: str, reason: str, fix: dict[str, Any], cleaned: CanonicalLead | None, *, keep_status: bool = False) -> None:
    await table("review_queue", workspace_id).insert(
        {
            "id": new_id(),
            "raw_record_id": record["id"],
            "reason": reason,
            "status": "open",
            "suggested_fix": fix,
            "draft": cleaned.model_dump(mode="json") if cleaned else None,
            "resolved_by": None,
            "resolved_at": None,
            "created_at": now_iso(),
        }
    )
    if not keep_status:
        await table("raw_lead_records", workspace_id).update({"status": "review", "error": reason, "updated_at": now_iso()}, id=record["id"])


async def _suppression(workspace_id: str) -> set[str]:
    rows = await table("suppression_list", workspace_id).select(limit=10_000)
    out: set[str] = set()
    for r in rows:
        if r.get("phone"):
            out.add(str(r["phone"]))
        if r.get("email"):
            out.add(str(r["email"]).strip().lower())
    return out


async def suppress_contact(workspace_id: str, *, phone: str | None, email: str | None, reason: str) -> None:
    """Add a buyer's contact points to the suppression list (idempotent)."""
    sup = table("suppression_list", workspace_id)
    email = email.strip().lower() if email else None
    if phone and not await sup.get(phone=phone):
        await sup.insert({"id": new_id(), "phone": phone, "email": None, "reason": reason, "created_at": now_iso()})
    if email and not await sup.get(email=email):
        await sup.insert({"id": new_id(), "phone": None, "email": email, "reason": reason, "created_at": now_iso()})


async def resolve_review(item_id: str, *, workspace_id: str, fixed_payload: dict[str, Any] | None, action: str, user_id: str | None) -> PipelineOutcome | None:
    """Admin fixes the payload and re-runs, or discards."""
    rq = table("review_queue", workspace_id)
    item = await rq.get(id=item_id)
    if not item or item.get("resolved_at"):
        return None
    raw = table("raw_lead_records", workspace_id)
    await rq.update({"status": "discarded" if action == "discard" else "resolved", "resolved_by": user_id, "resolved_at": now_iso(), "resolution": action}, id=item_id)
    if action == "discard":
        await raw.update({"status": "error", "error": "discarded", "updated_at": now_iso()}, id=item["raw_record_id"])
        return PipelineOutcome(raw_record_id=item["raw_record_id"], status="error", reasons=["discarded"])
    updates: dict[str, Any] = {"status": "landed", "attempts": 0, "error": None, "updated_at": now_iso()}
    if fixed_payload:
        record = await raw.get(id=item["raw_record_id"])
        updates["payload"] = {**(record or {}).get("payload", {}), **fixed_payload}
    await raw.update(updates, id=item["raw_record_id"])
    return await process_record(item["raw_record_id"], workspace_id=workspace_id)
