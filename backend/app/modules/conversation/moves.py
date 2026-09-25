"""Move enum and the tools each move needs (architecture §8.5)."""
from __future__ import annotations

from enum import Enum


class Move(str, Enum):
    OPT_OUT = "opt_out"
    HANDOFF_NOW = "handoff_now"
    CLARIFY_BUDGET = "clarify_budget"
    CLARIFY_AREA = "clarify_area"
    ANSWER_AREA = "answer_area"
    ANSWER_PROPERTY = "answer_property"
    COMPARE = "compare"
    HANDLE_OBJECTION = "handle_objection"
    ASK_NEXT_FIELD = "ask_next_field"
    SUGGEST = "suggest"
    CONFIRM_HANDOFF = "confirm_handoff"
    HANDOFF = "handoff"
    NURTURE = "nurture"
    SMALL_TALK_REDIRECT = "small_talk_redirect"
    GREETING = "greeting"


TOOLS_FOR_MOVE: dict[Move, tuple[str, ...]] = {
    Move.OPT_OUT: ("suppress",),
    Move.HANDOFF_NOW: ("route_broker", "brief"),
    Move.CLARIFY_BUDGET: (),
    Move.CLARIFY_AREA: ("resolve_area",),
    Move.ANSWER_AREA: ("area_profile",),
    Move.ANSWER_PROPERTY: ("property_details",),
    Move.COMPARE: ("compare",),
    Move.HANDLE_OBJECTION: ("property_search_relaxed",),
    Move.ASK_NEXT_FIELD: (),
    Move.SUGGEST: ("property_search",),
    Move.CONFIRM_HANDOFF: ("viewing_slots",),
    Move.HANDOFF: ("route_broker", "brief", "notify"),
    Move.NURTURE: ("followup_schedule",),
    Move.SMALL_TALK_REDIRECT: (),
    Move.GREETING: (),
}

# Moves that end the AI's active role in the conversation.
TERMINAL_MOVES = {Move.OPT_OUT, Move.HANDOFF_NOW, Move.HANDOFF}
