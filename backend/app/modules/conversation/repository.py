"""Persistence for ConversationState and normalized messages.

Tables: ``conversation_states`` (one row per lead, optimistic ``version``),
``messages`` (one row per utterance, ``idempotency_key`` unique per lead).
"""
from __future__ import annotations

from typing import Any

from app.modules.store import new_id, now_iso, table

from .state import ConversationState


class ConversationRepo:
    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self.states = table("conversation_states", workspace_id)
        self.messages = table("messages", workspace_id)

    async def load(self, lead_id: str, *, channel: str = "chat", source: str | None = None) -> ConversationState:
        row = await self.states.get(lead_id=lead_id)
        if row:
            state = ConversationState.model_validate(row["state"])
            state.version = int(row.get("version") or state.version)
            state.channel = channel  # type: ignore[assignment]
            return state
        state = ConversationState(lead_id=lead_id, channel=channel, source=source, conversation_id=new_id())  # type: ignore[arg-type]
        return state

    async def save(self, state: ConversationState) -> ConversationState:
        state.version += 1
        state.updated_at = now_iso()
        await self.states.upsert(
            {
                "lead_id": state.lead_id,
                "conversation_id": state.conversation_id,
                "stage": state.stage,
                "language": state.language,
                "score": state.score,
                "band": state.band,
                "turn": state.turn,
                "version": state.version,
                "state": state.model_dump(mode="json"),
                "updated_at": state.updated_at,
            },
            on_conflict="workspace_id,lead_id",
        )
        return state

    async def find_message(self, lead_id: str, idempotency_key: str) -> dict[str, Any] | None:
        return await self.messages.get(lead_id=lead_id, idempotency_key=idempotency_key, role="assistant")

    async def save_turn(
        self,
        state: ConversationState,
        *,
        text: str,
        reply: str,
        move: str,
        facts: dict[str, Any],
        tool_results: dict[str, Any],
        idempotency_key: str,
        latency_ms: int,
        fallbacks: list[str],
    ) -> None:
        conv = state.conversation_id or state.lead_id
        await self.messages.insert(
            {
                "lead_id": state.lead_id,
                "conversation_id": conv,
                "turn": state.turn,
                "role": "user",
                "channel": state.channel,
                "text": text,
                "idempotency_key": idempotency_key,
                "meta": {"facts": facts},
            }
        )
        await self.messages.insert(
            {
                "lead_id": state.lead_id,
                "conversation_id": conv,
                "turn": state.turn,
                "role": "assistant",
                "channel": state.channel,
                "text": reply,
                "idempotency_key": idempotency_key,
                "meta": {
                    "move": move,
                    "tool_results": tool_results,
                    "latency_ms": latency_ms,
                    "fallbacks": fallbacks,
                    "score": state.score,
                    "stage": state.stage,
                },
            }
        )
        await self.save(state)

    async def history(self, lead_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.messages.select(lead_id=lead_id, order="created_at", limit=limit * 2)
        return rows[-limit:]

    async def transcript(self, lead_id: str, limit: int = 20) -> list[dict[str, str]]:
        return [{"role": m["role"], "content": m["text"]} for m in await self.history(lead_id, limit)]
