"""Broker workspace: Today view, pipeline, lead detail/edits, handoff actions, follow-ups."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.database import get_lead_repository
from app.modules.conversation.repository import ConversationRepo
from app.modules.handoff import followups, viewings
from app.modules.handoff.service import accept_handoff, decline_handoff, reassign_stale
from app.modules.ingestion import events as lead_events
from app.modules.leads.stages import PIPELINE_STAGES, lead_stage
from app.modules.store import new_id, now_iso, table

router = APIRouter()

MIRROR_ONLY = ("updated_at", "broker_edited_fields", "budget_min", "budget_max", "property_type")
BROKER_EDITABLE = ("purpose", "budget_min_aed", "budget_max_aed", "budget_period", "community_ids", "property_types", "bedrooms_min", "timeline", "payment", "stage", "notes", "first_name", "last_name", "email")


def _broker_scope(context: RequestContext, broker_id: str | None) -> str | None:
    """Agents only see their own leads; owners/admins may pass any broker or none (all)."""
    if context.role == WorkspaceRole.AGENT:
        if not context.broker_id:
            raise HTTPException(status_code=403, detail={"code": "no_broker_profile", "message": "This account is not linked to a broker profile"})
        return context.broker_id
    return broker_id


def _visible(context: RequestContext, lead: dict[str, Any]) -> bool:
    return context.role != WorkspaceRole.AGENT or (context.broker_id is not None and lead.get("assigned_broker") == context.broker_id)


_lead_stage = lead_stage


def _summary(lead: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": lead["id"],
        "name": f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip() or "Unknown",
        "phone": lead.get("phone") or lead.get("phone_e164"),
        "language": lead.get("preferred_language") or lead.get("language") or "en",
        "score": lead.get("score") or lead.get("intent_score") or 0,
        "band": lead.get("band"),
        "stage": _lead_stage(lead),
        "purpose": lead.get("purpose"),
        "budget_min_aed": lead.get("budget_min_aed") or lead.get("budget_min"),
        "budget_max_aed": lead.get("budget_max_aed") or lead.get("budget_max"),
        "budget_period": lead.get("budget_period"),
        "areas": lead.get("area_preference") or [],
        "property_type": lead.get("property_type"),
        "timeline": lead.get("timeline"),
        "source": lead.get("source"),
        "assigned_broker": lead.get("assigned_broker"),
        "created_at": lead.get("created_at"),
        "updated_at": lead.get("updated_at"),
    }


@router.get("/today")
async def broker_today(broker_id: str | None = None, context: RequestContext = Depends(get_request_context)):
    ws = context.workspace_id
    scope = _broker_scope(context, broker_id)
    handoffs = table("handoffs", ws)
    repo = get_lead_repository(ws)
    filters: dict[str, Any] = {"broker_id": scope} if scope else {}

    pending = await handoffs.select(status="pending", order="created_at", desc=True, limit=50, **filters)
    accepted = await handoffs.select(status="accepted", order="accepted_at", desc=True, limit=50, **filters)
    escalated = await handoffs.select(status="escalated", order="created_at", desc=True, limit=20) if not scope else []
    today = datetime.now(timezone.utc).date().isoformat()

    async def with_lead(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for h in rows:
            lead = await repo.get_by_id(h["lead_id"])
            out.append({"handoff": _handoff_public(h), "lead": _summary(lead) if lead else {"id": h["lead_id"]}})
        return out

    hot = await repo.list_hot(min_score=70, limit=200, assigned_broker_id=scope)
    upcoming = await viewings.list_viewings(ws, broker_id=scope, statuses=["requested", "confirmed"], limit=50)

    return {
        "date": today,
        "broker_id": scope,
        "counts": {
            "new_handoffs": len(pending),
            "accepted": len(accepted),
            "hot_leads": len(hot),
            "viewings": len(upcoming),
            "followups_due": len([f for f in await followups.pending_for_broker(ws, scope, limit=200, include_unassigned=context.role != WorkspaceRole.AGENT) if f["due_at"][:10] <= today]),
            "escalated": len(escalated),
        },
        "new_handoffs": await with_lead(pending),
        "accepted_handoffs": await with_lead(accepted[:20]),
        "hot_leads": [_summary(l) for l in hot[:20]],
        "viewings": upcoming,
        "followups": await followups.pending_for_broker(ws, scope, limit=20, include_unassigned=context.role != WorkspaceRole.AGENT),
        "escalated": await with_lead(escalated),
    }


@router.get("/pipeline")
async def pipeline(broker_id: str | None = None, context: RequestContext = Depends(get_request_context)):
    scope = _broker_scope(context, broker_id)
    repo = get_lead_repository(context.workspace_id)
    leads = await repo.list_all(limit=1000, assigned_broker_id=scope)
    totals = await repo.count_by_stage(assigned_broker_id=scope)
    columns: dict[str, list[dict[str, Any]]] = {s: [] for s in PIPELINE_STAGES}
    for l in leads:
        columns[_lead_stage(l)].append(_summary(l))
    for rows in columns.values():
        rows.sort(key=lambda s: -(s["score"] or 0))
    return {
        "broker_id": scope,
        "total": sum(totals.values()),
        "stages": [{"stage": s, "count": totals.get(s, len(columns[s])), "leads": columns[s][:100]} for s in PIPELINE_STAGES],
    }


@router.get("/leads/{lead_id}")
async def lead_detail(lead_id: str, context: RequestContext = Depends(get_request_context)):
    ws = context.workspace_id
    lead = await get_lead_repository(ws).get_by_id(lead_id)
    if not lead or not _visible(context, lead):
        raise HTTPException(404, detail={"code": "lead_not_found", "message": "Lead not found"})
    handoff = await table("handoffs", ws).get(lead_id=lead_id, status__in=["pending", "accepted", "escalated"])
    convo = ConversationRepo(ws)
    messages = await convo.history(lead_id, limit=100)
    events = await table("lead_events", ws).select(lead_id=lead_id, order="created_at", limit=100)
    changes = await table("lead_change_log", ws).select(lead_id=lead_id, order="at", limit=100)
    sources = await table("lead_sources", ws).select(lead_id=lead_id, limit=50)
    fups = await table("followups", ws).select(lead_id=lead_id, order="due_at", limit=20)
    lead_viewings = await viewings.list_viewings(ws, lead_id=lead_id, limit=20)
    timeline = sorted(
        [
            *({"at": e.get("created_at"), "kind": "event", "type": e.get("type"), "payload": e.get("payload")} for e in events),
            *({"at": c.get("at"), "kind": "change", "field": c.get("field"), "old": c.get("old_value"), "new": c.get("new_value"), "by": c.get("changed_by")} for c in changes),
            *({"at": m.get("created_at"), "kind": "message", "role": m.get("role"), "text": m.get("text"), "channel": m.get("channel")} for m in messages),
        ],
        key=lambda t: t["at"] or "",
    )
    return {
        "lead": {**_summary(lead), **{k: lead.get(k) for k in ("email", "payment", "bedrooms_min", "score_reasons", "consent", "notes", "initial_message", "community_ids", "property_types")}},
        "brief": (handoff or {}).get("brief"),
        "handoff": _handoff_public(handoff) if handoff else None,
        "sources": sources,
        "followups": fups,
        "viewings": lead_viewings,
        "timeline": timeline,
    }


class LeadPatch(BaseModel):
    purpose: str | None = None
    budget_min_aed: float | None = None
    budget_max_aed: float | None = None
    budget_period: str | None = None
    community_ids: list[str] | None = None
    property_types: list[str] | None = None
    bedrooms_min: int | None = None
    timeline: str | None = None
    payment: str | None = None
    stage: Literal["new", "qualifying", "qualified", "handed_off", "viewing_booked", "offer", "closed", "lost"] | None = None
    notes: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None


@router.patch("/leads/{lead_id}")
async def patch_lead(lead_id: str, body: LeadPatch, context: RequestContext = Depends(get_request_context)):
    ws = context.workspace_id
    repo = get_lead_repository(ws)
    lead = await repo.get_by_id(lead_id)
    if not lead or not _visible(context, lead):
        raise HTTPException(404, detail={"code": "lead_not_found", "message": "Lead not found"})
    updates = {k: v for k, v in body.model_dump().items() if v is not None and k in BROKER_EDITABLE}
    if not updates:
        return {"lead": _summary(lead), "changed": []}
    if "budget_min_aed" in updates:
        updates["budget_min"] = updates["budget_min_aed"]
    if "budget_max_aed" in updates:
        updates["budget_max"] = updates["budget_max_aed"]
    if "property_types" in updates and updates["property_types"]:
        updates["property_type"] = updates["property_types"][0]
    confirmed = sorted(set(lead.get("buyer_confirmed_fields") or []) | {k for k in updates if k in ("purpose", "budget_min_aed", "budget_max_aed", "community_ids", "property_types", "timeline", "payment")})
    updates["broker_edited_fields"] = confirmed
    updates["updated_at"] = now_iso()
    saved = await repo.update(lead_id, updates)
    log = table("lead_change_log", ws)
    for field, value in updates.items():
        if field in MIRROR_ONLY:
            continue
        await log.insert({"id": new_id(), "lead_id": lead_id, "field": field, "old_value": lead.get(field), "new_value": value, "changed_by": "broker", "user_id": context.user_id, "at": now_iso()})
    await lead_events.emit(lead_id, "lead.updated", {"by": "broker", "fields": sorted(k for k in updates if k not in MIRROR_ONLY)}, workspace_id=ws)
    return {"lead": _summary(saved), "changed": sorted(k for k in updates if k not in MIRROR_ONLY)}


class HandoffAction(BaseModel):
    broker_id: str | None = None
    reason: str | None = Field(None, max_length=500)


def _handoff_public(h: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "lead_id", "broker_id", "broker_name", "status", "reason", "score", "band", "language", "slot_text", "created_at", "reassign_after", "accepted_at", "reassigned_count", "routing_reasons", "decline_reason")
    return {k: h.get(k) for k in keys}


def _acting_broker(context: RequestContext, requested: str | None) -> str:
    if context.role == WorkspaceRole.AGENT:
        if not context.broker_id:
            raise HTTPException(403, detail={"code": "no_broker_profile", "message": "Your account has no broker profile"})
        return context.broker_id
    if not requested:
        raise HTTPException(400, detail={"code": "broker_id_required", "message": "broker_id is required for admins"})
    return requested


@router.post("/handoffs/{handoff_id}/accept")
async def accept(handoff_id: str, body: HandoffAction | None = None, context: RequestContext = Depends(get_request_context)):
    broker_id = _acting_broker(context, body.broker_id if body else None)
    row = await accept_handoff(handoff_id, broker_id, context.workspace_id)
    if not row:
        raise HTTPException(409, detail={"code": "handoff_not_acceptable", "message": "Handoff is not pending for this broker"})
    await lead_events.emit(row["lead_id"], "handoff.accepted", {"handoff_id": handoff_id, "broker_id": broker_id}, workspace_id=context.workspace_id)
    await followups.cancel_followups(row["lead_id"], workspace_id=context.workspace_id, reason="broker_accepted")
    return _handoff_public(row)


@router.post("/handoffs/{handoff_id}/decline")
async def decline(handoff_id: str, body: HandoffAction | None = None, context: RequestContext = Depends(get_request_context)):
    broker_id = _acting_broker(context, body.broker_id if body else None)
    row = await decline_handoff(handoff_id, broker_id, context.workspace_id, reason=body.reason if body else None)
    if not row:
        raise HTTPException(409, detail={"code": "handoff_not_declinable", "message": "Handoff is not pending for this broker"})
    return _handoff_public(row)


class ViewingCreate(BaseModel):
    lead_id: str
    property_id: str | None = None
    starts_at: datetime
    broker_id: str | None = None
    notes: str | None = Field(None, max_length=1000)
    confirmed: bool = True


class ViewingUpdate(BaseModel):
    status: viewings.ViewingStatus | None = None
    starts_at: datetime | None = None
    broker_id: str | None = None
    notes: str | None = Field(None, max_length=1000)


@router.get("/viewings")
async def viewings_index(
    broker_id: str | None = None,
    lead_id: str | None = None,
    status: str | None = None,
    context: RequestContext = Depends(get_request_context),
):
    scope = _broker_scope(context, broker_id)
    statuses = [s for s in (status or "").split(",") if s in viewings.STATUSES] or None
    return await viewings.list_viewings(context.workspace_id, lead_id=lead_id, broker_id=scope, statuses=statuses)


@router.post("/viewings", status_code=201)
async def create_viewing(body: ViewingCreate, context: RequestContext = Depends(get_request_context)):
    ws = context.workspace_id
    lead = await get_lead_repository(ws).get_by_id(body.lead_id)
    if not lead or not _visible(context, lead):
        raise HTTPException(404, detail={"code": "lead_not_found", "message": "Lead not found"})
    broker_id = context.broker_id if context.role == WorkspaceRole.AGENT else (body.broker_id or lead.get("assigned_broker"))
    return await viewings.request_viewing(
        ws,
        lead_id=body.lead_id,
        property_id=body.property_id,
        starts_at=body.starts_at,
        broker_id=broker_id,
        source="broker",
        notes=body.notes,
        status="confirmed" if body.confirmed else "requested",
    )


@router.patch("/viewings/{viewing_id}")
async def patch_viewing(viewing_id: str, body: ViewingUpdate, context: RequestContext = Depends(get_request_context)):
    ws = context.workspace_id
    row = await table("viewings", ws).get(id=viewing_id)
    if not row:
        raise HTTPException(404, detail={"code": "viewing_not_found", "message": "Viewing not found"})
    # Access follows the lead's current assignment, not the broker recorded on the
    # viewing, so a reassigned lead's former agent loses access and agents can never
    # move a viewing into another broker's queue.
    lead = await get_lead_repository(ws).get_by_id(row["lead_id"])
    if not lead or not _visible(context, lead):
        raise HTTPException(404, detail={"code": "viewing_not_found", "message": "Viewing not found"})
    if context.role == WorkspaceRole.AGENT:
        broker_id = context.broker_id if row.get("broker_id") != context.broker_id else None
    else:
        broker_id = body.broker_id
    try:
        saved = await viewings.update_viewing(
            ws,
            viewing_id,
            status=body.status,
            starts_at=body.starts_at,
            broker_id=broker_id,
            notes=body.notes,
            actor=context.user_id,
        )
    except viewings.InvalidTransition as exc:
        raise HTTPException(409, detail={"code": "invalid_transition", "message": str(exc)})
    return saved


@router.post("/handoffs/reassign-stale")
async def run_reassignment(context: RequestContext = Depends(get_request_context)):
    """Manual trigger for the 15-minute reassignment timer (Celery beat calls the same function)."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    changed = await reassign_stale(context.workspace_id)
    return {"reassigned": len([c for c in changed if c.get("status") == "pending"]), "escalated": len([c for c in changed if c.get("status") == "escalated"])}


@router.get("/handoffs")
async def list_handoffs(status: str | None = None, broker_id: str | None = None, limit: int = 50, context: RequestContext = Depends(get_request_context)):
    scope = _broker_scope(context, broker_id)
    filters: dict[str, Any] = {}
    if scope:
        filters["broker_id"] = scope
    if status:
        filters["status"] = status
    rows = await table("handoffs", context.workspace_id).select(order="created_at", desc=True, limit=min(limit, 200), **filters)
    return [_handoff_public(h) for h in rows]


@router.get("/followups")
async def list_followups(broker_id: str | None = None, limit: int = 50, context: RequestContext = Depends(get_request_context)):
    return await followups.pending_for_broker(context.workspace_id, _broker_scope(context, broker_id), limit=min(limit, 200), include_unassigned=context.role != WorkspaceRole.AGENT)


@router.post("/followups/send-due")
async def send_due_followups(context: RequestContext = Depends(get_request_context)):
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    sent = await followups.send_due(context.workspace_id)
    return {"sent": len([s for s in sent if s.get("status") == "sent"]), "failed": len([s for s in sent if s.get("status") == "failed"])}
