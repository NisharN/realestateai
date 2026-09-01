"""Workflow templates, message outbox, and listing-refresh suggestions.

Deliberately not a workflow builder. This exposes the fixed set of templates
(what they are, whether they're on, and what they'd do right now) plus the
outputs they produce. There is no endpoint to create a custom workflow graph —
see docs/workflow_builder_validation.md for why all three advisors rejected
that.

The ``/preview`` endpoint is what makes this demoable and trustworthy: it runs
the same pure decision functions the scheduler runs, and shows the broker
exactly what the system *would* do, without sending anything.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.config import get_settings
from app.seed_data import community_median_ppsf
from app.services import workflows as wf
from app.services.listing_refresh import generate_refresh_copy
from app.services.whatsapp import get_outbox
from app.services.workflow_inputs import load_workflow_inputs

logger = logging.getLogger(__name__)
router = APIRouter()

# Outbound-call approvals. In-process for the pilot — voice itself is deferred,
# so this is the gate standing ready rather than a hot path. Moves to a table
# when voice actually ships.
_VOICE_APPROVALS: Dict[str, Dict[str, Any]] = {}


@router.get("/templates")
async def list_templates(
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """The fixed template catalogue and its current thresholds."""
    settings = get_settings()
    ws = wf.WorkflowSettings.from_settings(settings)
    return {
        "builder_enabled": False,
        "note": (
            "Templates are configured per deployment, not built by end users. "
            "See PILOT.md for the rationale."
        ),
        "templates": [
            {
                "id": template.value,
                "label": wf.TEMPLATE_LABELS[template],
                "enabled": template in ws.enabled,
            }
            for template in wf.WorkflowTemplate
        ],
        "settings": {
            "followup_delay_minutes": ws.followup_delay_minutes,
            "viewing_reminder_hours": ws.viewing_reminder_hours,
            "mandate_renewal_lead_days": ws.mandate_renewal_lead_days,
            "listing_stale_days": ws.listing_stale_days,
            "hot_lead_score": ws.hot_lead_score,
        },
        "voice_gate": {
            "outbound_enabled": settings.VOICE_OUTBOUND_ENABLED,
            "requires_human_approval": settings.VOICE_REQUIRE_HUMAN_APPROVAL,
            "note": (
                "No workflow may auto-dial a lead without a human approving "
                "the first call."
            ),
        },
    }


@router.get("/preview")
async def preview_actions(
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Show what the templates would do right now. Sends nothing."""
    settings = get_settings()
    ws = wf.WorkflowSettings.from_settings(settings)
    now = datetime.now(timezone.utc)

    leads, viewings, mandates, listings = await _load_inputs(context)

    actions: List[wf.WorkflowAction] = []
    actions += wf.evaluate_new_lead_followup(leads, now, ws)
    actions += wf.evaluate_viewing_reminders(viewings, now, ws)
    actions += wf.evaluate_post_viewing_nudge(viewings, now, ws)
    actions += wf.evaluate_mandate_renewals(mandates, now, ws)
    actions += wf.evaluate_listing_staleness(listings, now, ws)

    by_template: Dict[str, int] = {}
    for action in actions:
        by_template[action.template.value] = by_template.get(action.template.value, 0) + 1

    return {
        "evaluated_at": now.isoformat(),
        "total_actions": len(actions),
        "by_template": by_template,
        "actions": [a.to_dict() for a in actions],
    }


