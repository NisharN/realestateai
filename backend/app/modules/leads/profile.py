"""Profile merge rules: facts → ConversationState slots (architecture §6.3 / §8.3).

Rules: never overwrite with null; buyer's own words beat imported values;
newer + more specific wins; money only via ``extract_budget``.
"""
from __future__ import annotations

import re
from typing import Any

from app.modules.conversation.facts import ExtractedFacts
from app.modules.conversation.state import ConversationState
from app.modules.geo.communities import get_community
from app.services.budget_extraction import extract_budget

MARKET_CURRENCY = "AED"


def merge(state: ConversationState, facts: ExtractedFacts) -> ConversationState:
    """Apply extracted facts to the state in place and return it."""
    slots = facts.slots
    state.language = facts.language

    if slots.purpose:
        _set(state, "purpose", slots.purpose)
    if slots.property_type:
        _set(state, "property_type", slots.property_type)
    if slots.bedrooms is not None:
        _set(state, "bedrooms", slots.bedrooms)
    if slots.timeline and slots.timeline != "unknown":
        _set(state, "timeline", slots.timeline)
    if slots.payment and slots.payment != "unknown":
        _set(state, "payment", slots.payment)
    if slots.end_use:
        _set(state, "end_use", slots.end_use)
    if slots.name:
        _set(state, "name", slots.name)
    if slots.must_haves:
        existing = list(state.value("must_haves") or [])
        for item in slots.must_haves:
            if item not in existing:
                existing.append(item)
        _set(state, "must_haves", existing)
    if slots.location_prefs:
        merged = {**(state.value("location_prefs") or {}), **slots.location_prefs}
        _set(state, "location_prefs", merged)

    if facts.area_candidates:
        names = [c.name_en for cid in facts.area_candidates if (c := get_community(cid))]
        _set(state, "area", names, confidence=1.0)
        _set(state, "community_ids", list(facts.area_candidates))

    if slots.budget_text:
        _merge_budget(state, facts, slots.budget_text)

    # reactions ---------------------------------------------------------
    for r in facts.reactions:
        for shown in state.shortlist:
            if shown.property_id == r.property_id:
                shown.reaction = r.reaction
                shown.reason = r.reason
    if facts.objection and facts.objection not in state.objections:
        state.objections.append(facts.objection)

    if facts.intent == "request_viewing":
        _set(state, "viewing_requested", True)

    if facts.intent in {"provide_info", "agree", "disagree", "objection", "request_viewing"}:
        state.answers += 1
    return state


_MAGNITUDE = re.compile(r"\b(million|mil|m|مليون)\b|\b(thousand|k|ألف|الف)\b", re.I)
_PERIOD = re.compile(r"\b(per (year|annum)|yearly|annual(ly)?|to rent|rent(al)?|سنوي|إيجار|اجار)\b|\b(total|purchase|to buy|buy(ing)?|شراء|إجمالي)\b", re.I)


_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_AR_MONEY = (("مليون", " million "), ("ألف", " thousand "), ("الف", " thousand "), ("درهم", " AED "), ("دراهم", " AED "), ("سنوياً", " per year "), ("سنوي", " per year "), ("في السنة", " per year "), ("شهرياً", " per month "), ("للشراء", " to buy "), ("شراء", " buy "), ("للإيجار", " to rent "), ("إيجار", " rent "))


def normalise_money_text(text: str) -> str:
    out = text.translate(_AR_DIGITS)
    for ar, en in _AR_MONEY:
        out = out.replace(ar, en)
    return out


