"""Deterministic lead scoring with human-readable reasons (architecture §8.6)."""
from __future__ import annotations

from typing import Any, Literal

from app.modules.conversation.state import ConversationState

DEFAULT_WEIGHTS: dict[str, int] = {
    "budget_known": 20,
    "timeline_lt_3m": 20,
    "timeline_3_6m": 10,
    "timeline_later": 3,
    "payment_ready": 15,
    "payment_mortgage_not_started": 7,
    "area_and_type": 10,
    "engagement": 10,
    "viewing_or_price": 15,
    "source_max": 10,
}

SOURCE_QUALITY: dict[str, int] = {
    "referral": 10,
    "listing_enquiry": 9,
    "propertyfinder": 9,
    "bayut": 9,
    "dubizzle": 8,
    "website": 7,
    "whatsapp": 7,
    "crm": 6,
    "walk_in": 8,
    "ad_form": 4,
    "facebook": 4,
    "instagram": 4,
    "google_ads": 5,
    "csv": 5,
    "webhook": 5,
    "unknown": 3,
}

# Sanity band for AED budgets per purpose so "1 AED" or "9 billion" does not score.
REALISTIC_AED = {
    "buy": (300_000, 500_000_000),
    "invest": (300_000, 500_000_000),
    "rent": (20_000, 5_000_000),
}


def band_for(score: int) -> Literal["hot", "warm", "cold"]:
    if score >= 70:
        return "hot"
    if score >= 40:
        return "warm"
    return "cold"


def score(state: ConversationState, weights: dict[str, int] | None = None) -> tuple[int, list[str]]:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    points = 0
    reasons: list[str] = []

    budget: dict[str, Any] = state.value("budget") or {}
    max_aed = budget.get("max_aed")
    purpose = state.value("purpose") or "buy"
    if max_aed:
        lo, hi = REALISTIC_AED.get(purpose, REALISTIC_AED["buy"])
        if lo <= max_aed <= hi:
            points += w["budget_known"]
            reasons.append(f"Budget known and realistic (AED {max_aed:,.0f})")
        else:
            reasons.append(f"Budget AED {max_aed:,.0f} outside realistic range for {purpose}")

    timeline = state.value("timeline")
    if timeline in {"asap", "1_month", "3_months"}:
        points += w["timeline_lt_3m"]
        reasons.append("Timeline under 3 months")
    elif timeline == "6_months":
        points += w["timeline_3_6m"]
        reasons.append("Timeline 3–6 months")
    elif timeline in {"12_months", "later"}:
        points += w["timeline_later"]
        reasons.append("Timeline later than 6 months")

    payment = state.value("payment")
    if payment in {"cash", "mortgage_preapproved"}:
        points += w["payment_ready"]
        reasons.append("Cash or mortgage pre-approved")
    elif payment == "mortgage_not_started":
        points += w["payment_mortgage_not_started"]
        reasons.append("Mortgage not yet started")

    if state.has("area") and state.has("property_type"):
        points += w["area_and_type"]
        reasons.append("Area and property type known")

    reacted = any(p.reaction for p in state.shortlist)
    if state.answers >= 3 or reacted:
        points += w["engagement"]
        reasons.append("Engaged: answered questions or reacted to listings")

    if state.value("viewing_requested") or state.liked_properties() or state.value("asked_price"):
        points += w["viewing_or_price"]
        reasons.append("Asked for a viewing, call or price details")

    src = (state.source or "unknown").lower()
    src_points = min(SOURCE_QUALITY.get(src, SOURCE_QUALITY["unknown"]), w["source_max"])
    points += src_points
    reasons.append(f"Source quality: {src} (+{src_points})")

    total = max(0, min(points, 100))
    return total, reasons
