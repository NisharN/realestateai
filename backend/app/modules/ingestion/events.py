"""Lead event outbox and idempotent consumers (architecture §6.4)."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.modules.store import Row, new_id, now_iso, table

logger = logging.getLogger(__name__)

Handler = Callable[[Row], Awaitable[None]]


async def emit(lead_id: str, event_type: str, payload: dict[str, Any], *, workspace_id: str) -> Row:
    return await table("lead_events", workspace_id).insert(
        {
            "id": new_id(),
            "lead_id": lead_id,
            "type": event_type,
            "payload": payload,
            "published_at": None,
            "created_at": now_iso(),
        }
    )


async def pending(workspace_id: str, consumer: str, limit: int = 100) -> list[Row]:
    """Events this consumer has not processed yet, oldest first.

    ``consume`` handles events strictly in ``created_at`` order and stops at the
    first failure, so everything older than the newest processed event is done:
    start there (watermark) and page forward, excluding already-seen ids per
    page instead of loading the whole offsets table.
    """
    events_t = table("lead_events", workspace_id)
    offsets_t = table("consumer_offsets", workspace_id)
    filters: dict[str, Any] = {}
    last = await offsets_t.select(consumer=consumer, order="processed_at", desc=True, limit=1)
    if last:
        marker = await events_t.get(id=last[0]["event_id"])
        if marker and marker.get("created_at"):
            filters["created_at__gte"] = marker["created_at"]
    out: list[Row] = []
    page = max(limit, 50)
    offset = 0
    while len(out) < limit:
        chunk = await events_t.select(order="created_at", limit=page, offset=offset, **filters)
        if not chunk:
            break
        done = await offsets_t.select(consumer=consumer, event_id__in=[e["id"] for e in chunk], limit=page)
        seen = {d["event_id"] for d in done}
        out.extend(e for e in chunk if e["id"] not in seen)
        if len(chunk) < page:
            break
        offset += page
    return out[:limit]


async def consume(workspace_id: str, consumer: str, handler: Handler, limit: int = 100) -> int:
    """Run ``handler`` once per unprocessed event; offsets make redelivery a no-op."""
    offsets = table("consumer_offsets", workspace_id)
    processed = 0
    for event in await pending(workspace_id, consumer, limit):
        try:
            await handler(event)
        except Exception as exc:
            logger.warning("consumer %s failed on %s: %s", consumer, event["id"], exc)
            break
        await offsets.upsert({"consumer": consumer, "event_id": event["id"], "processed_at": now_iso()}, on_conflict="consumer,event_id")
        processed += 1
    return processed


class DashboardPush:
    """In-process fan-out target; the WebSocket layer subscribes here."""

    def __init__(self) -> None:
        self.subscribers: list[Callable[[Row], Awaitable[None]]] = []
        self.delivered: list[Row] = []

    def subscribe(self, fn: Callable[[Row], Awaitable[None]]) -> None:
        self.subscribers.append(fn)

    async def __call__(self, event: Row) -> None:
        self.delivered.append(event)
        for fn in list(self.subscribers):
            await fn(event)


dashboard_push = DashboardPush()
