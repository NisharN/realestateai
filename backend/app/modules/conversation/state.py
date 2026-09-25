"""ConversationState — saved after every turn (architecture §8.2)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

Stage = Literal[
    "greeting", "discovering", "suggesting", "refining",
    "confirming", "handed_off", "nurture", "closed", "opted_out",
]
Language = Literal["en", "ar"]
Channel = Literal["chat", "voice", "whatsapp"]
SlotSource = Literal["import", "buyer", "broker", "inferred"]

REQUIRED_SLOTS: tuple[str, ...] = ("purpose", "budget", "area", "property_type")
QUALIFICATION_SLOTS: tuple[str, ...] = REQUIRED_SLOTS + ("timeline",)
SEARCH_SLOTS: tuple[str, ...] = ("purpose", "budget", "area", "property_type", "bedrooms")

# Priority order for ask_next_field (one field per turn).
ASK_ORDER: tuple[str, ...] = ("purpose", "budget", "area", "property_type", "bedrooms", "timeline", "payment")


class Slot(BaseModel):
    value: Any
    confidence: float = 1.0
    source: SlotSource = "buyer"
    confirmed: bool = False
    updated_turn: int = 0


class ShownProperty(BaseModel):
    property_id: str
    title: str
    price: float | None = None
    area: str | None = None
    community_id: str | None = None
    bedrooms: int | None = None
    property_type: str | None = None
    shown_turn: int
    reaction: Literal["liked", "rejected", "neutral"] | None = None
    reason: str | None = None


class ConversationState(BaseModel):
    lead_id: str
    conversation_id: str | None = None
    channel: Channel = "chat"
    stage: Stage = "greeting"
    language: Language = "en"
    profile: dict[str, Slot] = Field(default_factory=dict)
    shortlist: list[ShownProperty] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    asked: dict[str, int] = Field(default_factory=dict)
    misunderstandings: int = 0
    last_move: str | None = None
    last_asked_field: str | None = None
    turn: int = 0
    score: int = 0
    score_reasons: list[str] = Field(default_factory=list)
    band: Literal["hot", "warm", "cold"] = "cold"
    version: int = 0
    answers: int = 0
    source: str | None = None
    handoff_id: str | None = None
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # ---- helpers -----------------------------------------------------
    def value(self, slot: str) -> Any:
        s = self.profile.get(slot)
        return None if s is None else s.value

    def has(self, slot: str) -> bool:
        return self.value(slot) not in (None, "", [], {})

    def missing_required(self) -> list[str]:
        # A bedroom count is enough to search on when the buyer never named a type.
        return [s for s in REQUIRED_SLOTS if not self.has(s) and not (s == "property_type" and self.has("bedrooms"))]

    def missing_for_qualification(self) -> list[str]:
        return [s for s in QUALIFICATION_SLOTS if not self.has(s)]

    def is_qualified(self) -> bool:
        return not self.missing_for_qualification() and self.score >= 60

    def next_field_to_ask(self, max_asks: int = 2) -> str | None:
        for field_name in ASK_ORDER:
            if field_name in QUALIFICATION_SLOTS and not self.has(field_name):
                if self.asked.get(field_name, 0) < max_asks:
                    return field_name
        return None

    def liked_properties(self) -> list[ShownProperty]:
        return [p for p in self.shortlist if p.reaction == "liked"]

    def current_shortlist(self) -> list[ShownProperty]:
        """Properties shown in the most recent suggest turn."""
        if not self.shortlist:
            return []
        last_turn = max(p.shown_turn for p in self.shortlist)
        return [p for p in self.shortlist if p.shown_turn == last_turn]

    def shortlist_is_stale(self) -> bool:
        """True when a search-relevant slot changed after the last shortlist was shown."""
        current = self.current_shortlist()
        if not current:
            return False
        shown = current[0].shown_turn
        return any(
            (s := self.profile.get(name)) is not None and s.updated_turn > shown
            for name in SEARCH_SLOTS
        )

    def last_shortlist_rejected(self) -> bool:
        current = self.current_shortlist()
        return bool(current) and all(p.reaction == "rejected" for p in current)

    def set_slot(self, name: str, value: Any, *, source: SlotSource = "buyer", confidence: float = 1.0, confirmed: bool = False) -> None:
        self.profile[name] = Slot(
            value=value, confidence=confidence, source=source, confirmed=confirmed, updated_turn=self.turn
        )

    def profile_values(self) -> dict[str, Any]:
        return {k: v.value for k, v in self.profile.items()}
