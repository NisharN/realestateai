"""Stress-scale demo data generator (mock mode only).

Produces a deterministic, plausible brokerage book of arbitrary size — leads
across every pipeline stage, a listing book across all gazetteer communities,
plus handoffs, viewings and follow-ups linked to those leads — so the broker
and admin screens can be exercised at ~100k records without a database.

Everything is derived from a fixed seed, so ``DEMO_SEED_SCALE=100000`` yields
the same world on every start. Records are kept lean (no long transcripts) so
100k leads fit comfortably in memory. Nothing here is ever loaded when a real
datastore is configured; see ``mock_store.load_seed_data``.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List

from app.modules.geo.communities import COMMUNITIES

FIRST_NAMES_EN = [
    "Ahmed", "Fatima", "Omar", "Layla", "Mariam", "Khalid", "Noor", "Yousef", "Sara", "Hamad",
    "Priya", "Rahul", "Anita", "Vikram", "James", "Emma", "Oliver", "Sophie", "Chen", "Mei",
    "Daniel", "Grace", "Tom", "Anna", "Ivan", "Olga", "Sofia", "Marco", "Aisha", "Zayed",
]
LAST_NAMES_EN = [
    "Al Mansouri", "Al Suwaidi", "Haddad", "Karim", "Al Balushi", "Al Marri", "Nair", "Mehta",
    "Sharma", "Whitfield", "Bergstrom", "Rossi", "Wei", "Okafor", "Petrov", "Ivanova", "Khan",
    "Hussain", "Rahman", "Al Nuaimi", "Farouk", "Saleh", "Dubois", "Schmidt", "Tanaka",
]
SOURCES = ["propertyfinder", "bayut", "website_form", "whatsapp", "referral", "instagram", "google_ads", "crm_import", "walk_in", "dubizzle"]
SOURCE_WEIGHTS = [22, 18, 14, 14, 8, 7, 7, 5, 3, 2]
LANGUAGES = ["en", "en", "en", "ar", "ar", "mixed"]
STAGES = ["new", "qualifying", "qualified", "handed_off", "viewing_booked", "offer", "closed", "lost", "opted_out"]
STAGE_WEIGHTS = [24, 22, 16, 12, 8, 4, 5, 7, 2]
STAGE_STATUS = {
    "new": "new", "qualifying": "new", "qualified": "qualified", "handed_off": "contacted",
    "viewing_booked": "contacted", "offer": "contacted", "closed": "closed", "lost": "nurture", "opted_out": "closed",
}
SCORE_RANGE = {
    "new": (5, 40), "qualifying": (25, 60), "qualified": (60, 85), "handed_off": (65, 92),
    "viewing_booked": (72, 96), "offer": (80, 99), "closed": (85, 99), "lost": (10, 50), "opted_out": (0, 20),
}
PURPOSES = ["buy", "buy", "buy", "rent", "rent", "invest"]
PROPERTY_TYPES = ["apartment", "apartment", "apartment", "villa", "townhouse", "penthouse"]
TIMELINES = ["immediate", "1_3_months", "3_6_months", "6_12_months", "just_browsing"]
PAYMENTS = ["cash", "mortgage", "mortgage", "undecided"]
DEVELOPERS = ["Emaar", "DAMAC", "Nakheel", "Meraas", "Select Group", "Sobha", "Ellington", "Binghatti", "Azizi", "Danube"]
AMENITIES = ["Pool", "Gym", "Covered Parking", "Concierge", "Beach Access", "Smart Home", "Kids Play Area", "Garden", "Sauna", "Padel Court", "Maid's Room", "Study"]
BROKERS = ["broker-1", "broker-2"]

# Approximate sale price per sqft by community tier; rents are ~6% yield.
_PPSF_HIGH = {"downtown_dubai", "palm_jumeirah", "difc", "jbr", "bluewaters", "emirates_hills", "jumeirah", "city_walk"}
_PPSF_LOW = {"international_city", "discovery_gardens", "dubai_south", "dubai_production_city", "remraam", "dubai_silicon_oasis", "al_quoz", "deira", "bur_dubai", "al_satwa"}


def _ppsf(community_id: str) -> int:
    if community_id in _PPSF_HIGH:
        return 2400
    if community_id in _PPSF_LOW:
        return 850
    return 1450


def _pick(rng: random.Random, options: List[Any], weights: List[int] | None = None) -> Any:
    return rng.choices(options, weights=weights, k=1)[0]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def scale_properties(count: int, seed: str = "scale-properties-v1") -> Iterator[Dict[str, Any]]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    for i in range(count):
        c = COMMUNITIES[i % len(COMMUNITIES)]
        ptype = _pick(rng, PROPERTY_TYPES)
        beds = _pick(rng, [0, 1, 1, 2, 2, 2, 3, 3]) if ptype in ("apartment", "penthouse") else _pick(rng, [3, 4, 4, 5, 6])
        size = beds * rng.randint(450, 780) if beds else rng.randint(380, 560)
        price = round(size * _ppsf(c.id) * rng.uniform(0.82, 1.22), -3)
        listing_kind = "rent" if rng.random() < 0.3 else "sale"
        if listing_kind == "rent":
            price = round(price * 0.06, -3)
        age_days = rng.randint(0, 45)
        yield {
            "id": f"scale-prop-{i:06d}",
            "source": "mock_seed",
            "source_id": f"scale-prop-{i:06d}",
            "source_url": f"https://demo.local/listing/scale-prop-{i:06d}",
            "title": f"{_pick(rng, DEVELOPERS)} {ptype.title()} in {c.name_en} — {beds or 'Studio'}{'BR' if beds else ''}",
            "description": f"{beds or 'Studio'}-bedroom {ptype} in {c.name_en}, {size:,} sqft.",
            "price": float(price),
            "price_per_sqft": round(price / size, 2),
            "listing_type": listing_kind,
            "area": c.name_en,
            "community_id": c.id,
            "property_type": ptype,
            "bedrooms": beds,
            "bathrooms": max(1, beds),
            "size_sqft": size,
            "images": ["https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800"],
            "map_lat": round(c.lat + rng.uniform(-0.01, 0.01), 6),
            "map_lng": round(c.lng + rng.uniform(-0.01, 0.01), 6),
            "amenities": rng.sample(AMENITIES, k=4),
            "developer": _pick(rng, DEVELOPERS),
            "is_active": age_days < 40,
            "refresh_count": rng.randint(0, 5),
            "last_refreshed_at": _iso(now - timedelta(days=age_days)),
            "scraped_at": _iso(now - timedelta(days=age_days)),
        }


def scale_leads(count: int, seed: str = "scale-leads-v1") -> Iterator[Dict[str, Any]]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    for i in range(count):
        stage = _pick(rng, STAGES, STAGE_WEIGHTS)
        status = STAGE_STATUS[stage]
        lo, hi = SCORE_RANGE[stage]
        score = rng.randint(lo, hi)
        c = _pick(rng, COMMUNITIES)
        purpose = _pick(rng, PURPOSES)
        ptype = _pick(rng, PROPERTY_TYPES)
        beds = _pick(rng, [1, 2, 2, 3, 3, 4]) if ptype in ("apartment", "penthouse") else _pick(rng, [3, 4, 5])
        base = _ppsf(c.id) * beds * 600
        if purpose == "rent":
            budget_max = round(base * 0.06 * rng.uniform(0.8, 1.3), -3)
        else:
            budget_max = round(base * rng.uniform(0.8, 1.4), -4)
        budget_min = round(budget_max * rng.uniform(0.6, 0.85), -3)
        age_min = int(rng.expovariate(1 / 20000)) + rng.randint(1, 240)  # heavy tail up to ~a year
        created = now - timedelta(minutes=age_min)
        updated = created + timedelta(minutes=rng.randint(5, 3000))
        assigned = _pick(rng, BROKERS) if stage in ("handed_off", "viewing_booked", "offer", "closed") or (stage == "qualified" and rng.random() < 0.4) else None
        language = _pick(rng, LANGUAGES)
        first = _pick(rng, FIRST_NAMES_EN)
        last = _pick(rng, LAST_NAMES_EN)
        band = "hot" if score >= 70 else "warm" if score >= 40 else "cold"
        yield {
            "id": f"scale-lead-{i:06d}",
            "source": _pick(rng, SOURCES, SOURCE_WEIGHTS),
            "first_name": first,
            "last_name": last,
            "phone": f"+9715{50000000 + (i * 7919) % 49999999:08d}",
            "email": f"{first.lower()}.{last.split()[-1].lower()}{i}@example.com",
            "preferred_language": "ar" if language == "ar" else "en",
            "purpose": purpose,
            "property_type": ptype,
            "property_types": [ptype],
            "bedrooms_min": beds,
            "area_preference": [c.name_en],
            "community_ids": [c.id],
            "budget_min": float(budget_min),
            "budget_max": float(budget_max),
            "budget_min_aed": float(budget_min),
            "budget_max_aed": float(budget_max),
            "budget_currency": "AED",
            "budget_period": "year" if purpose == "rent" else "total",
            "timeline": _pick(rng, TIMELINES),
            "payment": _pick(rng, PAYMENTS),
            "intent_score": score,
            "score": score,
            "band": band,
            "status": status,
            "stage": stage,
            "initial_message": f"{purpose} {beds} bed {ptype} in {c.name_en}, budget AED {budget_max:,.0f}",
            "conversation_history": [],
            "created_at": _iso(created),
            "updated_at": _iso(min(updated, now)),
            "last_contact_at": _iso(min(updated, now)) if status != "new" else None,
            "assigned_broker": assigned,
        }


def scale_related(leads: List[Dict[str, Any]], seed: str = "scale-related-v1") -> Dict[str, List[Dict[str, Any]]]:
    """Handoffs, viewings and follow-ups consistent with each lead's stage."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    handoffs: List[Dict[str, Any]] = []
    viewings: List[Dict[str, Any]] = []
    followups: List[Dict[str, Any]] = []
    prop_total = max(1, len(leads) // 4)
    for lead in leads:
        stage = lead["stage"]
        broker = lead.get("assigned_broker")
        if stage in ("handed_off", "viewing_booked", "offer", "closed") and broker:
            h_status = "pending" if stage == "handed_off" and rng.random() < 0.35 else "accepted"
            created = datetime.fromisoformat(lead["updated_at"])
            handoffs.append({
                "id": f"scale-handoff-{lead['id'][-6:]}",
                "lead_id": lead["id"],
                "broker_id": broker,
                "broker_name": {"broker-1": "Sarah Al-Maktoum", "broker-2": "Ahmed Hassan"}.get(broker),
                "status": h_status,
                "reason": "qualified",
                "routing_reasons": ["language match", "community specialist"],
                "brief": {"summary": lead["initial_message"], "language": lead["preferred_language"]},
                "score": lead["score"],
                "band": lead["band"],
                "language": lead["preferred_language"],
                "slot_text": None,
                "created_at": _iso(created),
                "reassign_after": _iso(created + timedelta(minutes=15)),
                "accepted_at": _iso(created + timedelta(minutes=rng.randint(2, 40))) if h_status == "accepted" else None,
                "reassigned_count": 0,
            })
        if stage in ("viewing_booked", "offer", "closed"):
            future = stage == "viewing_booked"
            starts = now + timedelta(hours=rng.randint(2, 96)) if future else now - timedelta(days=rng.randint(1, 30))
            viewings.append({
                "id": f"scale-viewing-{lead['id'][-6:]}",
                "lead_id": lead["id"],
                "broker_id": broker,
                "property_id": f"scale-prop-{rng.randrange(prop_total):06d}",
                "starts_at": _iso(starts.replace(minute=0, second=0, microsecond=0)),
                "status": ("confirmed" if rng.random() < 0.6 else "requested") if future else ("done" if rng.random() < 0.85 else "no_show"),
                "notes": None,
                "source": "broker" if rng.random() < 0.5 else "buyer",
                "created_at": lead["updated_at"],
                "updated_at": lead["updated_at"],
            })
        if stage in ("qualifying", "qualified", "handed_off") and rng.random() < 0.5:
            due = now + timedelta(hours=rng.randint(-48, 72))
            followups.append({
                "id": f"scale-followup-{lead['id'][-6:]}",
                "lead_id": lead["id"],
                "band": lead["band"],
                "touch": rng.randint(1, 3),
                "template_key": "followup_check_in",
                "channel": "whatsapp",
                "due_at": _iso(due.replace(second=0, microsecond=0)),
                "status": "pending",
                "attempts": 0,
                "created_at": lead["updated_at"],
            })
    return {"handoffs": handoffs, "viewings": viewings, "followups": followups}
