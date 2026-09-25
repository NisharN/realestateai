"""Pipeline stage vocabulary shared by the repositories and the broker API."""
from __future__ import annotations

from typing import Any

PIPELINE_STAGES: tuple[str, ...] = ("new", "qualifying", "qualified", "handed_off", "viewing_booked", "offer", "closed", "lost", "opted_out")
CLOSED_STAGES: frozenset[str] = frozenset({"closed", "lost", "opted_out"})
# Leads created before ``stage`` existed only carry the legacy ``status``.
LEGACY_STATUS_STAGE: dict[str, str] = {"new": "new", "contacted": "handed_off", "qualified": "qualified"}


def lead_stage(lead: dict[str, Any]) -> str:
    stage = lead.get("stage")
    if stage in PIPELINE_STAGES:
        return stage
    return LEGACY_STATUS_STAGE.get(lead.get("status") or "", "new")
