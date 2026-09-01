"""Listing refresh copy generator.

The broker named listing staleness as the single most tedious job in her
office — listings sink in portal search rank unless refreshed, and portals
penalise duplicate content, so each refresh means rewriting the description
from scratch. Her actual words on what the pain is: "The reminder isn't the
hard part. The hard part is I open the listing and stare at it for ten minutes
trying to write a *new* description that doesn't sound identical to the old
one."

So this generates the copy. It does **not** post anything. Automating a
repost to Bayut / Property Finder / Dubizzle without an API agreement is the
same terms-of-service exposure as scraping, and a banned customer account
would be an existential trust problem — the consultant refused it and the PM
agreed. The broker copies the output and posts it herself.

Works with or without an LLM: the deterministic template path produces usable,
varied copy on its own, and Groq is used only to polish when configured.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# Rotated by refresh count so consecutive refreshes never open the same way —
# duplicate-content penalties are the whole reason this exists.
OPENERS = [
    "Now available in {area} — {headline}.",
    "Just refreshed: {headline}, right in the heart of {area}.",
    "{area} opportunity — {headline}.",
    "New to market this week in {area}: {headline}.",
    "Priced to move in {area}: {headline}.",
    "A rare find in {area} — {headline}.",
]

CLOSERS = [
    "Viewings are open this week — message to book a slot.",
    "Happy to arrange a viewing at short notice.",
    "Serious enquiries welcome — I can share the full floor plan on request.",
    "Available to view daily, including weekends.",
    "Message for the full photo set and payment plan details.",
    "Ready to hand over — book a viewing before the weekend rush.",
]

ANGLES = [
    "investor",
    "end_user",
    "family",
    "value",
]

ANGLE_LINES = {
    "investor": "Strong rental demand in this community makes it a solid yield play.",
    "end_user": "Move-in ready, with the finish quality you'd expect at this level.",
    "family": "Well suited to families, with schools and parks close by.",
    "value": "Competitively priced against comparable units in the same building.",
}


@dataclass
class RefreshedCopy:
    """A ready-to-paste listing description plus why it was generated."""

    property_id: str
    title: str
    description: str
    days_stale: int
    variant: int
    angle: str
    price_note: Optional[str] = None
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "property_id": self.property_id,
            "title": self.title,
            "description": self.description,
            "days_stale": self.days_stale,
            "variant": self.variant,
            "angle": self.angle,
            "price_note": self.price_note,
            "generated_at": self.generated_at,
        }


def _variant_index(property_id: str, refresh_count: int, size: int, salt: str = "") -> int:
    """Deterministic rotation that never repeats on consecutive refreshes.

    A pure hash of (id, count) can collide — two refreshes in a row landing on
    the same opener, which is precisely the duplicate-content problem this
    feature exists to avoid. So the offset is seeded off the property id (so
    two different listings refreshed the same day don't read identically) but
    the step is sequential, guaranteeing a full cycle before any repeat.
    """
    seed = hashlib.md5(f"{property_id}:{salt}".encode()).hexdigest()
    offset = int(seed[:8], 16)
    return (offset + refresh_count) % size


def _headline(listing: Mapping[str, Any]) -> str:
    beds = listing.get("bedrooms")
    ptype = (listing.get("property_type") or "property").replace("_", " ")
    size = listing.get("size_sqft")
    parts: List[str] = []
    if beds:
        parts.append(f"{beds}-bedroom {ptype}")
    else:
        parts.append(str(ptype))
    if size:
        parts.append(f"{int(size):,} sqft")
    return ", ".join(parts)


def _price_note(
    listing: Mapping[str, Any],
    comparable_median: Optional[float],
) -> Optional[str]:
    """Position the price against comps, when we have them.

    This is the bit that turns a rewrite into an argument the broker can use
    in a price objection — which is what the DLD comps data is for.
    """
    price = listing.get("price")
    if not price or not comparable_median:
        return None
    delta = (float(price) - comparable_median) / comparable_median
    if delta <= -0.07:
        return (
            f"Priced roughly {abs(delta) * 100:.0f}% below recent comparable "
            "sales in the area."
        )
    if delta >= 0.07:
        return (
            "Premium unit — priced above recent comparables, justified on "
            "finish and floor level."
        )
    return "Priced in line with recent comparable transactions in the community."


def generate_refresh_copy(
    listing: Mapping[str, Any],
    days_stale: int,
    refresh_count: int = 0,
    comparable_median: Optional[float] = None,
) -> RefreshedCopy:
    """Build a fresh, non-duplicate description for an existing listing."""
    property_id = str(listing.get("id") or "")
    area = listing.get("area") or "Dubai"
    headline = _headline(listing)

    opener_idx = _variant_index(property_id, refresh_count, len(OPENERS), "opener")
    closer_idx = _variant_index(property_id, refresh_count, len(CLOSERS), "closer")
    angle_idx = _variant_index(property_id, refresh_count, len(ANGLES), "angle")
    angle = ANGLES[angle_idx]

    opener = OPENERS[opener_idx].format(area=area, headline=headline)
    closer = CLOSERS[closer_idx]
    price_note = _price_note(listing, comparable_median)

    # Don't say the same thing twice: the "value" angle and the comps-based
    # price note make the same point, so drop the generic one when we have
    # the specific one.
    angle_line = "" if (angle == "value" and price_note) else ANGLE_LINES[angle]

    amenities = listing.get("amenities") or []
    amenity_line = ""
    if amenities:
        picked = [str(a) for a in list(amenities)[:3]]
        amenity_line = f"Building amenities include {', '.join(picked)}. "

    body = " ".join(
        part for part in [opener, angle_line, amenity_line.strip(), price_note, closer] if part
    )

    return RefreshedCopy(
        property_id=property_id,
        title=str(listing.get("title") or headline),
        description=body,
        days_stale=days_stale,
        variant=opener_idx,
        angle=angle,
        price_note=price_note,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


async def polish_with_llm(copy: RefreshedCopy) -> RefreshedCopy:
    """Optionally rewrite the generated copy more naturally via Groq.

    Never required. If no key is configured or the call fails, the template
    output stands on its own — the feature must not silently stop working just
    because an LLM is unavailable.
    """
    settings = get_settings()
    if not settings.GROQ_API_KEY:
        return copy

    try:
        from langchain_groq import ChatGroq

        llm = ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL_FAST,
            temperature=0.7,
        )
        prompt = (
            "Rewrite this Dubai property listing description so it reads naturally "
            "and does not duplicate the original phrasing. Keep every fact "
            "unchanged, keep it under 80 words, no emojis, no invented features.\n\n"
            f"{copy.description}"
        )
        response = await llm.ainvoke(prompt)
        text = getattr(response, "content", "") or ""
        if text.strip():
            copy.description = text.strip()
    except Exception as exc:
        logger.warning("Listing copy polish skipped: %s", exc)

    return copy