@router.get("/outbox")
async def list_outbox(
    lead_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Every message the AI sent or would have sent.

    Brokers asked to see transcripts before trusting AI handoff — this is
    where that comes from. In mock mode nothing was actually delivered, and
    each entry says so via its ``status`` ("simulated").
    """
    settings = get_settings()
    messages = get_outbox().list(lead_id=lead_id, limit=limit)
    return {
        "mode": settings.whatsapp_mode,
        "delivered": settings.whatsapp_mode == "live",
        "count": len(messages),
        "messages": messages,
    }


@router.get("/listing-refresh")
async def listing_refresh_suggestions(
    limit: int = Query(25, ge=1, le=100),
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Stale listings plus ready-to-paste refreshed copy.

    The broker copies this and reposts it herself. This product never posts to
    Bayut, Property Finder, or Dubizzle on her behalf — automating that would
    risk getting her portal account banned.
    """
    settings = get_settings()
    ws = wf.WorkflowSettings.from_settings(settings)
    now = datetime.now(timezone.utc)

    _, _, _, listings = await _load_inputs(context)
    stale = wf.evaluate_listing_staleness(listings, now, ws)
    medians = community_median_ppsf()
    by_id = {str(l.get("id")): l for l in listings}

    suggestions: List[Dict[str, Any]] = []
    for action in stale[:limit]:
        listing = by_id.get(action.subject_id)
        if not listing:
            continue
        median_ppsf = medians.get(listing.get("area") or "")
        size = listing.get("size_sqft")
        comparable_median = median_ppsf * size if (median_ppsf and size) else None
        copy = generate_refresh_copy(
            listing,
            days_stale=int(action.metadata.get("days_stale", 0)),
            refresh_count=int(listing.get("refresh_count") or 0),
            comparable_median=comparable_median,
        )
        suggestions.append(
            {
                **copy.to_dict(),
                "area": listing.get("area"),
                "price": listing.get("price"),
                "posts_automatically": False,
            }
        )

    return {
        "count": len(suggestions),
        "stale_threshold_days": ws.listing_stale_days,
        "suggestions": suggestions,
    }


@router.post("/voice-calls/request")
async def request_voice_call(
    lead_id: str = Query(..., description="Lead to call"),
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Queue an outbound voice call for human approval — never dial directly.

    Once workflows could trigger calls, the broker's objection sharpened: an
    automated dial fired off a scoring rule can hit a wrong number, a lead
    another agent already closed, or someone who explicitly asked not to be
    called, with nobody watching. So every first outbound call requires a
    human to approve it, and this endpoint is the only way one can be created.
    """
    settings = get_settings()
    if not settings.VOICE_OUTBOUND_ENABLED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "voice_outbound_disabled",
                "message": (
                    "Outbound voice is disabled for this deployment. Real-time "
                    "voice is deferred past the pilot; see PILOT.md."
                ),
            },
        )

    request_id = f"voice-{lead_id}"
    _VOICE_APPROVALS[request_id] = {
        "id": request_id,
        "lead_id": lead_id,
        "status": "pending_approval",
        "requested_by": context.user_id,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "approved_by": None,
        "approved_at": None,
    }
    return _VOICE_APPROVALS[request_id]


@router.get("/voice-calls")
async def list_voice_calls(
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Pending and approved outbound call requests, plus the kill switch state."""
    settings = get_settings()
    return {
        "outbound_enabled": settings.VOICE_OUTBOUND_ENABLED,
        "requires_human_approval": settings.VOICE_REQUIRE_HUMAN_APPROVAL,
        "requests": list(_VOICE_APPROVALS.values()),
    }


@router.post("/voice-calls/{request_id}/approve")
async def approve_voice_call(
    request_id: str,
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """A human signs off on a specific call. Owners and admins only."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    record = _VOICE_APPROVALS.get(request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Call request not found")
    record["status"] = "approved"
    record["approved_by"] = context.user_id
    record["approved_at"] = datetime.now(timezone.utc).isoformat()
    return record


@router.post("/voice-calls/kill-switch")
async def voice_kill_switch(
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Cancel every pending call request immediately.

    The visible kill switch the broker asked for. Deliberately cheap to hit
    and available to any role — in a "stop calling my clients" moment nobody
    should be blocked on permissions.
    """
    cancelled = 0
    for record in _VOICE_APPROVALS.values():
        if record["status"] in {"pending_approval", "approved"}:
            record["status"] = "cancelled"
            cancelled += 1
    return {"cancelled": cancelled, "outbound_enabled": False}


@router.post("/run")
async def run_now(
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Manually trigger a workflow pass. Owners and admins only."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    try:
        from app.worker import _run_workflow_templates_async

        return await _run_workflow_templates_async()
    except Exception as exc:
        logger.error("Manual workflow run failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


async def _load_inputs(context: RequestContext):
    """Load workflow inputs via the shared loader the worker also uses."""
    return await load_workflow_inputs(context.workspace_id)
