"""Follow-up schedules for warm/cold leads, honouring consent, STOP and DND hours.

Deterministic: cadence per band, every send clamped into 09:00–21:00 Dubai
time, nothing after opt-out, nothing without channel consent.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

from app.database import get_lead_repository
from app.modules.conversation import templates
from app.modules.store import Row, new_id, now_iso, table
from app.services.whatsapp import get_whatsapp_service

logger = logging.getLogger(__name__)

DUBAI = timezone(timedelta(hours=4))
DND_START = time(21, 0)
DND_END = time(9, 0)

# hours after the trigger for each touch
CADENCE_HOURS: dict[str, tuple[int, ...]] = {
    "warm": (24, 72, 24 * 7),
    "cold": (72, 24 * 14),
    "hot": (),
}
TOUCH_TEMPLATES = ("followup_1", "followup_2", "followup_3")


def clamp_to_window(when: datetime) -> datetime:
    """Move ``when`` into the next allowed send window (09:00–21:00 Dubai)."""
    local = when.astimezone(DUBAI)
    if local.time() >= DND_START:
        local = (local + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif local.time() < DND_END:
        local = local.replace(hour=9, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


def in_window(when: datetime) -> bool:
    local = when.astimezone(DUBAI).time()
    return DND_END <= local < DND_START


def _allowed(lead: Row) -> bool:
    if lead.get("opted_out_at") or lead.get("stage") == "opted_out" or lead.get("status") == "opted_out":
        return False
    consent = lead.get("consent") or {}
    if consent and consent.get("marketing") is False:
        return False
    return bool(lead.get("phone") or lead.get("phone_e164"))


async def schedule_followups(lead_id: str, band: str, *, workspace_id: str, now: datetime | None = None) -> list[Row]:
    """Replace any pending schedule for the lead with the cadence for ``band``."""
    now = now or datetime.now(timezone.utc)
    followups = table("followups", workspace_id)
    lead = await get_lead_repository(workspace_id).get_by_id(lead_id)
    await followups.delete(lead_id=lead_id, status="pending")
    if not lead or not _allowed(lead):
        return []
    rows: list[Row] = []
    for i, hours in enumerate(CADENCE_HOURS.get(band, ())):
        due = clamp_to_window(now + timedelta(hours=hours))
        rows.append(
            await followups.insert(
                {
                    "id": new_id(),
                    "lead_id": lead_id,
                    "band": band,
                    "touch": i + 1,
                    "template_key": TOUCH_TEMPLATES[min(i, len(TOUCH_TEMPLATES) - 1)],
                    "channel": "whatsapp",
                    "due_at": due.isoformat(),
                    "status": "pending",
                    "created_at": now_iso(),
                }
            )
        )
    return rows


async def cancel_followups(lead_id: str, *, workspace_id: str, reason: str) -> int:
    rows = await table("followups", workspace_id).update({"status": "cancelled", "cancel_reason": reason}, lead_id=lead_id, status="pending")
    return len(rows)


async def send_due(workspace_id: str, now: datetime | None = None, limit: int = 100) -> list[Row]:
    """Send follow-ups whose time has come; re-check consent/STOP and DND at send time."""
    now = now or datetime.now(timezone.utc)
    if not in_window(now):
        return []
    followups = table("followups", workspace_id)
    due = [f for f in await followups.select(status="pending", limit=limit) if f.get("due_at") and datetime.fromisoformat(f["due_at"]) <= now]
    repo = get_lead_repository(workspace_id)
    sent: list[Row] = []
    for f in due:
        lead = await repo.get_by_id(f["lead_id"])
        if not lead or not _allowed(lead):
            await followups.update({"status": "cancelled", "cancel_reason": "consent_or_optout"}, id=f["id"])
            continue
        if lead.get("stage") in ("handed_off", "viewing_booked", "closed") and lead.get("assigned_broker"):
            await followups.update({"status": "cancelled", "cancel_reason": "broker_owns_lead"}, id=f["id"])
            continue
        lang = lead.get("preferred_language") or lead.get("language") or "en"
        text = templates.render(f["template_key"], lang, {"name": lead.get("first_name") or "", "area": (lead.get("area_preference") or [""])[0]})
        try:
            await get_whatsapp_service().send_text(lead.get("phone") or lead.get("phone_e164"), text, lead_id=lead["id"])
            rows = await followups.update({"status": "sent", "sent_at": now_iso(), "text": text}, id=f["id"])
        except Exception as exc:
            logger.warning("followup send failed for %s: %s", f["id"], exc)
            rows = await followups.update({"status": "failed", "error": str(exc)}, id=f["id"])
        if rows:
            sent.append(rows[0])
    return sent


async def pending_for_broker(workspace_id: str, broker_id: str | None, limit: int = 50) -> list[dict[str, Any]]:
    followups = table("followups", workspace_id)
    repo = get_lead_repository(workspace_id)
    out = []
    for f in await followups.select(status="pending", order="due_at", limit=limit * 3):
        lead = await repo.get_by_id(f["lead_id"])
        if not lead or (broker_id and lead.get("assigned_broker") not in (None, broker_id)):
            continue
        out.append({**f, "lead_name": f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip(), "lead_band": lead.get("band")})
        if len(out) >= limit:
            break
    return out
