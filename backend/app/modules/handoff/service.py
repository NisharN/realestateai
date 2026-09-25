"""Handoff orchestration: route → persist brief → alert → schedule reassignment."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import get_broker_repository, get_lead_repository
from app.modules.conversation.state import ConversationState
from app.modules.ingestion import events
from app.modules.store import new_id, now_iso, table
from app.services.whatsapp import get_whatsapp_service

from .brief import BrokerBrief, build_brief, polish_brief
from .routing import BrokerProfile, route

logger = logging.getLogger(__name__)

REASSIGN_AFTER_MIN = 15


async def _brokers(workspace_id: str) -> list[BrokerProfile]:
    repo = get_broker_repository(workspace_id)
    rows: list[dict[str, Any]]
    if hasattr(repo, "brokers"):
        rows = list(repo.brokers)
    else:
        try:
            result = repo.table.select("*").eq("workspace_id", workspace_id).eq("is_active", True).execute()
            rows = result.data or []
        except Exception as exc:  # pragma: no cover
            logger.warning("broker list failed: %s", exc)
            rows = []
    return [BrokerProfile.from_row(r) for r in rows]


async def create_handoff(
    state: ConversationState,
    *,
    workspace_id: str,
    reason: str,
    transcript: list[dict[str, str]] | None = None,
    slot_text: str | None = None,
    deadline_s: float = 4.0,
) -> dict[str, Any]:
    """Idempotent per lead: an open handoff is returned rather than duplicated."""
    handoffs = table("handoffs", workspace_id)
    existing = await handoffs.get(lead_id=state.lead_id, status__in=["pending", "accepted"])
    if existing:
        return existing

    lead_repo = get_lead_repository(workspace_id)
    lead = await lead_repo.get_by_id(state.lead_id) or {"id": state.lead_id}

    decision = route(
        await _brokers(workspace_id),
        language=state.language,
        community_ids=list(state.value("community_ids") or []),
    )
    brief = build_brief(state, lead, reason=reason)
    if transcript:
        brief = await polish_brief(brief, transcript, deadline_s=min(deadline_s, 3.0))

    broker = decision.broker
    now = datetime.now(timezone.utc)
    row = {
        "id": new_id(),
        "lead_id": state.lead_id,
        "broker_id": broker.id if broker else None,
        "broker_name": broker.name if broker else None,
        "status": "pending" if broker else "unassigned",
        "reason": reason,
        "routing_reasons": decision.reasons,
        "brief": brief.model_dump(),
        "score": state.score,
        "band": state.band,
        "language": state.language,
        "slot_text": slot_text,
        "created_at": now_iso(),
        "reassign_after": (now + timedelta(minutes=REASSIGN_AFTER_MIN)).isoformat(),
        "accepted_at": None,
        "reassigned_count": 0,
    }
    saved = await handoffs.insert(row)

    if broker:
        try:
            await get_broker_repository(workspace_id).increment_lead_count(broker.id)
            await lead_repo.update(state.lead_id, {"assigned_broker": broker.id, "status": "contacted"})
        except Exception as exc:  # pragma: no cover
            logger.warning("broker assignment side-effects failed: %s", exc)
        await _alert_broker(broker, brief, saved, workspace_id)

    await events.emit(state.lead_id, "handoff.created", {"handoff_id": saved["id"], "broker_id": row["broker_id"], "reason": reason}, workspace_id=workspace_id)
    return saved


async def _alert_broker(broker: BrokerProfile, brief: BrokerBrief, handoff: dict[str, Any], workspace_id: str) -> None:
    if not broker.phone:
        return
    text = (
        f"New {brief.band.upper()} lead ({brief.score}/100)\n{brief.headline}\n"
        f"Next: {brief.next_step}\nReply ACCEPT {handoff['id'][:8]} within {REASSIGN_AFTER_MIN} min."
    )
    try:
        await get_whatsapp_service().send_text(broker.phone, text, lead_id=handoff["lead_id"])
    except Exception as exc:  # pragma: no cover
        logger.warning("broker alert failed: %s", exc)


async def accept_handoff(handoff_id: str, broker_id: str, workspace_id: str) -> dict[str, Any] | None:
    handoffs = table("handoffs", workspace_id)
    row = await handoffs.get(id=handoff_id)
    if not row or row.get("broker_id") != broker_id or row.get("status") != "pending":
        return None
    updated = await handoffs.update({"status": "accepted", "accepted_at": now_iso()}, id=handoff_id)
    return updated[0] if updated else None


async def decline_handoff(handoff_id: str, broker_id: str, workspace_id: str, *, reason: str | None = None) -> dict[str, Any] | None:
    """Broker declines: reroute immediately to the next eligible broker."""
    handoffs = table("handoffs", workspace_id)
    row = await handoffs.get(id=handoff_id)
    if not row or row.get("broker_id") != broker_id or row.get("status") != "pending":
        return None
    await handoffs.update({"decline_reason": reason, "declined_at": now_iso()}, id=handoff_id)
    row["decline_reason"] = reason
    return await _reroute(row, workspace_id, await _brokers(workspace_id), datetime.now(timezone.utc), why="declined")


async def reassign_stale(workspace_id: str, now: datetime | None = None) -> list[dict[str, Any]]:
    """Move unaccepted handoffs to the next broker after 15 minutes."""
    now = now or datetime.now(timezone.utc)
    handoffs = table("handoffs", workspace_id)
    stale = [
        h for h in await handoffs.select(status="pending", limit=200)
        if h.get("reassign_after") and datetime.fromisoformat(h["reassign_after"]) <= now
    ]
    brokers = await _brokers(workspace_id)
    changed: list[dict[str, Any]] = []
    for h in stale:
        updated = await _reroute(h, workspace_id, brokers, now, why="timeout")
        if updated:
            changed.append(updated)
    return changed


async def _reroute(h: dict[str, Any], workspace_id: str, brokers: list[BrokerProfile], now: datetime, *, why: str) -> dict[str, Any] | None:
    handoffs = table("handoffs", workspace_id)
    tried = set(h.get("tried_broker_ids") or [])
    if h.get("broker_id"):
        tried.add(h["broker_id"])
    decision = route(brokers, language=h.get("language") or "en", community_ids=list((h.get("brief") or {}).get("profile", {}).get("community_ids") or []), exclude_ids=tried)
    if not decision.broker:
        rows = await handoffs.update({"status": "escalated", "routing_reasons": decision.reasons, "escalated_at": now_iso()}, id=h["id"])
        await events.emit(h["lead_id"], "handoff.escalated", {"handoff_id": h["id"], "why": why}, workspace_id=workspace_id)
        return rows[0] if rows else None
    updated = await handoffs.update(
        {
            "broker_id": decision.broker.id,
            "broker_name": decision.broker.name,
            "status": "pending",
            "reassigned_from": h.get("broker_id"),
            "tried_broker_ids": sorted(tried),
            "reassigned_count": int(h.get("reassigned_count") or 0) + 1,
            "reassign_after": (now + timedelta(minutes=REASSIGN_AFTER_MIN)).isoformat(),
            "routing_reasons": decision.reasons,
        },
        id=h["id"],
    )
    if not updated:
        return None
    try:
        await get_lead_repository(workspace_id).update(h["lead_id"], {"assigned_broker": decision.broker.id})
        await get_broker_repository(workspace_id).increment_lead_count(decision.broker.id)
    except Exception as exc:  # pragma: no cover
        logger.warning("reassignment side-effects failed: %s", exc)
    await events.emit(h["lead_id"], "handoff.reassigned", {"handoff_id": h["id"], "from": h.get("broker_id"), "to": decision.broker.id, "why": why}, workspace_id=workspace_id)
    await _alert_broker(decision.broker, BrokerBrief.model_validate(h["brief"]), updated[0], workspace_id)
    return updated[0]
