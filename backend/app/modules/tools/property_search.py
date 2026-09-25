"""property_search tool — real inventory only, never synthetic listings."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import get_property_repository
from app.modules.conversation.state import ConversationState, ShownProperty
from app.modules.geo.communities import get_community

logger = logging.getLogger(__name__)

DEMO_SOURCES = {"demo", "mock_seed", "seed"}
TOOL_TIMEOUT_S = 1.5


class PropertyQuery(BaseModel):
    areas: list[str] = Field(default_factory=list)
    community_ids: list[str] = Field(default_factory=list)
    property_type: str | None = None
    bedrooms: int | None = None
    min_price: float | None = None
    max_price: float | None = None
    purpose: str | None = None
    exclude_ids: list[str] = Field(default_factory=list)
    limit: int = 3


class PropertyCard(BaseModel):
    property_id: str
    title: str
    price: float | None
    area: str | None
    community_id: str | None
    bedrooms: int | None
    bathrooms: int | None = None
    size_sqft: int | None = None
    property_type: str | None
    image: str | None = None
    lat: float | None = None
    lng: float | None = None
    match_reasons: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    cards: list[PropertyCard]
    total_considered: int
    relaxed: list[str] = Field(default_factory=list)  # which filters were relaxed


def query_from_state(state: ConversationState, *, relax: str | None = None) -> PropertyQuery:
    budget = state.value("budget") or {}
    max_aed = budget.get("max_aed")
    min_aed = budget.get("min_aed")
    q = PropertyQuery(
        areas=list(state.value("area") or []),
        community_ids=list(state.value("community_ids") or []),
        property_type=state.value("property_type"),
        bedrooms=state.value("bedrooms"),
        purpose=state.value("purpose"),
        max_price=max_aed * 1.1 if max_aed else None,
        min_price=min_aed * 0.6 if min_aed and max_aed and min_aed != max_aed else None,
        exclude_ids=[p.property_id for p in state.shortlist if p.reaction == "rejected"],
    )
    if relax == "price" and q.max_price:
        q.max_price = q.max_price * 1.15
    if relax == "size" and q.bedrooms is not None:
        q.bedrooms = q.bedrooms + 1
    if relax == "location":
        q.areas, q.community_ids = [], []
    return q


def _is_live_ok(prop: dict[str, Any]) -> bool:
    if get_settings().properties_mode == "mock":
        return True
    return (prop.get("source") or "").lower() not in DEMO_SOURCES


def _to_card(prop: dict[str, Any], reasons: list[str]) -> PropertyCard:
    images = prop.get("images") or []
    return PropertyCard(
        property_id=str(prop.get("id")),
        title=prop.get("title") or "Listing",
        price=prop.get("price"),
        area=prop.get("area"),
        community_id=prop.get("community_id"),
        bedrooms=prop.get("bedrooms"),
        bathrooms=prop.get("bathrooms"),
        size_sqft=prop.get("size_sqft"),
        property_type=prop.get("property_type"),
        image=images[0] if images else None,
        lat=prop.get("map_lat"),
        lng=prop.get("map_lng"),
        match_reasons=reasons,
    )


PURPOSE_LISTING_TYPE = {"buy": "sale", "invest": "sale", "rent": "rent"}


async def search(query: PropertyQuery, workspace_id: str) -> SearchResult:
    repo = get_property_repository(workspace_id)
    area_terms: list[str] = list(query.areas)
    for cid in query.community_ids:
        c = get_community(cid)
        if c and c.name_en not in area_terms:
            area_terms.append(c.name_en)
            area_terms.extend(a for a in c.aliases if len(a) > 3)

    listing_type = PURPOSE_LISTING_TYPE.get(query.purpose or "")

    async def _search(area: str | None) -> list[dict[str, Any]]:
        try:
            return await asyncio.wait_for(
                repo.search_by_criteria(
                    area=area,
                    property_type=query.property_type,
                    min_price=query.min_price,
                    max_price=query.max_price,
                    bedrooms=query.bedrooms,
                    limit=max(query.limit * 3, 10),
                    listing_type=listing_type,
                ),
                timeout=TOOL_TIMEOUT_S,
            )
        except Exception as exc:
            logger.warning("property_search failed (area=%s): %s", area, exc)
            return []

    rows: list[dict[str, Any]] = []
    if area_terms:
        for batch in await asyncio.gather(*(_search(a) for a in area_terms[:6])):
            rows.extend(batch)
    else:
        rows = await _search(None)

    seen: set[str] = set()
    cards: list[PropertyCard] = []
    for prop in rows:
        pid = str(prop.get("id"))
        if pid in seen or pid in query.exclude_ids or not _is_live_ok(prop):
            continue
        if listing_type and prop.get("listing_type") not in (None, listing_type):
            continue
        seen.add(pid)
        cards.append(_to_card(prop, _reasons(prop, query)))

    budget_ref = query.max_price / 1.1 if query.max_price else None
    cards.sort(key=lambda c: (abs((c.price or 0) - budget_ref) if budget_ref else (c.price or 0)))
    return SearchResult(cards=cards[: query.limit], total_considered=len(seen))


def _reasons(prop: dict[str, Any], query: PropertyQuery) -> list[str]:
    reasons: list[str] = []
    if query.areas and prop.get("area"):
        reasons.append(f"In {prop['area']}")
    if query.max_price and prop.get("price") and prop["price"] <= query.max_price / 1.1:
        reasons.append("Within budget")
    elif query.max_price and prop.get("price"):
        reasons.append("Slightly above budget")
    if query.bedrooms is not None and prop.get("bedrooms") == query.bedrooms:
        reasons.append(f"{query.bedrooms} bedrooms as requested")
    if query.property_type and prop.get("property_type") == query.property_type:
        reasons.append(f"{query.property_type.title()}")
    return reasons


def to_shown(cards: list[PropertyCard], turn: int) -> list[ShownProperty]:
    return [
        ShownProperty(
            property_id=c.property_id,
            title=c.title,
            price=c.price,
            area=c.area,
            community_id=c.community_id,
            bedrooms=c.bedrooms,
            property_type=c.property_type,
            shown_turn=turn,
        )
        for c in cards
    ]
