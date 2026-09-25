"""Operational metrics and alert evaluation (architecture §12).

Everything is derived from stored rows so it works identically against the
in-memory store and Supabase; no metrics backend is required for the pilot.
Alert thresholds mirror the runbook: fallback rate > 5% over 15 minutes,
consumer lag > 5 minutes, connector with 3+ consecutive failures, review queue > 20.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.modules.ingestion import events
from app.modules.llm.gateway import get_gateway
from app.modules.store import table

FALLBACK_RATE_MAX = 0.05
FALLBACK_WINDOW_MIN = 15
CONSUMER_LAG_MAX_S = 300
CONNECTOR_FAILURES_MAX = 3
REVIEW_QUEUE_MAX = 20
CONSUMERS = ("crm_writeback",)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * pct) - 1))
    return ordered[idx]


def summarize_turns(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Assistant messages carry ``meta.latency_ms``, ``meta.fallbacks`` and ``meta.move``."""
    latencies: list[int] = []
    fallback_turns = 0
    guard_failures = 0
    tool_failures = 0
    llm_fallbacks = 0
    moves: dict[str, int] = {}
    for m in rows:
        meta = m.get("meta") or {}
        if isinstance(meta.get("latency_ms"), int):
            latencies.append(meta["latency_ms"])
        fallbacks = [f for f in (meta.get("fallbacks") or []) if f.startswith(("template:", "tool:"))]
        if fallbacks:
            fallback_turns += 1
        guard_failures += sum(1 for f in fallbacks if f == "template:guard_rejected")
        tool_failures += sum(1 for f in fallbacks if f.startswith("tool:"))
        llm_fallbacks += sum(1 for f in fallbacks if f in ("template:llm_unavailable", "template:exception"))
        move = meta.get("move")
        if move:
            moves[move] = moves.get(move, 0) + 1
    total = len(rows)
    return {
        "turns": total,
        "latency_ms": {"p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95), "max": max(latencies) if latencies else None},
        "fallback_turns": fallback_turns,
        "fallback_rate": round(fallback_turns / total, 4) if total else 0.0,
        "guard_failures": guard_failures,
        "tool_failures": tool_failures,
        "llm_fallbacks": llm_fallbacks,
        "moves": moves,
    }


async def collect(workspace_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(minutes=FALLBACK_WINDOW_MIN)).isoformat()
    messages = table("messages", workspace_id)
    recent = await messages.select(role="assistant", created_at__gte=since, order="created_at", limit=5_000)
    all_recent = await messages.select(role="assistant", order="created_at", desc=True, limit=1_000)

    consumer_lag: dict[str, Any] = {}
    for consumer in CONSUMERS:
        pending = await events.pending(workspace_id, consumer, limit=500)
        oldest = _parse(pending[0].get("created_at")) if pending else None
        consumer_lag[consumer] = {
            "pending": len(pending),
            "lag_s": int((now - oldest).total_seconds()) if oldest else 0,
        }

    connectors = await table("connectors", workspace_id).select(limit=200)
    connector_health = [
        {
            "connector_id": c["id"],
            "display_name": c.get("display_name"),
            "type": c.get("type"),
            "status": c.get("status"),
            "consecutive_failures": c.get("consecutive_failures", 0) or 0,
            "last_success_at": c.get("last_success_at"),
        }
        for c in connectors
    ]
    review_open = await table("review_queue", workspace_id).count(resolved_at__isnull=True)

    window = summarize_turns(recent)
    llm_configured = get_gateway().available
    alerts: list[dict[str, Any]] = []
    # Without an LLM every reply is templated by design; the fallback alert only means something when one is configured.
    if llm_configured and window["turns"] and window["fallback_rate"] > FALLBACK_RATE_MAX:
        alerts.append({"code": "fallback_rate", "severity": "warning", "value": window["fallback_rate"], "threshold": FALLBACK_RATE_MAX, "message": f"Fallback rate {window['fallback_rate']:.1%} over last {FALLBACK_WINDOW_MIN} min"})
    for consumer, lag in consumer_lag.items():
        if lag["lag_s"] > CONSUMER_LAG_MAX_S:
            alerts.append({"code": "consumer_lag", "severity": "warning", "value": lag["lag_s"], "threshold": CONSUMER_LAG_MAX_S, "message": f"{consumer} is {lag['lag_s'] // 60} min behind"})
    for c in connector_health:
        if c["consecutive_failures"] >= CONNECTOR_FAILURES_MAX:
            alerts.append({"code": "connector_failing", "severity": "critical", "value": c["consecutive_failures"], "threshold": CONNECTOR_FAILURES_MAX, "message": f"Connector {c['display_name'] or c['connector_id']} failed {c['consecutive_failures']} times in a row"})
    if review_open > REVIEW_QUEUE_MAX:
        alerts.append({"code": "review_queue", "severity": "warning", "value": review_open, "threshold": REVIEW_QUEUE_MAX, "message": f"{review_open} records waiting for review"})

    return {
        "generated_at": now.isoformat(),
        "window_minutes": FALLBACK_WINDOW_MIN,
        "llm_configured": llm_configured,
        "window": window,
        "recent_1000": summarize_turns(all_recent),
        "consumers": consumer_lag,
        "connectors": connector_health,
        "review_open": review_open,
        "thresholds": {
            "fallback_rate": FALLBACK_RATE_MAX,
            "consumer_lag_s": CONSUMER_LAG_MAX_S,
            "connector_failures": CONNECTOR_FAILURES_MAX,
            "review_queue": REVIEW_QUEUE_MAX,
        },
        "alerts": alerts,
    }
