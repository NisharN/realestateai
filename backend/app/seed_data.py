"""Seeded demo data — the default (mock) data mode.

Every external source in this product sits behind a mode switch that defaults
to ``mock`` (see ``config.DATA_MODE_*``). This module is what mock mode
serves: a coherent, deliberately realistic slice of a Dubai brokerage so the
whole product — matching, scoring, follow-up, the comps map — is demonstrable
offline with zero API keys and zero approvals pending.

Everything here is fabricated but plausible: real community names, realistic
price-per-sqft bands for those communities, and lead phrasing that includes
the exact currency/period ambiguities the budget extractor exists to catch.
Nothing here claims to be real market data — the DLD points below are
representative sample rows, not a live Dubai Land Department extract. When
``DATA_MODE_DLD=live`` those get replaced by the real Dubai Pulse feed.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

# Community centroids (approximate) used to scatter listings and comps.
COMMUNITIES: Dict[str, Dict[str, Any]] = {
    "Dubai Marina":   {"lat": 25.0805, "lng": 55.1403, "ppsf": 1650, "type_bias": "apartment"},
    "Downtown Dubai": {"lat": 25.1972, "lng": 55.2744, "ppsf": 2100, "type_bias": "apartment"},
    "Palm Jumeirah":  {"lat": 25.1124, "lng": 55.1390, "ppsf": 2900, "type_bias": "villa"},
    "Business Bay":   {"lat": 25.1857, "lng": 55.2649, "ppsf": 1500, "type_bias": "apartment"},
    "JVC":            {"lat": 25.0570, "lng": 55.2093, "ppsf": 1050, "type_bias": "apartment"},
    "Dubai Hills":    {"lat": 25.1050, "lng": 55.2470, "ppsf": 1750, "type_bias": "villa"},
    "JBR":            {"lat": 25.0785, "lng": 55.1330, "ppsf": 1900, "type_bias": "apartment"},
    "Arabian Ranches": {"lat": 25.0250, "lng": 55.2700, "ppsf": 1400, "type_bias": "villa"},
    "DIFC":           {"lat": 25.2110, "lng": 55.2800, "ppsf": 2250, "type_bias": "apartment"},
    "Damac Hills":    {"lat": 25.0280, "lng": 55.2480, "ppsf": 1200, "type_bias": "townhouse"},
}

DEVELOPERS = ["Emaar", "DAMAC", "Nakheel", "Meraas", "Select Group", "Sobha", "Ellington"]

AMENITY_POOL = [
    "Pool", "Gym", "Covered Parking", "Concierge", "Beach Access",
    "Smart Home", "Kids Play Area", "Landscaped Garden", "Sauna", "Padel Court",
]


def _rng(seed: str) -> random.Random:
    """Deterministic per-purpose RNG so the demo looks identical every run."""
    return random.Random(seed)


def mock_property_records(count: int = 42) -> List[Dict[str, Any]]:
    """Listings shaped exactly like the ingestion pipeline's input records."""
    rng = _rng("properties-v1")
    now = datetime.now(timezone.utc)
    records: List[Dict[str, Any]] = []

    names = list(COMMUNITIES.keys())
    for i in range(count):
        area = names[i % len(names)]
        meta = COMMUNITIES[area]
        ptype = meta["type_bias"] if rng.random() < 0.7 else rng.choice(
            ["apartment", "villa", "townhouse", "penthouse"]
        )
        beds = rng.choice([1, 1, 2, 2, 2, 3, 3, 4]) if ptype == "apartment" else rng.choice([3, 4, 4, 5])
        size = beds * rng.randint(480, 760)
        ppsf = meta["ppsf"] * rng.uniform(0.85, 1.18)
        price = round(size * ppsf, -3)

        # Spread "last refreshed" so the staleness workflow has real work to do:
        # roughly a third of the book is deliberately stale.
        days_since_refresh = rng.choice([1, 2, 4, 6, 9, 12, 16, 19, 23, 31])

        records.append(
            {
                "id": f"seed-{i:03d}",
                "source": "mock_seed",
                "source_id": f"seed-{i:03d}",
                "source_url": f"https://demo.local/listing/seed-{i:03d}",
                "title": f"{rng.choice(DEVELOPERS)} {ptype.title()} in {area} — {beds}BR",
                "description": (
                    f"{beds}-bedroom {ptype} in {area}, {size:,} sqft. "
                    "Bright layout with quality finishes and community access."
                ),
                "price": float(price),
                "price_per_sqft": round(price / max(size, 1), 2),
                "area": area,
                "property_type": ptype,
                "bedrooms": beds,
                "bathrooms": max(1, beds - 1),
                "size_sqft": size,
                "images": [
                    "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800",
                    "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800",
                ],
                "map_lat": round(meta["lat"] + rng.uniform(-0.012, 0.012), 6),
                "map_lng": round(meta["lng"] + rng.uniform(-0.012, 0.012), 6),
                "amenities": rng.sample(AMENITY_POOL, k=4),
                "developer": rng.choice(DEVELOPERS),
                "is_active": True,
                "refresh_count": rng.randint(0, 3),
                "last_refreshed_at": (now - timedelta(days=days_since_refresh)).isoformat(),
                "scraped_at": (now - timedelta(days=days_since_refresh)).isoformat(),
            }
        )
    return records


