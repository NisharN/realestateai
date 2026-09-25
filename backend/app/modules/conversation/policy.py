"""Next-move decision table — pure function, evaluated top to bottom (§8.5)."""
from __future__ import annotations

from dataclasses import dataclass

from .facts import ExtractedFacts
from .moves import Move
from .state import ConversationState

LONG_TIMELINES = {"later"}
MAX_ASKS = 2


@dataclass(frozen=True)
class Decision:
    move: Move
    rule: int
    field: str | None = None  # for ask_next_field / clarify_*
    reason: str = ""


def decide(state: ConversationState, facts: ExtractedFacts) -> Decision:
    intent = facts.intent

    # 1 — STOP always wins.
    if intent == "stop":
        return Decision(Move.OPT_OUT, 1, reason="buyer asked to stop")

    # 2 — explicit human request or the AI keeps misunderstanding.
    if intent == "request_human":
        return Decision(Move.HANDOFF_NOW, 2, reason="buyer asked for a human")
    if state.misunderstandings >= 2:
        return Decision(Move.HANDOFF_NOW, 2, reason="two misunderstandings in a row")

    if intent == "goodbye":
        return Decision(Move.GOODBYE, 2, reason="buyer signed off")

    # First contact: greet and ask the first field.
    if state.turn <= 1 and state.stage == "greeting" and intent in {"smalltalk", "unclear"} and not state.profile:
        return Decision(Move.GREETING, 0, field=state.next_field_to_ask(MAX_ASKS))

    # 3 — money is never guessed.
    if facts.budget_ambiguous and state.asked.get("budget_clarify", 0) < MAX_ASKS:
        return Decision(Move.CLARIFY_BUDGET, 3, field="budget", reason="budget currency/period ambiguous")

    # 4 — the buyer named a place we could not resolve.
    if facts.area_unresolved and not facts.area_candidates and state.asked.get("area_clarify", 0) < MAX_ASKS:
        return Decision(Move.CLARIFY_AREA, 4, field="area", reason="area not in gazetteer")

    # 5–8 — questions and pushback take priority over discovery.
    if intent == "ask_area":
        return Decision(Move.ANSWER_AREA, 5)
    if intent == "ask_property":
        return Decision(Move.ANSWER_PROPERTY, 6)
    if intent == "compare":
        return Decision(Move.COMPARE, 7)
    if intent == "objection" or facts.objection:
        return Decision(Move.HANDLE_OBJECTION, 8, reason=facts.objection or "objection")

    # 11 — a liked property or a viewing request moves to confirmation
    #      (checked before 9/10 so a keen buyer is never re-interrogated).
    liked_now = any(r.reaction == "liked" for r in facts.reactions)
    if intent == "request_viewing" or liked_now:
        if state.stage != "confirming":
            return Decision(Move.CONFIRM_HANDOFF, 11, reason="viewing requested or property liked")

    # 12 — buyer agreed to the specialist call.
    if state.stage == "confirming" and intent in {"agree", "request_viewing"}:
        return Decision(Move.HANDOFF, 12, reason="buyer confirmed handoff")

    # 13 — cold: not interested or far horizon.
    if intent == "not_interested":
        return Decision(Move.NURTURE, 13, reason="not interested")
    timeline = state.value("timeline")
    if timeline in LONG_TIMELINES:
        return Decision(Move.NURTURE, 13, reason="timeline over 12 months")

    # 9 — discovery, one field at a time, never more than twice. A required
    #     slot the buyer has sidestepped twice stops blocking the search.
    missing = state.missing_required()
    if missing:
        field = state.next_field_to_ask(MAX_ASKS)
        if field is not None:
            return Decision(Move.ASK_NEXT_FIELD, 9, field=field, reason=f"missing {', '.join(missing)}")
        missing = [m for m in missing if state.asked.get(m, 0) < MAX_ASKS]

    # 10 — everything needed is known: show inventory.
    if not missing and (not state.shortlist or state.last_shortlist_rejected() or state.shortlist_is_stale()):
        if state.asked.get("suggest_empty", 0) >= 2 and state.stage != "confirming":
            return Decision(Move.CONFIRM_HANDOFF, 10, reason="no inventory twice; offer specialist search")
        return Decision(Move.SUGGEST, 10, reason="required slots known")

    # If we are confirming and the buyer said no, go back to refining.
    if state.stage == "confirming" and intent == "disagree":
        return Decision(Move.SUGGEST, 10, reason="buyer declined handoff, refine shortlist")

    # Shortlist shown and the buyer is positive or fully qualified: offer the call.
    if state.shortlist and state.stage != "confirming" and (intent == "agree" or state.is_qualified()):
        return Decision(Move.CONFIRM_HANDOFF, 11, reason="qualified after shortlist")

    # Timeline/payment still unknown after suggestions: ask (bounded).
    field = state.next_field_to_ask(MAX_ASKS)
    if field is not None and intent == "provide_info":
        return Decision(Move.ASK_NEXT_FIELD, 9, field=field, reason=f"qualification slot {field} missing")

    # 14
    return Decision(Move.SMALL_TALK_REDIRECT, 14)
