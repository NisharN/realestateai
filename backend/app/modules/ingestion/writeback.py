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


async def _targets(lead_id: str, workspace_id: str) -> list[tuple[Row, str]]:
    """(connector, external_id) for every pull connector that fed this lead.

    A merged lead may exist in several CRMs under different ids; each gets its
    own write-back with the id *that* CRM assigned (taken from its raw record),
    never the lead's single ``crm_external_id`` column.
    """
    raws = await table("raw_lead_records", workspace_id).select(lead_id=lead_id, order="received_at", desc=True, limit=1000)
    newest: dict[str, str] = {}
    for raw in raws:
        cid, ext = raw.get("connector_id"), raw.get("external_id")
        if cid and ext and cid not in newest:
            newest[cid] = str(ext)
    out: list[tuple[Row, str]] = []
    for cid, ext in newest.items():
        row = await table("connectors", workspace_id).get(id=cid)
        if row and row.get("mode") == "pull" and (row.get("config") or {}).get("write_back_url"):
            out.append((row, ext))
    return out


def fields_for(lead: Row, connector: Row) -> dict[str, Any]:
    wanted = (connector.get("config") or {}).get("write_back_fields") or list(DEFAULT_FIELDS)
    return {k: lead.get(k) for k in wanted if k in ALLOWED_FIELDS and lead.get(k) is not None}


async def handle_event(
    event: Row,
    *,
    workspace_id: str,
    client: httpx.AsyncClient | None = None,
    sent_this_run: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> bool:
    """Write the lead's current state to each source CRM; identical payloads already sent in this run are skipped."""
    if event.get("type") not in EVENT_TYPES:
        return False
    targets = await _targets(event["lead_id"], workspace_id)
    if not targets:
        return False
    lead = await get_lead_repository(workspace_id).get_by_id(event["lead_id"])
    if not lead:
        return False
    sent = False
    for connector, external_id in targets:
        fields = fields_for(lead, connector)
        key = (str(event["lead_id"]), str(connector["id"]))
        if sent_this_run is not None and sent_this_run.get(key) == fields:
            continue
        if fields:
            if sent_this_run is not None:
                sent_this_run[key] = fields
            await CrmPullConnector(connector, client=client).write_back({**lead, "crm_external_id": external_id}, fields)
            sent = True
    return sent


async def run_writeback(workspace_id: str, limit: int = 100, *, client: httpx.AsyncClient | None = None) -> int:
    sent_this_run: dict[tuple[str, str], dict[str, Any]] = {}

    async def handler(event: Row) -> None:
        try:
            await handle_event(event, workspace_id=workspace_id, client=client, sent_this_run=sent_this_run)
        except Exception as exc:
            raise RuntimeError(safe_error(exc)) from None

    return await events.consume(workspace_id, CONSUMER, handler, limit=limit)
