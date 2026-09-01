"""Scrape live Property Finder listings page-by-page and save them locally.

Examples:
  python scripts/propertyfinder_full_site_scrape.py
  python scripts/propertyfinder_full_site_scrape.py --property-type buy_apartment --pages 50
  python scripts/propertyfinder_full_site_scrape.py --property-type rent_apartment --pages 20 --enrich-details

This script uses the existing backend scraper logic and writes JSON output to
`exports/propertyfinder/`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.scrapers.propertyfinder_scraper import PropertyFinderScraper


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def dedupe_listings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for record in records:
        key = record.get("source_url") or record.get("source_id") or json.dumps(record, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


async def enrich_detail_pages(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    async with PropertyFinderScraper() as scraper:
        for idx, listing in enumerate(listings, start=1):
            url = listing.get("source_url")
            if not url:
                enriched.append(listing)
                continue
            try:
                detail = await scraper.scrape_detail(url)
                merged = {**listing}
                if detail.get("description"):
                    merged["description"] = detail["description"]
                if detail.get("amenities"):
                    merged["amenities"] = detail["amenities"]
                if detail.get("images"):
                    merged["images"] = detail["images"]
                enriched.append(merged)
            except Exception as exc:
                merged = {**listing, "detail_error": str(exc)}
                enriched.append(merged)
            if idx % 25 == 0:
                print(f"Enriched {idx}/{len(listings)} listings...")
    return enriched


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--property-type",
        default="buy_apartment",
        choices=["buy_apartment", "buy_villa", "rent_apartment", "rent_villa"],
    )
    parser.add_argument("--area", default=None, help="Optional post-filter on listing area text")
    parser.add_argument("--pages", type=int, default=25, help="How many live portal pages to crawl")
    parser.add_argument("--enrich-details", action="store_true", help="Visit each listing detail page after crawl")
    parser.add_argument("--output", default=None, help="Optional output JSON path")
    args = parser.parse_args()

    exports_dir = ROOT / "exports" / "propertyfinder"
    exports_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        Path(args.output)
        if args.output
        else exports_dir / f"{args.property_type}_{utc_stamp()}.json"
    )

    print(
        f"Starting Property Finder crawl: property_type={args.property_type}, "
        f"pages={args.pages}, area={args.area or 'ALL'}"
    )

    async with PropertyFinderScraper() as scraper:
        listings = await scraper.scrape_listings(
            property_type=args.property_type,
            area=args.area,
            pages=args.pages,
        )

    listings = dedupe_listings(listings)
    print(f"Collected {len(listings)} unique listings from live portal pages.")

    if args.enrich_details and listings:
        print("Enriching listing detail pages...")
        listings = await enrich_detail_pages(listings)

    payload = {
        "source": "propertyfinder",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "property_type": args.property_type,
        "area_filter": args.area,
        "pages_requested": args.pages,
        "detail_enriched": args.enrich_details,
        "count": len(listings),
        "listings": listings,
    }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved crawl output to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
