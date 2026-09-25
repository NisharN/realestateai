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


# ---------------------------------------------------------------------------
# Jev (TypeSafe AI) qualification layered on the deterministic score.
# ---------------------------------------------------------------------------

def lead_state_for_jev(state: ConversationState, recent_messages: list[str] | None = None) -> dict[str, Any]:
    """Compact JSON view of the lead that Jev judges. No PII beyond the conversation itself."""
    return {
        "purpose": state.value("purpose"),
        "budget_aed": state.value("budget"),
        "timeline": state.value("timeline"),
        "payment": state.value("payment"),
        "area": state.value("area"),
        "property_type": state.value("property_type"),
        "bedrooms": state.value("bedrooms"),
        "viewing_requested": bool(state.value("viewing_requested")),
        "asked_price": bool(state.value("asked_price")),
        "liked_listings": len(state.liked_properties()),
        "listings_shown": len(state.shortlist),
        "objections": list(state.objections)[:5],
        "answers_given": state.answers,
        "turns": state.turn,
        "language": state.language,
        "source": state.source or "unknown",
        "stage": state.stage,
        "recent_messages": (recent_messages or [])[-6:],
    }


class Qualification:
    __slots__ = ("band", "jev", "provider", "reasons", "score")

    def __init__(self, score: int, band: str, reasons: list[str], provider: str, jev: dict[str, Any] | None = None) -> None:
        self.score, self.band, self.reasons, self.provider, self.jev = score, band, reasons, provider, jev


def scoring_provider() -> str:
    from app.config import get_settings

    s = get_settings()
    mode = (s.LEAD_SCORING_PROVIDER or "auto").lower()
    if mode == "rules":
        return "rules"
    if mode == "jev" or (mode == "auto" and s.TYPESAFE_API_KEY):
        return "jev"
    return "rules"


async def qualify(state: ConversationState, *, recent_messages: list[str] | None = None, fallbacks: list[str] | None = None) -> Qualification:
    """Score with rules, then let Jev re-band when it is configured and confident.

    Jev never lowers a lead below the deterministic evidence by more than one band and
    never raises a lead that has no budget and no timeline to hot; the rules stay the floor.
    """
    from app.config import get_settings
    from app.modules.llm import jev as jev_client

    base_score, base_reasons = score(state)
    base_band = band_for(base_score)
    if scoring_provider() != "jev":
        return Qualification(base_score, base_band, base_reasons, "rules")
    try:
        j = await jev_client.qualify(lead_state_for_jev(state, recent_messages))
    except jev_client.JevUnavailable as exc:
        if fallbacks is not None:
            fallbacks.append("score:rules_only")
        return Qualification(base_score, base_band, base_reasons + [f"Jev unavailable ({exc}); deterministic score used"], "rules")

    if j.band_confidence < get_settings().JEV_MIN_CONFIDENCE:
        return Qualification(base_score, base_band, base_reasons + [f"Jev low confidence ({j.band_confidence:.0%}); deterministic band kept"], "rules", j.as_dict())

    order = ["cold", "warm", "hot"]
    target = order.index(j.band)
    current = order.index(base_band)
    target = max(target, current - 1)
    if j.band == "hot" and not (state.has("budget") or state.has("timeline")):
        target = min(target, order.index("warm"))
    band = order[target]
    blended = round(0.5 * base_score + 0.5 * j.score)
    lo, hi = {"cold": (0, 39), "warm": (40, 69), "hot": (70, 100)}[band]
    final = max(lo, min(blended, hi))
    return Qualification(final, band, j.reasons + base_reasons, "jev", j.as_dict())
