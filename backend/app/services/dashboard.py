"""Workspace dashboard aggregation."""
from collections import Counter
from typing import Any, Iterable


def summarize_leads(leads: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(leads)
    scores = [float(lead.get("intent_score") or 0) for lead in records]
    return {
        "total_leads": len(records),
        "qualified_leads": sum(
            lead.get("status") in {"qualified", "closed"} for lead in records
        ),
        "closed_leads": sum(lead.get("status") == "closed" for lead in records),
        "unassigned_leads": sum(not lead.get("assigned_broker") for lead in records),
        "average_intent_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "status_counts": dict(Counter(str(lead.get("status") or "unknown") for lead in records)),
    }
