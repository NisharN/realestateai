"""Broker brief: deterministic structure, optional LLM prose, always persisted."""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.modules.conversation.state import ConversationState
from app.modules.llm import LLMUnavailable, get_gateway

logger = logging.getLogger(__name__)

TIMELINE_LABEL = {
    "asap": "ASAP", "1_month": "within 1 month", "3_months": "within 3 months",
    "6_months": "3–6 months", "12_months": "6–12 months", "later": "12+ months", "unknown": "unknown",
}
PAYMENT_LABEL = {
    "cash": "cash", "mortgage_preapproved": "mortgage (pre-approved)",
    "mortgage_not_started": "mortgage (not started)", "unknown": "unknown",
}


class BrokerBrief(BaseModel):
    headline: str
    profile: dict[str, Any]
    budget_text: str
    score: int
    band: str
    score_reasons: list[str]
    liked: list[dict[str, Any]] = Field(default_factory=list)
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    next_step: str
    language: str
    suggested_opening: str
    summary: str
    generated_by: str = "template"


def budget_text(state: ConversationState) -> str:
    b = state.value("budget") or {}
    if not b:
        return "not stated"
    lo, hi, period = b.get("min_aed"), b.get("max_aed"), b.get("period")
    if lo and hi and lo != hi:
        amount = f"AED {lo:,.0f}–{hi:,.0f}"
    elif hi:
        amount = f"AED {hi:,.0f}"
    else:
        return b.get("text") or "not stated"
    return f"{amount} per year" if period == "year" else amount


def build_brief(state: ConversationState, lead: dict[str, Any], *, reason: str) -> BrokerBrief:
    areas = state.value("area") or []
    ptype = state.value("property_type") or "property"
    beds = state.value("bedrooms")
    purpose = state.value("purpose") or "buy"
    name = lead.get("name") or state.value("name") or "Buyer"
    beds_txt = f"{beds}BR " if beds is not None else ""
    area_txt = ", ".join(areas) if areas else "area not fixed"
    headline = f"{name}: {purpose} {beds_txt}{ptype} in {area_txt}, {budget_text(state)}"

    liked = [p.model_dump() for p in state.shortlist if p.reaction == "liked"]
    rejected = [p.model_dump() for p in state.shortlist if p.reaction == "rejected"]
    if state.value("viewing_requested") or liked:
        next_step = "Call to arrange a viewing" + (f" of {liked[0]['title']}" if liked else "")
    elif reason == "request_human":
        next_step = "Buyer asked for a person — call within 15 minutes"
    else:
        next_step = "Introduce yourself and confirm the brief"

    timeline = TIMELINE_LABEL.get(state.value("timeline") or "unknown", "unknown")
    payment = PAYMENT_LABEL.get(state.value("payment") or "unknown", "unknown")
    opening = (
        f"Hi {name}, this is {{broker}} from {{brokerage}}. You were looking at {beds_txt}{ptype}s in {area_txt} "
        f"around {budget_text(state)} — I'd love to line up a viewing. When suits you?"
    )
    summary_lines = [
        headline,
        f"Timeline: {timeline}. Payment: {payment}. Score {state.score}/100 ({state.band}).",
    ]
    if liked:
        summary_lines.append("Liked: " + "; ".join(p["title"] for p in liked))
    if rejected:
        summary_lines.append("Rejected: " + "; ".join(f"{p['title']} ({p.get('reason') or 'no reason'})" for p in rejected))
    if state.objections:
        summary_lines.append("Objections: " + ", ".join(state.objections))
    summary_lines.append("Next: " + next_step)

    return BrokerBrief(
        headline=headline,
        profile={**state.profile_values(), "timeline_label": timeline, "payment_label": payment},
        budget_text=budget_text(state),
        score=state.score,
        band=state.band,
        score_reasons=list(state.score_reasons),
        liked=liked,
        rejected=rejected,
        objections=list(state.objections),
        next_step=next_step,
        language=state.language,
        suggested_opening=opening,
        summary="\n".join(summary_lines),
    )


async def polish_brief(brief: BrokerBrief, transcript: list[dict[str, str]], deadline_s: float = 3.0) -> BrokerBrief:
    """Ask the LLM for a tighter summary; keep the template on any failure."""
    gateway = get_gateway()
    if not gateway.available:
        return brief
    messages = [
        {"role": "system", "content": "Write a 4-line broker brief in English using ONLY the facts given. No new numbers, no promises. Plain text."},
        {"role": "user", "content": f"FACTS:\n{brief.summary}\n\nTRANSCRIPT (last turns):\n{json.dumps(transcript[-8:], ensure_ascii=False)}"},
    ]
    try:
        completion = await gateway.complete_text(messages, deadline_s=deadline_s, max_tokens=220, temperature=0.2, purpose="brief")
    except LLMUnavailable:
        return brief
    text = completion.text.strip()
    if 40 <= len(text) <= 900 and "guarantee" not in text.lower():
        return brief.model_copy(update={"summary": text, "generated_by": completion.provider})
    return brief
