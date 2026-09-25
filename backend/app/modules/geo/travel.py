"""Offline travel-time lookups (architecture §7).

Two data sources, both deterministic and both local:

* ``travel_times`` table — precomputed by ``scripts/osrm_precompute.py`` against a
  self-hosted OSRM. Rows carry ``method="osrm"`` and a ``computed_at`` stamp.
* straight-line fallback — haversine distance and an assumed city driving speed.
  Rows/results carry ``method="straight_line"`` and ``approx=True`` so the
  responder must label them as estimates.

Nothing here calls the network. OSRM is only ever hit by the batch script.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.modules.geo.communities import COMMUNITIES, Community, get_community
from app.modules.store import Row, now_iso, table

GEO_WORKSPACE = "shared"  # gazetteer + travel tables are not tenant data
ASSUMED_SPEED_KMH = 38.0  # Dubai off-peak arterial average; used only for the labelled fallback
ROAD_FACTOR = 1.3  # straight-line → road distance


@dataclass(frozen=True)
class Landmark:
    id: str
    name_en: str
    name_ar: str
    lat: float
    lng: float
    kind: str


LANDMARKS: tuple[Landmark, ...] = (
    Landmark("dxb", "Dubai International Airport (DXB)", "مطار دبي الدولي", 25.2532, 55.3657, "airport"),
    Landmark("dwc", "Al Maktoum International (DWC)", "مطار آل مكتوم الدولي", 24.8964, 55.1614, "airport"),
    Landmark("downtown", "Downtown / Burj Khalifa", "وسط المدينة / برج خليفة", 25.1972, 55.2744, "district"),
    Landmark("difc", "DIFC", "مركز دبي المالي العالمي", 25.2110, 55.2800, "business"),
    Landmark("marina", "Dubai Marina", "مرسى دبي", 25.0805, 55.1403, "district"),
    Landmark("dubai_mall", "Dubai Mall", "دبي مول", 25.1985, 55.2796, "mall"),
    Landmark("moe", "Mall of the Emirates", "مول الإمارات", 25.1181, 55.2004, "mall"),
    Landmark("jbr_beach", "JBR Beach", "شاطئ جي بي آر", 25.0783, 55.1336, "beach"),
    Landmark("expo_city", "Expo City Dubai", "مدينة إكسبو دبي", 24.9610, 55.1510, "district"),
    Landmark("internet_city", "Dubai Internet City", "مدينة دبي للإنترنت", 25.0950, 55.1590, "business"),
    Landmark("jafza", "Jebel Ali Free Zone", "المنطقة الحرة بجبل علي", 25.0090, 55.0680, "business"),
    Landmark("healthcare_city", "Dubai Healthcare City", "مدينة دبي الطبية", 25.2300, 55.3200, "hospital"),
)
DEFAULT_LANDMARKS: tuple[str, ...] = ("downtown", "dxb", "marina", "difc")

_LANDMARK_BY_ID = {l.id: l for l in LANDMARKS}


class TravelTime(BaseModel):
    from_id: str
    to_id: str
    to_name_en: str
    to_name_ar: str
    to_lat: float
    to_lng: float
    minutes: int
    km: float
    method: str  # "osrm" | "straight_line"
    approx: bool
    computed_at: str | None = None


def get_landmark(landmark_id: str) -> Landmark | None:
    return _LANDMARK_BY_ID.get(landmark_id)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def straight_line(origin: Community | Landmark, dest: Landmark) -> TravelTime:
    km = haversine_km(origin.lat, origin.lng, dest.lat, dest.lng) * ROAD_FACTOR
    minutes = max(3, round(km / ASSUMED_SPEED_KMH * 60))
    return TravelTime(
        from_id=origin.id, to_id=dest.id, to_name_en=dest.name_en, to_name_ar=dest.name_ar,
        to_lat=dest.lat, to_lng=dest.lng,
        minutes=minutes, km=round(km, 1), method="straight_line", approx=True,
    )


def nearest_communities(community_id: str, n: int = 3) -> list[tuple[Community, float]]:
    """Deterministic neighbours by centroid distance — used for "similar areas" suggestions."""
    origin = get_community(community_id)
    if origin is None:
        return []
    ranked = sorted(
        ((c, haversine_km(origin.lat, origin.lng, c.lat, c.lng)) for c in COMMUNITIES if c.id != origin.id),
        key=lambda pair: pair[1],
    )
    return [(c, round(d, 1)) for c, d in ranked[:n]]


async def travel_time(from_community_id: str, landmark_id: str) -> TravelTime | None:
    origin = get_community(from_community_id)
    dest = get_landmark(landmark_id)
    if origin is None or dest is None:
        return None
    row = await table("travel_times", GEO_WORKSPACE).get(from_id=origin.id, to_id=dest.id)
    if row and row.get("minutes") is not None:
        return TravelTime(
            from_id=origin.id, to_id=dest.id, to_name_en=dest.name_en, to_name_ar=dest.name_ar,
            to_lat=dest.lat, to_lng=dest.lng,
            minutes=int(row["minutes"]), km=float(row.get("km") or 0.0),
            method=str(row.get("method") or "osrm"), approx=str(row.get("method")) != "osrm",
            computed_at=row.get("computed_at"),
        )
    return straight_line(origin, dest)


async def travel_summary(from_community_id: str, landmark_ids: tuple[str, ...] = DEFAULT_LANDMARKS) -> list[TravelTime]:
    out: list[TravelTime] = []
    for lid in landmark_ids:
        tt = await travel_time(from_community_id, lid)
        if tt is not None:
            out.append(tt)
    return out


async def store_travel_times(rows: list[dict[str, Any]], *, method: str) -> int:
    """Upsert a batch produced by the precompute script. Never deletes: a failed
    refresh keeps last week's table (§7)."""
    await seed_landmarks()
    t = table("travel_times", GEO_WORKSPACE)
    stamp = now_iso()
    n = 0
    for r in rows:
        payload: Row = {
            "from_id": r["from_id"], "to_id": r["to_id"], "minutes": int(r["minutes"]), "km": float(r["km"]),
            "method": method, "computed_at": stamp,
        }
        await t.upsert(payload, on_conflict="from_id,to_id")
        n += 1
    return n


async def seed_landmarks() -> int:
    """Upsert the landmark catalog; ``travel_times.to_id`` references it."""
    t = table("landmarks", GEO_WORKSPACE)
    for row in landmark_rows():
        await t.upsert(dict(row), on_conflict="id")
    return len(LANDMARKS)


def landmark_rows() -> list[dict[str, object]]:
    return [{"id": l.id, "name_en": l.name_en, "name_ar": l.name_ar, "lat": l.lat, "lng": l.lng, "kind": l.kind} for l in LANDMARKS]
