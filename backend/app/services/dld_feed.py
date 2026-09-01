"""Dubai Land Department transactions via Dubai Pulse open data.

Dubai Pulse (dubaipulse.gov.ae) publishes DLD registered transactions as free
open data — no partner approval, no scraping, no ToS grey area. That makes it
the one genuinely free, genuinely legitimate market-data source available to
this product, which is why the comps map is built on it rather than on portal
listing data.

Only used when ``DATA_MODE_DLD=live``. The default mock mode serves bundled
sample rows instead, so the map works offline. Any failure here falls back to
that sample data rather than breaking the map.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Approximate community centroids, used to give a transaction a map position
# when the source row carries an area name but no coordinates.
from app.seed_data import COMMUNITIES  # noqa: E402

SQM_TO_SQFT = 10.7639


async def fetch_dld_transactions(limit: int = 1000) -> List[Dict[str, Any]]:
    """Fetch and normalise recent DLD transactions.

    The Dubai Pulse dataset endpoint is configurable because the exact open-data
    URL and any access token depend on how the deployment registers with the
    platform. Without a configured URL this returns an empty list and the
    caller falls back to sample data.
    """
    settings = get_settings()
    url = getattr(settings, "DLD_TRANSACTIONS_URL", "") or ""
    if not url:
        logger.info("DLD_TRANSACTIONS_URL not configured; using sample comps")
        return []

    headers: Dict[str, str] = {"Accept": "application/json"}
    token = getattr(settings, "DLD_API_TOKEN", "") or ""
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers, params={"limit": limit})
        response.raise_for_status()
        payload = response.json()

    rows = _extract_rows(payload)
    normalised = [_normalise(row) for row in rows]
    return [row for row in normalised if row is not None][:limit]


def _extract_rows(payload: Any) -> List[Dict[str, Any]]:
    """Open-data APIs wrap records differently; handle the common shapes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("records", "result", "data", "items", "value"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict) and isinstance(value.get("records"), list):
                return value["records"]
    return []


def _normalise(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map a DLD row onto the same shape the mock data uses."""
    try:
        area = _first(row, "area_name_en", "AREA_EN", "area", "community")
        amount = _number(_first(row, "actual_worth", "TRANS_VALUE", "amount", "meter_sale_price"))
        if not area or not amount:
            return None

        size_sqm = _number(_first(row, "procedure_area", "PROCEDURE_AREA", "area_sqm"))
        size_sqft = round(size_sqm * SQM_TO_SQFT, 2) if size_sqm else None

        centroid = COMMUNITIES.get(area, {})
        return {
            "transaction_id": str(
                _first(row, "transaction_id", "TRANSACTION_NUMBER", "id") or ""
            ),
            "area": area,
            "property_type": _map_type(_first(row, "property_type_en", "PROP_TYPE_EN", "property_type")),
            "rooms": _rooms(_first(row, "rooms_en", "ROOMS_EN", "rooms")),
            "size_sqft": size_sqft,
            "amount_aed": float(amount),
            "price_per_sqft": round(amount / size_sqft, 2) if size_sqft else None,
            "transaction_date": str(
                _first(row, "instance_date", "TRANSACTION_DATE", "date") or ""
            )[:10],
            "lat": _number(_first(row, "latitude", "lat")) or centroid.get("lat"),
            "lng": _number(_first(row, "longitude", "lng")) or centroid.get("lng"),
            "is_demo_data": False,
        }
    except Exception as exc:  # pragma: no cover - defensive on open data
        logger.debug("Skipping unparseable DLD row: %s", exc)
        return None


def _first(row: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _map_type(value: Any) -> str:
    text = str(value or "").lower()
    if "villa" in text:
        return "villa"
    if "town" in text:
        return "townhouse"
    if "land" in text:
        return "land"
    return "apartment"


def _rooms(value: Any) -> Optional[int]:
    text = str(value or "").lower()
    if "studio" in text:
        return 0
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None
