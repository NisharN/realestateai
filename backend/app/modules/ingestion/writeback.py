"""CRM write-back — an outbox consumer (§6.4).

For every ``lead.*`` / ``handoff.*`` event on a lead that came from a pull
connector with ``config.write_back_url``, PATCH the CRM with a small, explicit
field set. Consumer offsets make redelivery a no-op; a failing CRM stops the
consumer for this tick and it resumes on the next one.

    config.write_back_url    "https://crm.example.com/leads/{id}"
    config.write_back_fields ["score", "stage", "assigned_broker"]   # default
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.database import get_lead_repository
from app.modules.ingestion import events
from app.modules.ingestion.connectors.crm_pull import CrmPullConnector, safe_error
from app.modules.store import Row, table

logger = logging.getLogger(__name__)

CONSUMER = "crm_writeback"
EVENT_TYPES = ("lead.updated", "lead.scored", "handoff.created", "handoff.accepted", "handoff.reassigned")
DEFAULT_FIELDS = ("score", "stage", "assigned_broker")
ALLOWED_FIELDS = ("score", "intent_score", "band", "stage", "status", "assigned_broker", "purpose", "timeline", "budget_min_aed", "budget_max_aed", "area_preference")


async def _connector_for(lead_id: str, workspace_id: str) -> Row | None:
    raws = await table("raw_lead_records", workspace_id).select(lead_id=lead_id, order="received_at", desc=True, limit=20)
    for raw in raws:
        cid = raw.get("connector_id")
        if not cid:
            continue
        row = await table("connectors", workspace_id).get(id=cid)
        if row and row.get("mode") == "pull" and (row.get("config") or {}).get("write_back_url"):
            return row
    return None


def fields_for(lead: Row, connector: Row) -> dict[str, Any]:
    wanted = (connector.get("config") or {}).get("write_back_fields") or list(DEFAULT_FIELDS)
    return {k: lead.get(k) for k in wanted if k in ALLOWED_FIELDS and lead.get(k) is not None}


async def handle_event(event: Row, *, workspace_id: str, client: httpx.AsyncClient | None = None) -> bool:
    if event.get("type") not in EVENT_TYPES:
        return False
    connector = await _connector_for(event["lead_id"], workspace_id)
    if connector is None:
        return False
    lead = await get_lead_repository(workspace_id).get_by_id(event["lead_id"])
    if not lead or not lead.get("crm_external_id"):
        return False
    fields = fields_for(lead, connector)
    if not fields:
        return False
    await CrmPullConnector(connector, client=client).write_back(lead, fields)
    return True


async def run_writeback(workspace_id: str, limit: int = 100, *, client: httpx.AsyncClient | None = None) -> int:
    async def handler(event: Row) -> None:
        try:
            await handle_event(event, workspace_id=workspace_id, client=client)
        except Exception as exc:
            raise RuntimeError(safe_error(exc)) from None

    return await events.consume(workspace_id, CONSUMER, handler, limit=limit)
