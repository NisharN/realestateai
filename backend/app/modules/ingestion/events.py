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
    """Events this consumer has not processed yet, oldest first."""
    events = await table("lead_events", workspace_id).select(order="created_at", limit=limit * 4)
    done = await table("consumer_offsets", workspace_id).select(consumer=consumer, limit=10_000)
    seen = {d["event_id"] for d in done}
    return [e for e in events if e["id"] not in seen][:limit]


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
