"""area_profile tool — offline community facts.

Until the PostGIS/OSM/OSRM tables (§7) are populated, profiles come from a
curated static table + live inventory statistics. Nothing here calls the
network, and every number the responder may quote is present in the output.
"""
from __future__ import annotations

import logging
from statistics import median
from typing import Any

from pydantic import BaseModel, Field

from app.database import get_property_repository
from app.modules.geo.communities import Community, get_community, resolve_area
from app.modules.geo.travel import TravelTime, nearest_communities, travel_summary

logger = logging.getLogger(__name__)

# Curated descriptors (no prices — prices come from stored inventory / DLD).
_PROFILE_TEXT: dict[str, dict[str, str]] = {
    "downtown_dubai": {"en": "the city centre around Burj Khalifa and Dubai Mall — high-rise living, walkable, strong short-let demand.", "ar": "قلب المدينة حول برج خليفة ودبي مول — أبراج سكنية، سهولة التنقل مشياً، وطلب إيجار قوي."},
    "dubai_marina": {"en": "a waterfront high-rise community with the Marina Walk, JBR beach next door and two metro stations.", "ar": "مجتمع أبراج على الواجهة البحرية مع ممشى المارينا وشاطئ JBR ومحطتي مترو."},
    "dubai_hills": {"en": "a master-planned family community with a golf course, Dubai Hills Mall and top schools, 15 minutes to Downtown.", "ar": "مجتمع عائلي متكامل مع ملعب جولف ودبي هيلز مول ومدارس ممتازة، 15 دقيقة عن وسط المدينة."},
    "jvc": {"en": "a mid-market community popular with young families — good value per sq ft, mostly apartments and townhouses.", "ar": "مجتمع متوسط السعر يفضله العائلات الشابة — قيمة جيدة للقدم المربع، أغلبه شقق وتاون هاوس."},
    "business_bay": {"en": "a canal-side business district next to Downtown with newer towers and strong rental demand.", "ar": "منطقة أعمال على القناة بجوار وسط المدينة مع أبراج حديثة وطلب إيجار قوي."},
    "palm_jumeirah": {"en": "the iconic island — beachfront villas and apartments, resort lifestyle, premium pricing.", "ar": "الجزيرة الشهيرة — فلل وشقق على الشاطئ، نمط حياة منتجعي، أسعار مرتفعة."},
    "arabian_ranches": {"en": "an established villa community with schools, a golf club and a quiet suburban feel.", "ar": "مجتمع فلل راسخ مع مدارس ونادي جولف وطابع سكني هادئ."},
    "jlt": {"en": "a lakeside tower cluster opposite the Marina with a metro stop and good value apartments.", "ar": "مجموعة أبراج حول البحيرات مقابل المارينا مع محطة مترو وشقق بأسعار جيدة."},
    "dubai_creek_harbour": {"en": "a new waterfront district by Emaar near the Ras Al Khor sanctuary, 10 minutes to Downtown.", "ar": "منطقة واجهة بحرية جديدة من إعمار قرب محمية رأس الخور، 10 دقائق عن وسط المدينة."},
    "mbr_city": {"en": "a large new district with lagoon communities such as District One and Sobha Hartland.", "ar": "منطقة جديدة كبيرة تضم مجتمعات البحيرات مثل ديستريكت وان وشوبا هارتلاند."},
    "dubai_south": {"en": "the growing district around Al Maktoum airport and Expo City with entry-level pricing.", "ar": "منطقة نامية حول مطار آل مكتوم ومدينة إكسبو بأسعار مناسبة للمبتدئين."},
    "damac_hills": {"en": "a golf community with villas, townhouses and apartments along Hessa Street.", "ar": "مجتمع جولف يضم فللاً وتاون هاوس وشققاً على شارع حصة."},
    "town_square": {"en": "an affordable family community by Nshama with parks and a central plaza.", "ar": "مجتمع عائلي بأسعار معقولة من نشاما مع حدائق وساحة مركزية."},
    "al_furjan": {"en": "a villa and apartment community near Ibn Battuta Mall with two metro stations.", "ar": "مجتمع فلل وشقق قرب ابن بطوطة مول مع محطتي مترو."},
    "jbr": {"en": "beachfront towers on The Walk — the most walkable beach lifestyle in the city.", "ar": "أبراج على شاطئ ذا ووك — أكثر أنماط الحياة الشاطئية سهولة في المشي."},
}


class AreaProfile(BaseModel):
    community_id: str
    name_en: str
    name_ar: str
    summary: str
    lat: float
    lng: float
    listing_count: int = 0
    median_price: float | None = None
    median_price_psf: float | None = None
    price_range: tuple[float, float] | None = None
    data_as_of: str = "inventory"
    travel: list[TravelTime] = Field(default_factory=list)
    nearby_communities: list[dict[str, Any]] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)


async def area_profile(text_or_id: str, workspace_id: str, language: str = "en") -> AreaProfile | None:
    community: Community | None = get_community(text_or_id)
    if community is None:
        matches = resolve_area(text_or_id)
        community = matches[0].community if matches else None
    if community is None:
        return None

    repo = get_property_repository(workspace_id)
    try:
        rows = await repo.search_by_criteria(area=community.name_en, limit=50)
    except Exception as exc:
        logger.warning("area_profile inventory lookup failed: %s", exc)
        rows = []

    prices = [float(r["price"]) for r in rows if r.get("price")]
    psf = [float(r["price_per_sqft"]) for r in rows if r.get("price_per_sqft")]
    psf += [float(r["price"]) / float(r["size_sqft"]) for r in rows if r.get("price") and r.get("size_sqft") and not r.get("price_per_sqft")]

    try:
        travel = await travel_summary(community.id)
    except Exception as exc:
        logger.warning("area_profile travel lookup failed: %s", exc)
        travel = []
    nearby = [
        {"community_id": c.id, "name_en": c.name_en, "name_ar": c.name_ar, "km": km}
        for c, km in nearest_communities(community.id)
    ]

    text = _PROFILE_TEXT.get(community.id, {}).get(language) or _PROFILE_TEXT.get(community.id, {}).get("en") or (
        "a Dubai community." if language == "en" else "منطقة في دبي."
    )
    return AreaProfile(
        community_id=community.id,
        name_en=community.name_en,
        name_ar=community.name_ar,
        summary=text,
        lat=community.lat,
        lng=community.lng,
        listing_count=len(rows),
        median_price=round(median(prices)) if prices else None,
        median_price_psf=round(median(psf)) if psf else None,
        price_range=(min(prices), max(prices)) if prices else None,
        travel=travel,
        nearby_communities=nearby,
    )