# Lead messages chosen to exercise the budget extractor's ambiguity handling:
# some explicit, some missing currency, some missing period, some bare numbers.
LEAD_SEEDS: List[Dict[str, Any]] = [
    {"first_name": "Ahmed", "last_name": "Al Mansouri", "source": "propertyfinder",
     "message": "Looking to buy a 2 bed in Marina, budget AED 1.8M", "lang": "en"},
    {"first_name": "Priya", "last_name": "Nair", "source": "bayut",
     "message": "I want to rent, 80k per year in JVC", "lang": "en"},
    {"first_name": "James", "last_name": "Whitfield", "source": "website_form",
     "message": "budget is USD 500k to buy, prefer Downtown", "lang": "en"},
    {"first_name": "Fatima", "last_name": "Al Suwaidi", "source": "whatsapp",
     "message": "my budget is 1.2", "lang": "ar"},
    {"first_name": "Chen", "last_name": "Wei", "source": "referral",
     "message": "investor, 3-4 million dirhams, looking at Business Bay yields", "lang": "en"},
    {"first_name": "Omar", "last_name": "Haddad", "source": "propertyfinder",
     "message": "3 bedroom villa in Dubai Hills, around 6.5M AED", "lang": "en"},
    {"first_name": "Sofia", "last_name": "Rossi", "source": "instagram",
     "message": "renting, up to 140,000 AED annually, Palm or JBR", "lang": "en"},
    {"first_name": "Rahul", "last_name": "Mehta", "source": "crm_import",
     "message": "i have 2 million", "lang": "en"},
    {"first_name": "Layla", "last_name": "Karim", "source": "walk_in",
     "message": "family home, 4 bed, Arabian Ranches, 7M budget to purchase", "lang": "ar"},
    {"first_name": "Daniel", "last_name": "Okafor", "source": "google_ads",
     "message": "studio or 1 bed investment under 900k AED", "lang": "en"},
    {"first_name": "Mariam", "last_name": "Al Balushi", "source": "whatsapp",
     "message": "Downtown 2BR, 2.4M", "lang": "ar"},
    {"first_name": "Tom", "last_name": "Bergstrom", "source": "referral",
     "message": "relocating, need 3 bed rental in Dubai Hills, 250k a year", "lang": "en"},
]

STATUSES = ["new", "new", "contacted", "contacted", "qualified", "qualified", "nurture", "closed"]


def mock_leads(count: int = 26) -> List[Dict[str, Any]]:
    """Leads spread across pipeline stages, sources, and recency."""
    rng = _rng("leads-v1")
    now = datetime.now(timezone.utc)
    leads: List[Dict[str, Any]] = []

    for i in range(count):
        seed = LEAD_SEEDS[i % len(LEAD_SEEDS)]
        status = STATUSES[i % len(STATUSES)]
        # A few genuinely fresh, uncontacted leads so the new-lead follow-up
        # workflow has something to act on in a live demo.
        age_minutes = rng.choice([3, 8, 25, 90, 240, 1200, 4300, 11000])
        created = now - timedelta(minutes=age_minutes)
        contacted = status != "new"

        area = rng.choice(list(COMMUNITIES.keys()))
        score = {
            "new": rng.randint(10, 45),
            "contacted": rng.randint(35, 65),
            "qualified": rng.randint(62, 92),
            "nurture": rng.randint(15, 40),
            "closed": rng.randint(70, 98),
        }[status]

        leads.append(
            {
                "id": f"lead-{i:03d}",
                "source": seed["source"],
                "first_name": seed["first_name"],
                "last_name": seed["last_name"],
                "phone": f"+9715{rng.randint(10000000, 99999999)}",
                "email": f"{seed['first_name'].lower()}{i}@example.com",
                "preferred_language": seed["lang"],
                "property_type": rng.choice(["apartment", "villa", "townhouse"]),
                "area_preference": [area],
                "timeline": rng.choice(["immediate", "1_3_months", "3_6_months", "just_browsing"]),
                "intent_score": score,
                "status": status,
                "initial_message": seed["message"],
                "conversation_history": [
                    {"role": "user", "content": seed["message"]},
                ],
                "created_at": created.isoformat(),
                "updated_at": created.isoformat(),
                "last_contact_at": (created + timedelta(minutes=12)).isoformat() if contacted else None,
                "assigned_broker": f"broker-{rng.randint(1, 3)}" if contacted else None,
            }
        )
    return leads


