"""Dubai community gazetteer with alias + fuzzy matching (architecture §7).

Pure Python, no network. The Postgres ``communities`` / ``community_aliases``
tables are seeded from ``COMMUNITIES`` so the API and the DB agree.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable


@dataclass(frozen=True)
class Community:
    id: str
    name_en: str
    name_ar: str
    lat: float
    lng: float
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AreaMatch:
    community: Community
    confidence: float
    matched_text: str


COMMUNITIES: tuple[Community, ...] = (
    Community("downtown_dubai", "Downtown Dubai", "وسط مدينة دبي", 25.1972, 55.2744, ("downtown", "burj khalifa area", "داون تاون")),
    Community("dubai_marina", "Dubai Marina", "مرسى دبي", 25.0805, 55.1403, ("marina", "المارينا")),
    Community("jbr", "Jumeirah Beach Residence", "جميرا بيتش ريزيدنس", 25.0783, 55.1336, ("jbr", "beach residence")),
    Community("palm_jumeirah", "Palm Jumeirah", "نخلة جميرا", 25.1124, 55.1390, ("palm", "the palm", "النخلة")),
    Community("business_bay", "Business Bay", "الخليج التجاري", 25.1850, 55.2650, ("bay", "بزنس باي")),
    Community("difc", "DIFC", "مركز دبي المالي العالمي", 25.2110, 55.2800, ("financial centre", "financial center")),
    Community("dubai_hills", "Dubai Hills Estate", "دبي هيلز", 25.1070, 55.2470, ("dubai hills", "hills estate", "hills", "دبي هيلز استيت")),
    Community("jvc", "Jumeirah Village Circle", "قرية جميرا الدائرية", 25.0600, 55.2100, ("jvc", "village circle")),
    Community("jvt", "Jumeirah Village Triangle", "قرية جميرا المثلثة", 25.0480, 55.1900, ("jvt", "village triangle")),
    Community("jlt", "Jumeirah Lakes Towers", "أبراج بحيرات جميرا", 25.0700, 55.1440, ("jlt", "lakes towers")),
    Community("arabian_ranches", "Arabian Ranches", "المرابع العربية", 25.0530, 55.2680, ("ranches", "arabian ranches 2", "arabian ranches 3", "المرابع")),
    Community("damac_hills", "DAMAC Hills", "داماك هيلز", 25.0260, 55.2470, ("damac hills 1", "akoya")),
    Community("damac_hills_2", "DAMAC Hills 2", "داماك هيلز 2", 24.9970, 55.3550, ("akoya oxygen", "damac hills two")),
    Community("mbr_city", "Mohammed Bin Rashid City", "مدينة محمد بن راشد", 25.1650, 55.2960, ("mbr city", "mbr", "district one", "sobha hartland", "meydan")),
    Community("dubai_creek_harbour", "Dubai Creek Harbour", "مرسى خور دبي", 25.2050, 55.3450, ("creek harbour", "creek harbor", "creek")),
    Community("jumeirah", "Jumeirah", "جميرا", 25.2170, 55.2500, ("jumeirah 1", "jumeirah 2", "jumeirah 3")),
    Community("umm_suqeim", "Umm Suqeim", "أم سقيم", 25.1550, 55.2070, ("umm suqeim 1", "umm suqeim 2", "madinat jumeirah")),
    Community("al_barsha", "Al Barsha", "البرشاء", 25.1120, 55.2000, ("barsha", "al barsha 1", "barsha heights", "tecom")),
    Community("motor_city", "Motor City", "موتور سيتي", 25.0470, 55.2400, ("dubai motor city",)),
    Community("sports_city", "Dubai Sports City", "مدينة دبي الرياضية", 25.0390, 55.2190, ("sports city",)),
    Community("dubai_silicon_oasis", "Dubai Silicon Oasis", "واحة دبي للسيليكون", 25.1210, 55.3780, ("silicon oasis", "dso")),
    Community("international_city", "International City", "المدينة العالمية", 25.1620, 55.4060, ("intl city",)),
    Community("discovery_gardens", "Discovery Gardens", "ديسكفري جاردنز", 25.0400, 55.1420, ()),
    Community("al_furjan", "Al Furjan", "الفرجان", 25.0270, 55.1450, ("furjan",)),
    Community("dubai_south", "Dubai South", "دبي الجنوب", 24.8860, 55.1600, ("expo city", "dubai world central", "dwc", "emaar south")),
    Community("town_square", "Town Square", "تاون سكوير", 25.0170, 55.2790, ("nshama", "townsquare")),
    Community("mudon", "Mudon", "مدن", 25.0420, 55.2700, ()),
    Community("the_springs", "The Springs", "الينابيع", 25.0650, 55.1740, ("springs",)),
    Community("the_meadows", "The Meadows", "المروج", 25.0700, 55.1660, ("meadows",)),
    Community("the_lakes", "The Lakes", "البحيرات", 25.0780, 55.1650, ("lakes",)),
    Community("emirates_hills", "Emirates Hills", "تلال الإمارات", 25.0790, 55.1720, ()),
    Community("the_greens", "The Greens", "الروضة", 25.0930, 55.1740, ("greens", "the views")),
    Community("al_quoz", "Al Quoz", "القوز", 25.1380, 55.2290, ("quoz",)),
    Community("bur_dubai", "Bur Dubai", "بر دبي", 25.2530, 55.2960, ("al mankhool", "mankhool")),
    Community("deira", "Deira", "ديرة", 25.2710, 55.3170, ("al rigga", "deira islands")),
    Community("mirdif", "Mirdif", "مردف", 25.2200, 55.4190, ("mirdiff",)),
    Community("al_jaddaf", "Al Jaddaf", "الجداف", 25.2200, 55.3320, ("jaddaf", "culture village", "dubai healthcare city")),
    Community("bluewaters", "Bluewaters Island", "جزيرة بلوواترز", 25.0810, 55.1210, ("bluewaters",)),
    Community("city_walk", "City Walk", "سيتي ووك", 25.2070, 55.2620, ("citywalk", "al wasl")),
    Community("dubai_land", "Dubailand", "دبي لاند", 25.0600, 55.3000, ("dubailand", "dubai land", "villanova", "rukan", "arjan", "majan")),
    Community("jumeirah_golf_estates", "Jumeirah Golf Estates", "جميرا للجولف", 25.0180, 55.1740, ("jge", "golf estates")),
    Community("tilal_al_ghaf", "Tilal Al Ghaf", "تلال الغاف", 25.0380, 55.2270, ("tilal",)),
    Community("dubai_islands", "Dubai Islands", "جزر دبي", 25.3060, 55.3040, ("deira islands",)),
    Community("al_satwa", "Al Satwa", "السطوة", 25.2220, 55.2720, ("satwa",)),
    Community("nad_al_sheba", "Nad Al Sheba", "ند الشبا", 25.1580, 55.3300, ("nas",)),
    Community("dubai_production_city", "Dubai Production City", "مدينة دبي للإنتاج", 25.0340, 55.1900, ("impz", "production city")),
    Community("dubai_studio_city", "Dubai Studio City", "مدينة دبي للاستديوهات", 25.0350, 55.2380, ("studio city",)),
    Community("remraam", "Remraam", "رمرام", 25.0020, 55.2450, ()),
    Community("serena", "Serena", "سيرينا", 25.0130, 55.3130, ()),
    Community("the_valley", "The Valley", "الوادي", 25.0000, 55.5000, ("valley",)),
    Community("al_reem", "Reem", "ريم", 25.0290, 55.2740, ("reem community", "mira")),
    Community("dubai_harbour", "Dubai Harbour", "دبي هاربر", 25.0930, 55.1420, ("harbour", "emaar beachfront", "beachfront")),
    Community("la_mer", "La Mer", "لامير", 25.2330, 55.2580, ("port de la mer", "jumeirah bay")),
    Community("dubai_science_park", "Dubai Science Park", "مجمع دبي للعلوم", 25.0740, 55.2400, ("science park",)),
    Community("al_khail_heights", "Al Khail Heights", "الخيل هايتس", 25.1700, 55.2620, ("al quoz 4",)),
    Community("wadi_al_safa", "Wadi Al Safa", "وادي الصفا", 25.0800, 55.3300, ("liwan", "wadi al safa 2")),
    Community("jumeirah_park", "Jumeirah Park", "جميرا بارك", 25.0490, 55.1580, ()),
    Community("jumeirah_islands", "Jumeirah Islands", "جزر جميرا", 25.0580, 55.1500, ()),
    Community("al_barari", "Al Barari", "البراري", 25.1010, 55.3210, ("barari",)),
    Community("world_islands", "The World Islands", "جزر العالم", 25.2230, 55.1700, ("world islands",)),
)

_BY_ID = {c.id: c for c in COMMUNITIES}

_STOPWORDS = {"in", "at", "near", "around", "the", "area", "dubai", "في", "قرب", "منطقة"}


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[\u064b-\u0652]", "", text)  # Arabic diacritics
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _terms(community: Community) -> list[str]:
    return [normalise(community.name_en), normalise(community.name_ar), *(normalise(a) for a in community.aliases)]


_INDEX: list[tuple[str, Community]] = [(t, c) for c in COMMUNITIES for t in _terms(c) if t]
_INDEX.sort(key=lambda item: -len(item[0]))


def get_community(community_id: str) -> Community | None:
    return _BY_ID.get(community_id)


def resolve_area(text: str, threshold: float = 0.8) -> list[AreaMatch]:
    """Return communities mentioned in ``text`` with a confidence per match.

    Exact alias / name matches score 1.0; fuzzy matches (typos such as
    "dubai hils") score by similarity and only count above ``threshold``.
    """
    norm = normalise(text)
    if not norm:
        return []
    matches: dict[str, AreaMatch] = {}

    for term, community in _INDEX:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", norm):
            existing = matches.get(community.id)
            if existing is None or existing.confidence < 1.0:
                matches[community.id] = AreaMatch(community, 1.0, term)

    if matches:
        return sorted(matches.values(), key=lambda m: -m.confidence)

    words = [w for w in norm.split() if w not in _STOPWORDS]
    candidates: Iterable[str] = set(
        [" ".join(words[i : i + n]) for n in (1, 2, 3) for i in range(len(words) - n + 1)]
    )
    best: dict[str, AreaMatch] = {}
    for candidate in candidates:
        if len(candidate) < 3:
            continue
        for term, community in _INDEX:
            if len(term) < 4 or abs(len(term) - len(candidate)) > 4:
                continue
            ratio = SequenceMatcher(None, candidate, term).ratio()
            if ratio >= threshold:
                existing = best.get(community.id)
                if existing is None or ratio > existing.confidence:
                    best[community.id] = AreaMatch(community, round(ratio, 3), candidate)
    return sorted(best.values(), key=lambda m: -m.confidence)


def community_rows() -> list[dict[str, object]]:
    return [
        {"id": c.id, "name_en": c.name_en, "name_ar": c.name_ar, "lat": c.lat, "lng": c.lng}
        for c in COMMUNITIES
    ]


def alias_rows() -> list[dict[str, str]]:
    return [{"alias": t, "community_id": c.id} for t, c in _INDEX]
