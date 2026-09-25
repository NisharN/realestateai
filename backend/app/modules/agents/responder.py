"""Responder — phrases the chosen move from FACTS; template fallback always exists."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.modules.conversation import templates
from app.modules.conversation.moves import Move
from app.modules.conversation.state import ConversationState
from app.modules.llm import LLMUnavailable, get_gateway

from . import guard

logger = logging.getLogger(__name__)

PERSONA = (
    "You are a warm, concise property assistant for a licensed Dubai brokerage. "
    "Use ONLY the FACTS block. Never invent listings, prices, distances or dates. "
    "No legal, mortgage-approval or price guarantees. Ask at most one question. "
    "{length_rule} Reply in {language_name} only. Do not mention being an AI unless asked."
)

MOVE_INSTRUCTIONS: dict[Move, str] = {
    Move.GREETING: "Greet briefly and ask the first question given in FACTS.next_question.",
    Move.CLARIFY_BUDGET: "Ask the clarifying budget question in FACTS.budget_question, phrased naturally.",
    Move.CLARIFY_AREA: "Ask which community the buyer meant; offer 3 example communities from FACTS.examples.",
    Move.ANSWER_AREA: "Describe the area using FACTS.area only; you may quote FACTS.area_travel_text verbatim (keep the word approx. if present), then offer to show options.",
    Move.ANSWER_PROPERTY: "Answer about the property using FACTS.property only, then offer a viewing.",
    Move.COMPARE: "Compare the properties in FACTS.compare on price, size and bedrooms; ask which they prefer.",
    Move.HANDLE_OBJECTION: "Acknowledge the objection in FACTS.objection, present the adjusted options in FACTS.cards (count only), ask if better.",
    Move.ASK_NEXT_FIELD: "Acknowledge what the buyer just said in one short clause, then ask FACTS.next_question.",
    Move.SUGGEST: "Introduce the FACTS.cards (say how many, name the area) and ask which they like. Do not list prices individually unless in FACTS.",
    Move.CONFIRM_HANDOFF: "Propose that a specialist calls to arrange a viewing; offer FACTS.slots.",
    Move.HANDOFF: "Confirm the specialist FACTS.broker_name will call at FACTS.slot_text and thank them.",
    Move.HANDOFF_NOW: "Confirm a specialist will contact them shortly.",
    Move.NURTURE: "Politely close, say you will check in nearer their timeline.",
    Move.SMALL_TALK_REDIRECT: "Respond briefly, then steer back with FACTS.next_question.",
    Move.OPT_OUT: "Confirm they will not be contacted again.",
}


async def respond(
    move: Move,
    state: ConversationState,
    facts: dict[str, Any],
    *,
    deadline_s: float | None,
    field: str | None = None,
) -> tuple[str, list[str]]:
    """Return (reply, fallbacks_used)."""
    fallbacks: list[str] = []
    voice = state.channel == "voice"
    max_sentences = 2 if voice else 4
    template_key = None
    if move == Move.SUGGEST and not facts.get("cards"):
        template_key = "suggest_empty"
    elif move == Move.CONFIRM_HANDOFF and not state.shortlist:
        template_key = "confirm_handoff_no_inventory"
    template_reply = templates.render(move, state.language, facts, field=field, key=template_key)

    # Deterministic moves are always templated: no LLM value, and the wording is compliance-sensitive.
    if move in {Move.OPT_OUT, Move.HANDOFF, Move.HANDOFF_NOW, Move.CLARIFY_BUDGET}:
        return template_reply, fallbacks

    gateway = get_gateway()
    if not gateway.available or (deadline_s is not None and deadline_s < 0.4):
        fallbacks.append("template:llm_unavailable")
        return template_reply, fallbacks

    system = PERSONA.format(
        length_rule="Maximum 2 short sentences." if voice else "Maximum 4 sentences.",
        language_name="Arabic" if state.language == "ar" else "English",
    )
    user = (
        f"MOVE: {move.value}\nINSTRUCTION: {MOVE_INSTRUCTIONS.get(move, '')}\n"
        f"FACTS: {json.dumps(_compact(facts), ensure_ascii=False, default=str)}\n"
        f"TEMPLATE_IF_UNSURE: {template_reply}"
    )
    try:
        completion = await gateway.complete_text(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            deadline_s=deadline_s,
            tier="fast",
            max_tokens=160 if voice else 260,
            purpose=f"respond.{move.value}",
        )
    except LLMUnavailable as exc:
        logger.info("responder: llm unavailable (%s)", exc)
        fallbacks.append("template:llm_unavailable")
        return template_reply, fallbacks

    checked = guard.check(completion.text, facts, language=state.language, max_sentences=max_sentences)
    if checked is None:
        fallbacks.append("template:guard_rejected")
        return template_reply, fallbacks
    return checked, fallbacks


def _compact(facts: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in facts.items():
        if v in (None, "", [], {}):
            continue
        if k == "cards" and isinstance(v, list):
            out[k] = [{kk: c.get(kk) for kk in ("title", "price", "area", "bedrooms", "property_type")} for c in v[:3]]
        else:
            out[k] = v
    return out
