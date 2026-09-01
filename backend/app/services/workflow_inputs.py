"""Shared loader for workflow inputs.

Both the Celery worker and the ``/workflows/preview`` endpoint need the same
four collections (leads, viewings, mandates, listings), and they must agree —
if the preview shows a broker 33 pending actions and the scheduler then only
performs 5, the product is lying to them. Keeping the loading in one place is
what guarantees preview and execution see an identical world.

Falls back to seeded demo data whenever Supabase isn't configured, so the
workflow engine is fully demonstrable offline.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

WorkflowInputs = Tuple[
    List[Dict[str, Any]],  # leads
    List[Dict[str, Any]],  # viewings
    List[Dict[str, Any]],  # mandates
    List[Dict[str, Any]],  # listings
]


async def load_workflow_inputs(workspace_id: Optional[str] = None) -> WorkflowInputs:
    """Load everything the workflow templates evaluate against."""
    from app.database import (
        DatabaseClient,
        current_workspace_id,
        get_lead_repository,
        get_property_repository,
    )
    from app.seed_data import mock_mandates, mock_viewings

    workspace_id = workspace_id or current_workspace_id()
    client = DatabaseClient.get_client()

    leads = await _load_leads(get_lead_repository(workspace_id))
    listings = await _load_listings(get_property_repository(workspace_id))

    # Viewings and mandates have no repository yet — they're read straight from
    # their tables when a database exists, and seeded otherwise.
    viewings = _read_table(client, "viewings", workspace_id)
    mandates = _read_table(client, "mandates", workspace_id)
    if client is None:
        viewings = viewings or mock_viewings()
        mandates = mandates or mock_mandates()

    return leads, viewings, mandates, listings


async def _load_leads(repo: Any) -> List[Dict[str, Any]]:
    """Active pipeline statuses only — closed and lost leads aren't actioned."""
    leads: List[Dict[str, Any]] = []
    for status in ("new", "contacted", "qualified", "nurture"):
        try:
            leads.extend(await repo.list_by_status(status, limit=200, offset=0))
        except Exception as exc:
            logger.debug("Could not load %s leads: %s", status, exc)
    return leads


async def _load_listings(repo: Any) -> List[Dict[str, Any]]:
    try:
        return await repo.search_by_criteria(limit=500)
    except Exception as exc:
        logger.debug("Could not load listings: %s", exc)
        return []


def _read_table(client: Any, table: str, workspace_id: str) -> List[Dict[str, Any]]:
    """Read a workspace-scoped table, tolerating its absence."""
    if client is None:
        return []
    try:
        return (
            client.table(table)
            .select("*")
            .eq("workspace_id", workspace_id)
            .limit(500)
            .execute()
            .data
        ) or []
    except Exception as exc:
        logger.debug("Table %s unavailable: %s", table, exc)
        return []
