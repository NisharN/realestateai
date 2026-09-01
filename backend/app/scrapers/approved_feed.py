"""Approved alternate property feed adapter.

Use this when a portal's public browse pages are challenge-protected but you
have an approved export/feed from a partner, CRM, or listing provider.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class ApprovedFeedScraper:
    """Load listings from an approved JSON feed."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def scrape_listings(
        self,
        area: Optional[str] = None,
        property_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if not self.settings.APPROVED_FEED_URL:
            return []

        headers = {"Accept": "application/json"}
        if self.settings.APPROVED_FEED_TOKEN:
            headers["Authorization"] = f"Bearer {self.settings.APPROVED_FEED_TOKEN}"

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(self.settings.APPROVED_FEED_URL)
            response.raise_for_status()
            payload = response.json()

        records = payload if isinstance(payload, list) else payload.get("listings", [])
        normalized: List[Dict[str, Any]] = []
        for row in records[:limit]:
            item = self.normalize_property(row)
            if area and area.lower() not in (item.get("area") or "").lower():
                continue
            if property_type and property_type.lower() != (item.get("property_type") or "").lower():
                continue
            normalized.append(item)
        return normalized

    def normalize_property(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "source": row.get("source", "approved_feed"),
            "source_id": str(row.get("id") or row.get("source_id") or ""),
            "source_url": row.get("url") or row.get("source_url") or "",
            "title": row.get("title") or "",
            "description": row.get("description") or "",
            "price": row.get("price"),
            "price_per_sqft": row.get("price_per_sqft"),
            "area": row.get("area") or row.get("location") or "",
            "property_type": (row.get("property_type") or "").lower(),
            "bedrooms": row.get("bedrooms"),
            "bathrooms": row.get("bathrooms"),
            "size_sqft": row.get("size_sqft") or row.get("area_sqft"),
            "images": row.get("images") or [],
            "video_url": row.get("video_url"),
            "floor_plan_url": row.get("floor_plan_url"),
            "map_lat": row.get("map_lat") or row.get("latitude"),
            "map_lng": row.get("map_lng") or row.get("longitude"),
            "amenities": row.get("amenities") or [],
            "developer": row.get("developer"),
            "completion_date": row.get("completion_date"),
            "is_active": True,
            "approved_feed": True,
        }


async def scrape_approved_feed(**kwargs) -> List[Dict[str, Any]]:
    """Convenience wrapper for approved feed ingestion."""
    scraper = ApprovedFeedScraper()
    return await scraper.scrape_listings(**kwargs)
