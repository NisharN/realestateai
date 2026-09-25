"""Inbound WhatsApp (Meta Cloud API) → shared turn engine.

Order of operations is fixed by the architecture: persist the raw event,
acknowledge, then process. Processing is idempotent on the provider message
id so Meta retries never produce a second reply.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.database import get_lead_repository
from app.modules.agents.extractor import detect_language
from app.modules.conversation.engine import handle_turn
from app.modules.conversation.repository import ConversationRepo
from app.modules.store import new_id, now_iso, table
from app.services.whatsapp import get_whatsapp_service

logger = logging.getLogger(__name__)


@dataclass
class InboundMessage:
    provider_message_id: str
    from_phone: str
    text: str
    phone_number_id: str
    profile_name: str | None = None
    timestamp: str | None = None


@dataclass
class InboundResult:
    stored: int = 0
    replied: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def parse_meta_payload(payload: dict[str, Any]) -> list[InboundMessage]:
    out: list[InboundMessage] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
            names = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in value.get("contacts") or []
                if isinstance(c, dict)
            }
            for msg in value.get("messages") or []:
                if not isinstance(msg, dict) or msg.get("type") != "text":
                    continue
                body = ((msg.get("text") or {}).get("body") or "").strip()
                if not body or not msg.get("id") or not msg.get("from"):
                    continue
                out.append(
                    InboundMessage(
                        provider_message_id=str(msg["id"]),
                        from_phone=str(msg["from"]),
                        text=body,
                        phone_number_id=phone_number_id,
                        profile_name=names.get(msg.get("from")),
                        timestamp=str(msg.get("timestamp") or ""),
                    )
                )
    return out


def resolve_workspace(phone_number_id: str) -> str | None:
    settings = get_settings()
    configured = settings.WHATSAPP_PHONE_NUMBER_ID
    if configured and phone_number_id and configured != phone_number_id:
        return None
    return settings.WORKSPACE_ID


async def store_raw_event(workspace_id: str | None, msg: InboundMessage) -> bool:
    """Persist the raw provider event. Returns False if it was already stored."""
    events = table("webhook_events", workspace_id or get_settings().WORKSPACE_ID)
    if await events.get(provider="whatsapp", provider_event_id=msg.provider_message_id):
        return False
    await events.insert(
        {
            "id": new_id(),
            "provider": "whatsapp",
            "provider_event_id": msg.provider_message_id,
            "event_type": "message.text",
            "status": "received",
            "received_at": now_iso(),
        }
    )
    return True


async def _lead_for(workspace_id: str, msg: InboundMessage) -> dict[str, Any]:
    repo = get_lead_repository(workspace_id)
    phone = "+" + msg.from_phone.lstrip("+")
    lead = await repo.get_by_phone(phone)
    if lead:
        return lead
    first, _, last = (msg.profile_name or "WhatsApp Lead").partition(" ")
    lead = await repo.create(
        {
            "first_name": first,
            "last_name": last or None,
            "phone": phone,
            "source": "whatsapp",
            "preferred_language": "ar" if detect_language(msg.text) == "ar" else "en",
            "status": "new",
            "intent_score": 0,
            "created_at": now_iso(),
        }
    )
    await ConversationRepo(workspace_id).save(
        await ConversationRepo(workspace_id).load(lead["id"], channel="whatsapp", source="whatsapp")
    )
    return lead


async def process_message(workspace_id: str, msg: InboundMessage) -> bool:
    events = table("webhook_events", workspace_id)
    lead = await _lead_for(workspace_id, msg)
    result = await handle_turn(
        lead["id"],
        msg.text,
        workspace_id=workspace_id,
        channel="whatsapp",
        idempotency_key=f"wa:{msg.provider_message_id}",
        source="whatsapp",
    )
    if result.idempotent_replay:
        await events.update(
            {"status": "duplicate", "processed_at": now_iso()},
            provider="whatsapp",
            provider_event_id=msg.provider_message_id,
        )
        return False
    sent = await get_whatsapp_service().send_text(lead["phone"], result.reply, lead_id=lead["id"])
    await events.update(
        {
            "status": "processed" if sent.status in {"sent", "simulated"} else "error",
            "processed_at": now_iso(),
            "error_code": sent.error,
        },
        provider="whatsapp",
        provider_event_id=msg.provider_message_id,
    )
    return True


async def handle_payload(payload: dict[str, Any]) -> InboundResult:
    result = InboundResult()
    for msg in parse_meta_payload(payload):
        workspace_id = resolve_workspace(msg.phone_number_id)
        if workspace_id is None:
            result.skipped += 1
            continue
        if not await store_raw_event(workspace_id, msg):
            result.skipped += 1
            continue
        result.stored += 1
        try:
            if await process_message(workspace_id, msg):
                result.replied += 1
        except Exception as exc:  # the raw event is saved; processing can be retried
            logger.exception("WhatsApp inbound processing failed")
            result.errors.append(str(exc))
            await table("webhook_events", workspace_id).update(
                {"status": "error", "error_code": type(exc).__name__},
                provider="whatsapp",
                provider_event_id=msg.provider_message_id,
            )
    return result
