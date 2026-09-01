"""Scrapers package for Dubai real estate platforms.

Each portal scraper extends ``BaseScraper`` (Playwright + stealth). For demo /
local development, the public ``scrape_*`` helpers fall back to a synthesised
listing set when the live portal is unreachable (timeout, anti-bot block, etc.)
so the rest of the AI pipeline — agent orchestration, matching, handoff —
keeps working.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Dict, List, Optional

from .bayut_scraper import BayutScraper, scrape_bayut  # noqa: F401
from .dubizzle_scraper import DubizzleScraper, scrape_dubizzle  # noqa: F401
from .approved_feed import ApprovedFeedScraper, scrape_approved_feed  # noqa: F401
from .rapidapi_uae import (  # noqa: F401
    RapidApiUAEScraper,
    rapidapi_developer_search_by_name,
    scrape_rapidapi_properties,
)
from .propertyfinder_scraper import (  # noqa: F401
    PropertyFinderScraper,
    scrape_propertyfinder,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BayutScraper",
    "PropertyFinderScraper",
    "DubizzleScraper",
    "ApprovedFeedScraper",
    "RapidApiUAEScraper",
    "scrape_bayut",
    "scrape_propertyfinder",
    "scrape_dubizzle",
    "scrape_approved_feed",
    "scrape_rapidapi_properties",
    "rapidapi_developer_search_by_name",
    "synthesized_listings",
]


_AREAS = [
    "Downtown Dubai",
    "Dubai Marina",
    "Palm Jumeirah",
    "Business Bay",
    "JBR",
    "DIFC",
    "Dubai Hills",
    "Arabian Ranches",
]
_TYPES = ["apartment", "villa", "penthouse", "townhouse"]
_DEVELOPERS = ["Emaar", "DAMAC", "Nakheel", "Meraas", "Select Group"]


def _one_synthetic(idx: int, source: str) -> Dict[str, Any]:
    area = random.choice(_AREAS)
    ptype = random.choice(_TYPES)
    beds = random.choice([1, 2, 2, 3, 3, 4])
    size = beds * random.randint(450, 750)
    price = (
        random.randint(900_000, 1_800_000) * beds
        + random.choice([0, 250_000, 750_000])
    )
    return {
        "id": f"{source}-synth-{idx}",
        "source": source,
        "source_id": f"{source}-synth-{idx}",
        "source_url": f"https://example.com/{source}/{idx}",
        "title": f"{random.choice(_DEVELOPERS)} {ptype.title()} in {area} — {beds}BR",
        "description": (
            f"Spacious {beds}-bedroom {ptype} in {area}. "
            "Bright open-plan living, premium finishes, walkable to dining and transit."
        ),
        "price": float(price),
        "price_per_sqft": round(price / max(size, 1), 2),
        "area": area,
        "property_type": ptype,
        "bedrooms": beds,
        "bathrooms": max(1, beds - 1),
        "size_sqft": size,
        "images": [
            f"https://images.unsplash.com/photo-{random.choice(['1545324418-cc1a3fa10c00', '1512917774080-9991f1c4c750', '1522708323590-d24dbb6b0267', '1502672260266-1c1ef2d93688'])}?w=800"
        ],
        "video_url": None,
        "floor_plan_url": None,
        "map_lat": 25.0 + random.random() * 0.3,
        "map_lng": 55.0 + random.random() * 0.4,
        "amenities": random.sample(
            ["Pool", "Gym", "Concierge", "Parking", "Beach Access", "Smart Home", "Valet", "Spa"],
            k=4,
        ),
        "developer": random.choice(_DEVELOPERS),
        "completion_date": None,
        "scraped_at": __import__("datetime").datetime.utcnow().isoformat(),
        "is_active": True,
        "synthetic": True,
    }


def synthesized_listings(
    source: str = "demo",
    count: int = 12,
    area: Optional[str] = None,
    property_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Generate a deterministic-ish batch of demo listings.

    Used when the live portal is unreachable so the rest of the AI pipeline
    stays demonstrable. Honors ``area`` / ``property_type`` filters when given.
    """
    rng = random.Random(f"{source}:{area or ''}:{property_type or ''}")
    out: List[Dict[str, Any]] = []
    for i in range(count):
        rec = _one_synthetic(i, source)
        if area:
            rec["area"] = area
        if property_type:
            rec["property_type"] = property_type
        out.append(rec)
    return out


def _maybe_synthesize(name: str, listings: List[Dict[str, Any]], **kwargs) -> List[Dict[str, Any]]:
    """If a real scrape returned nothing, fall back to synthesized data.

    The orchestrator doesn't care whether a listing was scraped or generated;
    matching and the UI work the same.
    """
    if listings:
        return listings
    area = kwargs.get("area")
    ptype = kwargs.get("property_type", "buy_apartment")
    logger.info("Falling back to synthesized listings for %s (area=%s)", name, area)
    return synthesized_listings(source=name, area=area, property_type=ptype.replace("buy_", "").replace("rent_", ""))


async def scrape_bayut_safe(**kwargs) -> List[Dict[str, Any]]:
    return _maybe_synthesize("bayut", await scrape_bayut(**kwargs), **kwargs)


async def scrape_propertyfinder_safe(**kwargs) -> List[Dict[str, Any]]:
    return _maybe_synthesize("propertyfinder", await scrape_propertyfinder(**kwargs), **kwargs)


async def scrape_dubizzle_safe(**kwargs) -> List[Dict[str, Any]]:
    return _maybe_synthesize("dubizzle", await scrape_dubizzle(**kwargs), **kwargs)
