"""Viewing requests and bookings.

A viewing is created either by the engine (buyer accepted a proposed slot while
confirming a specialist handoff) or by a broker from the lead detail page. Status
transitions are explicit; confirming moves the lead to the ``viewing_booked``
pipeline stage, completion/no-show is recorded as a lead event only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from app.database import get_lead_repository
from app.modules.store import new_id, now_iso, table

logger = logging.getLogger(__name__)

ViewingStatus = Literal["requested", "confirmed", "done", "no_show", "cancelled"]
STATUSES: tuple[str, ...] = ("requested", "confirmed", "done", "no_show", "cancelled")
TRANSITIONS: dict[str, set[str]] = {
    "requested": {"confirmed", "cancelled"},
    "confirmed": {"done", "no_show", "cancelled"},
    "done": set(),
    "no_show": {"confirmed"},
    "cancelled": {"requested"},
}


class InvalidTransition(ValueError):
    pass


def _parse_when(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


async def request_viewing(
    workspace_id: str,
    *,
    lead_id: str,
    property_id: str | None,
    starts_at: str | datetime | None,
    broker_id: str | None,
    source: str,
    notes: str | None = None,
    status: ViewingStatus = "requested",
) -> dict[str, Any]:
    """Idempotent per (lead, property, start): re-requesting the same slot returns the open row."""
    viewings = table("viewings", workspace_id)
    when = _parse_when(starts_at)
    existing = await viewings.select(lead_id=lead_id, status__in=["requested", "confirmed"], limit=20)
    for row in existing:
        if row.get("property_id") == property_id and row.get("starts_at") == when:
            return row
    row = {
        "id": new_id(),
        "lead_id": lead_id,
        "broker_id": broker_id,
        "property_id": property_id,
        "starts_at": when,
        "status": status,
        "notes": notes,
        "source": source,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    saved = await viewings.insert(row)
    await table("lead_events", workspace_id).insert(
        {"lead_id": lead_id, "type": "viewing.requested", "payload": {"viewing_id": saved["id"], "property_id": property_id, "starts_at": when, "source": source}}
    )
    if status == "confirmed":
        await _mark_booked(workspace_id, lead_id)
    return saved


async def update_viewing(
    workspace_id: str,
    viewing_id: str,
    *,
    status: ViewingStatus | None = None,
    starts_at: str | datetime | None = None,
    broker_id: str | None = None,
    notes: str | None = None,
    actor: str | None = None,
) -> dict[str, Any] | None:
    viewings = table("viewings", workspace_id)
    row = await viewings.get(id=viewing_id)
    if not row:
        return None
    updates: dict[str, Any] = {"updated_at": now_iso()}
    if status and status != row["status"]:
        if status not in TRANSITIONS.get(row["status"], set()):
            raise InvalidTransition(f"{row['status']} -> {status}")
        updates["status"] = status
    if starts_at is not None:
        updates["starts_at"] = _parse_when(starts_at)
    if broker_id is not None:
        updates["broker_id"] = broker_id
    if notes is not None:
        updates["notes"] = notes
    rows = await viewings.update(updates, id=viewing_id)
    saved = rows[0] if rows else {**row, **updates}
    if "status" in updates:
        await table("lead_events", workspace_id).insert(
            {"lead_id": row["lead_id"], "type": f"viewing.{updates['status']}", "payload": {"viewing_id": viewing_id, "actor": actor}}
        )
        if updates["status"] == "confirmed":
            await _mark_booked(workspace_id, row["lead_id"])
    return saved


async def list_viewings(
    workspace_id: str,
    *,
    lead_id: str | None = None,
    broker_id: str | None = None,
    statuses: list[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    filters: dict[str, Any] = {}
    if lead_id:
        filters["lead_id"] = lead_id
    if broker_id:
        filters["broker_id"] = broker_id
    if statuses:
        filters["status__in"] = statuses
    return await table("viewings", workspace_id).select(order="starts_at", limit=limit, **filters)


async def _mark_booked(workspace_id: str, lead_id: str) -> None:
    repo = get_lead_repository(workspace_id)
    lead = await repo.get_by_id(lead_id)
    if not lead or lead.get("stage") in {"viewing_booked", "offer", "closed", "lost", "opted_out"}:
        return
    try:
        await repo.update(lead_id, {"stage": "viewing_booked"})
    except Exception as exc:  # pragma: no cover
        logger.warning("could not advance lead %s to viewing_booked: %s", lead_id, exc)
