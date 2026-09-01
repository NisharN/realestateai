"""WhatsApp send-side.

Replaces the previous fails-closed stub (which verified Meta's signature and
then returned 503 without ever sending). Two modes, per PILOT.md:

- ``mock``  — the default. Nothing leaves the building; every message is
  appended to an in-memory/DB outbox so the demo can show exactly what would
  have been sent, to whom, and when. This is what makes the product demoable
  today, while Meta Business Verification (2-4+ weeks) is still pending.
- ``live``  — real Meta Cloud API call. Automatically falls back to mock if
  the access token or phone number id is missing, so a half-configured
  deployment degrades to "recorded but not sent" rather than crashing.

The outbox is not a throwaway demo prop: in live mode it is still written, so
there is always a local record of what the AI sent to a lead. Brokers asked to
see transcripts before trusting handoff — this is where that comes from.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"


@dataclass
class OutboundMessage:
    """One outbound WhatsApp message, sent or simulated."""

    id: str
    to: str
    body: str
    lead_id: Optional[str] = None
    template: Optional[str] = None
    mode: str = "mock"                 # mock | live
    status: str = "queued"             # queued | sent | failed | simulated
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WhatsAppOutbox:
    """In-process record of outbound messages.

    Deliberately simple. When Supabase is configured the messages are also
    persisted to ``whatsapp_outbox``; when it isn't (pure demo mode) the
    in-memory list is the whole story and survives for the life of the process.
    """

    def __init__(self) -> None:
        self._messages: List[OutboundMessage] = []

    def add(self, message: OutboundMessage) -> OutboundMessage:
        self._messages.append(message)
        self._persist(message)
        return message

    def list(self, lead_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        items = self._messages
        if lead_id:
            items = [m for m in items if m.lead_id == lead_id]
        return [m.to_dict() for m in reversed(items[-limit:])]

    def clear(self) -> None:
        self._messages.clear()

    def _persist(self, message: OutboundMessage) -> None:
        """Best-effort write-through. Never let logging break sending."""
        try:
            from app.database import DatabaseClient, current_workspace_id

            client = DatabaseClient.get_client()
            if client is None:
                return
            payload = message.to_dict()
            payload["workspace_id"] = current_workspace_id()
            client.table("whatsapp_outbox").insert(payload).execute()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Outbox persistence skipped: %s", exc)


_outbox = WhatsAppOutbox()


def get_outbox() -> WhatsAppOutbox:
    return _outbox


class WhatsAppService:
    """Send WhatsApp messages, or simulate them convincingly."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.outbox = get_outbox()

    @property
    def mode(self) -> str:
        return self.settings.whatsapp_mode

    async def send_text(
        self,
        to: str,
        body: str,
        lead_id: Optional[str] = None,
    ) -> OutboundMessage:
        """Send a free-form text message to a lead."""
        message = OutboundMessage(
            id=str(uuid.uuid4()),
            to=_normalize_phone(to),
            body=body,
            lead_id=lead_id,
            mode=self.mode,
        )

        if not message.to:
            message.status = "failed"
            message.error = "missing_recipient"
            return self.outbox.add(message)

        if self.mode != "live":
            # Mock mode: record it, don't send it. The demo reads the outbox.
            message.status = "simulated"
            logger.info("[whatsapp:mock] -> %s: %s", message.to, body[:80])
            return self.outbox.add(message)

        try:
            provider_id = await self._post_to_meta(message.to, body)
            message.status = "sent"
            message.provider_message_id = provider_id
        except Exception as exc:
            message.status = "failed"
            message.error = str(exc)
            logger.error("WhatsApp send failed for %s: %s", message.to, exc)

        return self.outbox.add(message)

    async def _post_to_meta(self, to: str, body: str) -> Optional[str]:
        settings = self.settings
        url = (
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/"
            f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        messages = data.get("messages") or []
        return messages[0].get("id") if messages else None


def _normalize_phone(phone: Optional[str]) -> str:
    """Meta wants digits only, country code included, no '+' or spaces.

    UAE numbers are commonly written '+971 50 123 4567', '050 123 4567', or
    '0501234567'. The local-format variants need the leading zero swapped for
    the country code or the message silently goes nowhere.
    """
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    # Local UAE mobile: 05XXXXXXXX -> 9715XXXXXXXX
    if digits.startswith("0") and len(digits) == 10:
        digits = "971" + digits[1:]
    return digits


_service: Optional[WhatsAppService] = None


def get_whatsapp_service() -> WhatsAppService:
    global _service
    if _service is None:
        _service = WhatsAppService()
    return _service