def mock_dld_transactions(count: int = 160) -> List[Dict[str, Any]]:
    """Representative comparable-sale points for the map.

    NOT real Dubai Land Department data — these are synthesised rows in the
    same shape as the DLD open-data transaction extract, so the comps map and
    the price-positioning line in listing refresh copy are demonstrable
    offline. Set ``DATA_MODE_DLD=live`` to source the real Dubai Pulse feed.
    """
    rng = _rng("dld-v1")
    now = datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    names = list(COMMUNITIES.keys())

    for i in range(count):
        area = names[i % len(names)]
        meta = COMMUNITIES[area]
        size = rng.randint(550, 3800)
        ppsf = meta["ppsf"] * rng.uniform(0.8, 1.25)
        amount = round(size * ppsf, -3)
        rows.append(
            {
                "transaction_id": f"dld-demo-{i:04d}",
                "area": area,
                "property_type": rng.choice(["apartment", "villa", "townhouse"]),
                "rooms": rng.choice([1, 2, 2, 3, 3, 4, 5]),
                "size_sqft": size,
                "amount_aed": float(amount),
                "price_per_sqft": round(amount / size, 2),
                "transaction_date": (now - timedelta(days=rng.randint(1, 540))).date().isoformat(),
                "lat": round(meta["lat"] + rng.uniform(-0.015, 0.015), 6),
                "lng": round(meta["lng"] + rng.uniform(-0.015, 0.015), 6),
                "is_demo_data": True,
            }
        )
    return rows


def community_median_ppsf() -> Dict[str, float]:
    """Median price-per-sqft per community, derived from the comps above."""
    by_area: Dict[str, List[float]] = {}
    for row in mock_dld_transactions():
        by_area.setdefault(row["area"], []).append(row["price_per_sqft"])
    medians: Dict[str, float] = {}
    for area, values in by_area.items():
        values.sort()
        mid = len(values) // 2
        medians[area] = round(
            values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2, 2
        )
    return medians


def mock_viewings(count: int = 8) -> List[Dict[str, Any]]:
    """Upcoming and completed viewings for the reminder workflows."""
    rng = _rng("viewings-v1")
    now = datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for i in range(count):
        upcoming = i % 2 == 0
        scheduled = now + timedelta(hours=rng.randint(3, 40)) if upcoming else now - timedelta(hours=rng.randint(20, 72))
        out.append(
            {
                "id": f"viewing-{i:03d}",
                "lead_id": f"lead-{i:03d}",
                "lead_name": LEAD_SEEDS[i % len(LEAD_SEEDS)]["first_name"],
                "phone": f"+9715{rng.randint(10000000, 99999999)}",
                "property_id": f"seed-{i:03d}",
                "property_title": f"Listing seed-{i:03d}",
                "scheduled_at": scheduled.isoformat(),
                "status": "scheduled" if upcoming else "completed",
                "reminder_sent_at": None,
                "followup_sent_at": None,
            }
        )
    return out


def mock_mandates(count: int = 6) -> List[Dict[str, Any]]:
    """Exclusive mandates, some approaching expiry."""
    rng = _rng("mandates-v1")
    now = datetime.now(timezone.utc)
    return [
        {
            "id": f"mandate-{i:03d}",
            "property_id": f"seed-{i:03d}",
            "property_title": f"Listing seed-{i:03d}",
            "agent_id": f"broker-{(i % 3) + 1}",
            "owner_name": f"Owner {i}",
            "status": "active",
            "expires_at": (now + timedelta(days=rng.choice([12, 28, 40, 95, 180, 220]))).isoformat(),
            "renewal_notified_at": None,
        }
        for i in range(count)
    ]


def seed_summary() -> Dict[str, int]:
    """Counts for the docs page and the seed script's output."""
    return {
        "properties": len(mock_property_records()),
        "leads": len(mock_leads()),
        "dld_transactions": len(mock_dld_transactions()),
        "viewings": len(mock_viewings()),
        "mandates": len(mock_mandates()),
    }
