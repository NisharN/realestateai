"""RapidAPI UAE real-estate adapter."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class RapidApiUAEScraper:
    """Load UAE property/developer records through RapidAPI.

    This is useful when public browse pages are blocked and you want a provider-
    backed source instead. The exact payload can vary by endpoint, so the
    adapter is intentionally defensive.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = f"https://{self.settings.RAPIDAPI_UAE_REAL_ESTATE_HOST}"

    async def developer_search_by_name(
        self,
        query: str,
        page: int = 1,
        langs: str = "en",
    ) -> Dict[str, Any]:
        headers = self._headers()
        if not headers:
            return {"results": [], "errors": ["RapidAPI credentials are not configured"]}

        params = {"query": query, "page": page, "langs": langs}
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(f"{self.base_url}/developer-search-by-name", params=params)
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else {"results": payload}

    async def property_search(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        headers = self._headers()
        if not headers:
            return []

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(f"{self.base_url}/{endpoint.lstrip('/')}", params=params or {})
            response.raise_for_status()
            payload = response.json()

        records: List[Dict[str, Any]]
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            for key in ("results", "data", "properties", "items", "listings"):
                if isinstance(payload.get(key), list):
                    records = payload[key]
                    break
            else:
                records = []
        else:
            records = []

        return [self.normalize_property(row) for row in records]

    def normalize_property(self, row: Dict[str, Any]) -> Dict[str, Any]:
        source_url = row.get("url") or row.get("permalink") or row.get("listing_url") or ""
        return {
            "source": "rapidapi_uae",
            "source_id": str(row.get("id") or row.get("property_id") or row.get("slug") or ""),
            "source_url": source_url,
            "title": row.get("title") or row.get("name") or row.get("headline") or "",
            "description": row.get("description") or row.get("details") or "",
            "price": row.get("price") or row.get("amount"),
            "price_per_sqft": row.get("price_per_sqft") or row.get("ppsf"),
            "area": row.get("area") or row.get("location") or row.get("community") or "",
            "property_type": (row.get("property_type") or row.get("type") or "").lower(),
            "bedrooms": row.get("bedrooms") or row.get("beds"),
            "bathrooms": row.get("bathrooms") or row.get("baths"),
            "size_sqft": row.get("size_sqft") or row.get("area_sqft") or row.get("size"),
            "images": row.get("images") or row.get("photos") or [],
            "video_url": row.get("video_url"),
            "floor_plan_url": row.get("floor_plan_url"),
            "map_lat": row.get("map_lat") or row.get("latitude"),
            "map_lng": row.get("map_lng") or row.get("longitude"),
            "amenities": row.get("amenities") or row.get("features") or [],
            "developer": row.get("developer") or row.get("developer_name"),
            "completion_date": row.get("completion_date"),
            "is_active": True,
            "rapidapi_source": True,
        }

    def _headers(self) -> Optional[Dict[str, str]]:
        api_key = (self.settings.RAPIDAPI_UAE_REAL_ESTATE_KEY or "").strip()
        host = (self.settings.RAPIDAPI_UAE_REAL_ESTATE_HOST or "").strip()
        if not api_key or not host:
            return None
        return {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": host,
            "Content-Type": "application/json",
        }


async def rapidapi_developer_search_by_name(query: str, page: int = 1, langs: str = "en") -> Dict[str, Any]:
    scraper = RapidApiUAEScraper()
    return await scraper.developer_search_by_name(query=query, page=page, langs=langs)


async def scrape_rapidapi_properties(endpoint: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    scraper = RapidApiUAEScraper()
    return await scraper.property_search(endpoint=endpoint, params=params)
