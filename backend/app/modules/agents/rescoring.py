"""Behaviour-aware lead re-scoring.

Runs whenever lead data is pulled or pushed into the platform (CRM pull,
portal webhook, Meta Lead Ads, Gmail parsing, routine step). It rebuilds a
scoring state from the lead row, asks ``scorer.qualify`` (Jev when configured,
deterministic rules otherwise), then adjusts for what the lead has actually
*done* since last time:

- replied / had contact recently         -> up
- viewing requested / confirmed / done   -> up
- went quiet after a hot band            -> down (decays with silence)
- viewing no-show or cancelled           -> down
- opted out / lost                       -> floor at cold

Every change is appended to ``lead_score_history`` so brokers can see why a
lead moved, and a ``lead.scored`` event is emitted for automations.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.database import get_lead_repository
from app.modules.agents import scorer
from app.modules.conversation.state import ConversationState
from app.modules.ingestion import events
from app.modules.leads.stages import lead_stage
from app.modules.store import Row, new_id, now_iso, table

logger = logging.getLogger(__name__)

HISTORY_TABLE = "lead_score_history"
MAX_BATCH = 500


def _hours_since(ts: Any) -> float | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)


_TIMELINE_TO_SCORER = {"immediate": "asap", "1_3_months": "3_months", "3_6_months": "6_months", "6_plus_months": "later", "browsing": "later"}
_PAYMENT_TO_SCORER = {"mortgage": "mortgage_not_started", "payment_plan": "mortgage_not_started"}


def state_from_lead(lead: Row) -> ConversationState:
    """A scoring-only ConversationState built from CRM/portal columns."""
    st = ConversationState(lead_id=str(lead.get("id") or new_id()), source=lead.get("source"))
    budget_max, budget_min = lead.get("budget_max_aed"), lead.get("budget_min_aed")
    if budget_max or budget_min:
        st.set_slot("budget", {"min_aed": budget_min, "max_aed": budget_max}, source="import")
    for col, slot in (("purpose", "purpose"), ("timeline", "timeline"), ("payment", "payment"), ("property_type", "property_type"), ("bedrooms", "bedrooms")):
        value = lead.get(col)
        if value in (None, "", []):
            continue
        if slot == "timeline":
            value = _TIMELINE_TO_SCORER.get(str(value), value)
        elif slot == "payment":
            value = _PAYMENT_TO_SCORER.get(str(value), value)
        st.set_slot(slot, value, source="import")
    area = lead.get("area_preference") or lead.get("areas")
    if area:
        st.set_slot("area", area if isinstance(area, list) else [area], source="import")
    if lead.get("viewing_requested") or lead_stage(lead) in ("viewing", "viewing_booked"):
        st.set_slot("viewing_requested", True, source="import")
    if lead.get("language") in ("en", "ar", "mixed"):
        st.language = lead["language"]  # type: ignore[assignment]
    st.answers = sum(1 for k in ("purpose", "budget_max_aed", "timeline", "payment", "area_preference", "property_type") if lead.get(k) not in (None, "", []))
    st.turn = int(lead.get("message_count") or lead.get("turns") or 0)
    return st


def behaviour_adjustment(lead: Row, viewings: list[Row]) -> tuple[int, list[str]]:
    """Points to add/subtract for observed behaviour, with human-readable reasons."""
    delta = 0
    reasons: list[str] = []
    stage = lead_stage(lead)
    if stage in ("lost", "closed", "opted_out"):
        return -100, [f"stage {stage}"]

    contact_age = _hours_since(lead.get("last_contact_at") or lead.get("last_message_at"))
    if contact_age is not None:
        if contact_age <= 24:
            delta += 8
            reasons.append("active in the last 24h")
        elif contact_age <= 72:
            delta += 3
            reasons.append("contact within 3 days")
        elif contact_age > 24 * 14:
            delta -= 15
            reasons.append("silent for 2+ weeks")
        elif contact_age > 24 * 7:
            delta -= 8
            reasons.append("silent for a week")

    inbound = int(lead.get("inbound_messages") or 0)
    if inbound >= 3:
        delta += 5
        reasons.append(f"{inbound} replies")

    statuses = [str(v.get("status") or "") for v in viewings]
    if "done" in statuses or "completed" in statuses:
        delta += 15
        reasons.append("attended a viewing")
    elif "confirmed" in statuses:
        delta += 10
        reasons.append("viewing confirmed")
    elif "booked" in statuses or "requested" in statuses:
        delta += 6
        reasons.append("viewing booked")
    if "no_show" in statuses:
        delta -= 12
        reasons.append("viewing no-show")
    if "cancelled" in statuses:
        delta -= 6
        reasons.append("viewing cancelled")

    if lead.get("unsubscribed") or lead.get("do_not_contact"):
        delta -= 30
        reasons.append("asked not to be contacted")
    return delta, reasons


async def rescore_lead(lead: Row, *, workspace_id: str, trigger: str, recent_messages: list[str] | None = None) -> dict[str, Any]:
    """Re-score one lead, persist the change and emit ``lead.scored``. Never raises."""
    repo = get_lead_repository(workspace_id)
    lead_id = str(lead["id"])
    try:
        viewings = await table("viewings", workspace_id).select(limit=20, lead_id=lead_id)
    except Exception:  # noqa: BLE001
        viewings = []
    fallbacks: list[str] = []
    st = state_from_lead(lead)
    msgs = recent_messages or [m for m in (lead.get("last_message"), lead.get("message")) if m]
    qual = await scorer.qualify(st, recent_messages=msgs, fallbacks=fallbacks)
    delta, why = behaviour_adjustment(lead, viewings)
    score = max(0, min(100, qual.score + delta))
    band = scorer.band_for(score)
    reasons = (qual.reasons + [f"behaviour: {r}" for r in why])[:8]

    previous = int(lead.get("score") or 0)
    prev_band = (lead.get("band") or "").lower() or None
    changed = score != previous or band != prev_band
    if changed:
        await repo.update(lead_id, {"score": score, "band": band, "score_reasons": reasons, "scored_at": now_iso()})
    await table(HISTORY_TABLE, workspace_id).insert(
        {
            "id": new_id(),
            "lead_id": lead_id,
            "score": score,
            "previous_score": previous,
            "delta": score - previous,
            "band": band,
            "previous_band": prev_band,
            "provider": qual.provider,
            "behaviour_delta": delta,
            "reasons": reasons,
            "trigger": trigger,
            "created_at": now_iso(),
        }
    )
    if changed:
        try:
            await events.emit(lead_id, "lead.scored", {"score": score, "band": band, "previous_score": previous, "provider": qual.provider, "trigger": trigger}, workspace_id=workspace_id, lead={**lead, "score": score, "band": band})
        except Exception:  # noqa: BLE001
            logger.warning("lead.scored emit failed for %s", lead_id)
    return {"lead_id": lead_id, "score": score, "previous_score": previous, "band": band, "previous_band": prev_band, "delta": score - previous, "provider": qual.provider, "changed": changed}


async def rescore_leads(lead_ids: list[str], *, workspace_id: str, trigger: str) -> dict[str, Any]:
    repo = get_lead_repository(workspace_id)
    out = {"rescored": 0, "improved": 0, "reduced": 0, "unchanged": 0, "jev": 0, "rules": 0, "errors": 0}
    for lid in dict.fromkeys(lead_ids[:MAX_BATCH]):
        lead = await repo.get_by_id(lid)
        if not lead:
            continue
        try:
            r = await rescore_lead(lead, workspace_id=workspace_id, trigger=trigger)
        except Exception:
            logger.exception("rescore failed for %s", lid)
            out["errors"] += 1
            continue
        out["rescored"] += 1
        out["jev" if r["provider"] == "jev" else "rules"] += 1
        out["improved" if r["delta"] > 0 else "reduced" if r["delta"] < 0 else "unchanged"] += 1
    return out


async def history(lead_id: str, *, workspace_id: str, limit: int = 20) -> list[Row]:
    return await table(HISTORY_TABLE, workspace_id).select(order="created_at", desc=True, limit=limit, lead_id=lead_id)
