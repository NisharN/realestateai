"""Licensed property sources.

Only sources the brokerage is entitled to use live here: an approved partner
JSON feed and a licensed RapidAPI provider. Portal scraping (Bayut, Dubizzle,
Property Finder) is out of scope and there is no synthetic listing fallback —
if a source returns nothing, the inventory stays as it is.
"""
from __future__ import annotations

from .approved_feed import ApprovedFeedScraper, scrape_approved_feed  # noqa: F401
from .rapidapi_uae import (  # noqa: F401
    RapidApiUAEScraper,
    rapidapi_developer_search_by_name,
    scrape_rapidapi_properties,
)

__all__ = [
    "ApprovedFeedScraper",
    "RapidApiUAEScraper",
    "scrape_approved_feed",
    "scrape_rapidapi_properties",
    "rapidapi_developer_search_by_name",
]