def _merge_budget(state: ConversationState, facts: ExtractedFacts, text: str) -> None:
    text = normalise_money_text(text)
    extraction = extract_budget(text)
    pending = state.value("budget_pending")
    if extraction.amount_max is None and pending:
        # Buyer is answering our clarification ("million", "to buy", "per year").
        extraction.amount_min = pending.get("amount_min")
        extraction.amount_max = pending.get("amount_max")
        extraction.currency = pending.get("currency")
        mag = _MAGNITUDE.search(text)
        if mag and extraction.amount_max is not None and extraction.amount_max < 1000:
            factor = 1_000_000 if mag.group(1) else 1_000
            extraction.amount_min = (extraction.amount_min or extraction.amount_max) * factor
            extraction.amount_max = extraction.amount_max * factor
        per = _PERIOD.search(text)
        if per:
            extraction.period = "year" if per.group(1) else "total"
            if extraction.intent is None:
                extraction.intent = "rent" if per.group(1) else "buy"
    if extraction.amount_max is None:
        return
    purpose = state.value("purpose") or (extraction.intent if extraction.intent else None)
    if extraction.period is None and purpose:
        extraction.period = "total" if purpose in {"buy", "invest"} else "year"
    currency_assumed = False
    if extraction.currency is None:
        extraction.currency = MARKET_CURRENCY
        currency_assumed = True

    bare = extraction.amount_max < 1000
    ambiguous = extraction.period is None or bare
    if ambiguous:
        facts.budget_ambiguous = True
        questions: list[str] = []
        if bare:
            questions.append(f"is that {extraction.amount_max:g} million or {extraction.amount_max:g} thousand?")
        if extraction.period is None:
            questions.append("is that the total price to buy, or per year to rent?")
        if state.language == "ar":
            ar_q: list[str] = []
            if bare:
                ar_q.append(f"هل تقصد {extraction.amount_max:g} مليون أم {extraction.amount_max:g} ألف؟")
            if extraction.period is None:
                ar_q.append("هل هو سعر الشراء الإجمالي أم الإيجار السنوي؟")
            facts.budget_question = "للتأكد من الميزانية — " + " و".join(ar_q)
        else:
            facts.budget_question = "Just to confirm your budget — " + " And ".join(questions)
        state.set_slot(
            "budget_pending",
            {"amount_min": extraction.amount_min, "amount_max": extraction.amount_max, "currency": extraction.currency},
            confidence=0.5,
        )
        return

    state.profile.pop("budget_pending", None)

    if extraction.intent and not state.has("purpose"):
        _set(state, "purpose", extraction.intent, confidence=0.9)
    _set(
        state,
        "budget",
        {
            "min_aed": extraction.amount_min_aed,
            "max_aed": extraction.amount_max_aed,
            "currency": extraction.currency,
            "period": extraction.period,
            "currency_assumed": currency_assumed,
            "text": text.strip()[:120],
        },
        confidence=0.85 if currency_assumed else 1.0,
    )


def _set(state: ConversationState, name: str, value: Any, *, confidence: float = 1.0) -> None:
    if value in (None, "", [], {}):
        return
    existing = state.profile.get(name)
    if existing is not None and existing.source == "buyer" and existing.confirmed and existing.value == value:
        return
    state.set_slot(name, value, source="buyer", confidence=confidence)


def lead_updates_from_state(state: ConversationState) -> dict[str, Any]:
    """Columns on ``leads`` that mirror the profile (for dashboards/CRM)."""
    budget = state.value("budget") or {}
    updates: dict[str, Any] = {
        "language": state.language,
        "score": state.score,
        "score_reasons": state.score_reasons,
        "band": state.band,
        "stage": state.stage,
    }
    if state.has("purpose"):
        updates["purpose"] = state.value("purpose")
    if budget:
        updates["budget_min_aed"] = budget.get("min_aed")
        updates["budget_max_aed"] = budget.get("max_aed")
        updates["budget_period"] = budget.get("period")
    if state.has("community_ids"):
        updates["community_ids"] = state.value("community_ids")
    if state.has("property_type"):
        updates["property_types"] = [state.value("property_type")]
    if state.has("bedrooms"):
        updates["bedrooms_min"] = state.value("bedrooms")
    if state.has("timeline"):
        updates["timeline"] = state.value("timeline")
    if state.has("payment"):
        updates["payment"] = state.value("payment")
    if state.has("must_haves"):
        updates["must_haves"] = state.value("must_haves")
    if state.has("location_prefs"):
        updates["location_prefs"] = state.value("location_prefs")
    return updates
