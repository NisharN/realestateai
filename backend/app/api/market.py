"""Market data: comparable transactions for the map and price positioning.

Backs the DLD comps map — the most demo-critical screen in the product per
the PM ("the thing a broker forwards to her principal"), and the thing that
gives an agent ammunition in a price-objection conversation with a landlord.

Mock mode serves representative sample rows shaped like the Dubai Land
Department open-data extract. Live mode is wired to Dubai Pulse, which
publishes DLD transactions as free open data. The response always states
which mode produced it so nobody mistakes demo rows for real market data.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from app.auth import RequestContext, get_request_context
from app.config import get_settings
from app.seed_data import COMMUNITIES, community_median_ppsf, mock_dld_transactions

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/transactions")
async def list_transactions(
    area: Optional[str] = Query(None, description="Filter by community"),
    property_type: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Comparable transactions for plotting on the map."""
    settings = get_settings()
    mode = (settings.DATA_MODE_DLD or "mock").lower()

    rows = await _load_transactions(mode)

    if area:
        rows = [r for r in rows if r["area"].lower() == area.lower()]
    if property_type:
        rows = [r for r in rows if r["property_type"] == property_type]
    if min_price is not None:
        rows = [r for r in rows if r["amount_aed"] >= min_price]
    if max_price is not None:
        rows = [r for r in rows if r["amount_aed"] <= max_price]

    return {
        "mode": mode,
        "is_demo_data": mode != "live",
        "source": (
            "Representative sample rows — not live DLD data"
            if mode == "mock"
            else "Dubai Land Department via Dubai Pulse open data"
        ),
        "count": len(rows[:limit]),
        "transactions": rows[:limit],
    }


@router.get("/communities")
async def list_communities(
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Community centroids and median price-per-sqft, for map layers."""
    medians = community_median_ppsf()
    return {
        "communities": [
            {
                "name": name,
                "lat": meta["lat"],
                "lng": meta["lng"],
                "median_price_per_sqft": medians.get(name),
                "typical_type": meta["type_bias"],
            }
            for name, meta in COMMUNITIES.items()
        ]
    }


@router.get("/comps")
async def price_positioning(
    area: str = Query(..., description="Community to compare against"),
    price: float = Query(..., description="Asking price in AED"),
    size_sqft: Optional[float] = Query(None),
    context: RequestContext = Depends(get_request_context),
) -> Dict[str, Any]:
    """Position an asking price against recent comparable sales.

    This is what an agent uses when a landlord insists their unit is worth
    more than the market says — a concrete number rather than an opinion.
    """
    mode = (get_settings().DATA_MODE_DLD or "mock").lower()
    rows = [r for r in await _load_transactions(mode) if r["area"].lower() == area.lower()]

    if not rows:
        return {"area": area, "sample_size": 0, "verdict": "no_comparable_data"}

    amounts = sorted(r["amount_aed"] for r in rows)
    ppsfs = sorted(r["price_per_sqft"] for r in rows if r.get("price_per_sqft"))
    median_amount = _median(amounts)
    median_ppsf = _median(ppsfs)

    result: Dict[str, Any] = {
        "area": area,
        "mode": mode,
        "sample_size": len(rows),
        "median_amount_aed": round(median_amount, 2),
        "median_price_per_sqft": round(median_ppsf, 2),
        "asking_price_aed": price,
    }

    # Compare like with like. A total price is only meaningful against
    # similarly-sized units, so when we know the size we judge on
    # price-per-sqft — otherwise a large unit looks "expensive" purely for
    # being large, which is exactly the kind of wrong number that loses an
    # agent an argument with a landlord.
    if size_sqft and median_ppsf:
        asking_ppsf = price / size_sqft
        delta = (asking_ppsf - median_ppsf) / median_ppsf
        result["asking_price_per_sqft"] = round(asking_ppsf, 2)
        result["basis"] = "price_per_sqft"
    else:
        delta = (price - median_amount) / median_amount if median_amount else 0.0
        result["basis"] = "total_price"
        result["caveat"] = (
            "Compared against all sizes in this community. Provide size_sqft "
            "for a like-for-like price-per-sqft comparison."
        )

    if delta <= -0.07:
        verdict = "below_market"
    elif delta >= 0.07:
        verdict = "above_market"
    else:
        verdict = "in_line"

    result["delta_pct"] = round(delta * 100, 1)
    result["verdict"] = verdict
    return result


async def _load_transactions(mode: str) -> List[Dict[str, Any]]:
    """Mock returns the bundled sample; live pulls the Dubai Pulse extract."""
    if mode != "live":
        return mock_dld_transactions()

    try:
        from app.services.dld_feed import fetch_dld_transactions

        rows = await fetch_dld_transactions()
        if rows:
            return rows
        logger.warning("DLD live feed returned no rows; falling back to sample data")
    except Exception as exc:
        logger.error("DLD live feed failed, falling back to sample data: %s", exc)
    return mock_dld_transactions()


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2
