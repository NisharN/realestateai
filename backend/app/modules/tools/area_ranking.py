"""area_ranking tool — "which areas give good rental yield?".

Gross yield per community is computed only from stored inventory (median annual
rent listing ÷ median sale listing, same community). Communities without both a
rent and a sale sample are skipped rather than estimated, so every number the
responder quotes is backed by listings. Results are cached per workspace.
"""
from __future__ import annotations

import logging
import time
from statistics import median
from typing import Any

from pydantic import BaseModel, Field

from app.database import get_property_repository
from app.modules.geo.communities import COMMUNITIES

logger = logging.getLogger(__name__)

CACHE_TTL_S = 600
MIN_SAMPLES = 3
SAMPLE_LIMIT = 200
_cache: dict[str, tuple[float, "AreaRanking"]] = {}


class AreaYield(BaseModel):
    community_id: str
    name_en: str
    name_ar: str
    gross_yield_pct: float
    median_sale_price: float
    median_annual_rent: float
    sale_samples: int
    rent_samples: int


class AreaRanking(BaseModel):
    metric: str = "gross_yield"
    areas: list[AreaYield] = Field(default_factory=list)
    data_as_of: str = "inventory"


def _prices(rows: list[dict[str, Any]], kind: str) -> list[float]:
    out: list[float] = []
    for r in rows:
        price = r.get("price")
        if price and (r.get("listing_type") or "").lower() == kind:
            out.append(float(price))
    return out


async def _samples(repo: Any, area: str) -> tuple[list[float], list[float]]:
    """Sale and rent samples are fetched with independent limits so a rental-heavy
    community cannot crowd its sale listings out of a single bounded query."""
    sale_rows = await repo.search_by_criteria(area=area, limit=SAMPLE_LIMIT, listing_type="sale")
    rent_rows = await repo.search_by_criteria(area=area, limit=SAMPLE_LIMIT, listing_type="rent")
    return _prices(sale_rows, "sale"), _prices(rent_rows, "rent")


async def area_ranking(workspace_id: str, limit: int = 3) -> AreaRanking:
    cached = _cache.get(workspace_id)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
        return cached[1].model_copy(update={"areas": cached[1].areas[:limit]})

    repo = get_property_repository(workspace_id)
    ranked: list[AreaYield] = []
    for c in COMMUNITIES:
        try:
            sale, rent = await _samples(repo, c.name_en)
        except Exception as exc:
            logger.warning("area_ranking lookup failed for %s: %s", c.id, exc)
            continue
        if len(sale) < MIN_SAMPLES or len(rent) < MIN_SAMPLES:
            continue
        sale_med, rent_med = median(sale), median(rent)
        if sale_med <= 0:
            continue
        ranked.append(
            AreaYield(
                community_id=c.id,
                name_en=c.name_en,
                name_ar=c.name_ar,
                gross_yield_pct=round(100 * rent_med / sale_med, 1),
                median_sale_price=sale_med,
                median_annual_rent=rent_med,
                sale_samples=len(sale),
                rent_samples=len(rent),
            )
        )
    ranked.sort(key=lambda a: a.gross_yield_pct, reverse=True)
    result = AreaRanking(areas=ranked)
    _cache[workspace_id] = (time.monotonic(), result)
    return result.model_copy(update={"areas": ranked[:limit]})


def reset_cache() -> None:
    _cache.clear()
