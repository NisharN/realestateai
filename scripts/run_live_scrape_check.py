"""Run a live scraper smoke test with current proxy/session settings.

Examples:
  python scripts/run_live_scrape_check.py
  python scripts/run_live_scrape_check.py --site propertyfinder
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.scrapers import scrape_bayut, scrape_dubizzle, scrape_propertyfinder


SCRAPERS = {
    "bayut": scrape_bayut,
    "dubizzle": scrape_dubizzle,
    "propertyfinder": scrape_propertyfinder,
}


async def run_one(site: str) -> dict:
    fn = SCRAPERS[site]
    try:
        listings = await fn(property_type="buy_apartment", pages=1)
        return {
            "site": site,
            "count": len(listings),
            "sample": listings[:2],
        }
    except Exception as exc:
        return {
            "site": site,
            "error": str(exc),
        }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", choices=sorted(SCRAPERS))
    args = parser.parse_args()

    sites = [args.site] if args.site else sorted(SCRAPERS)
    results = []
    for site in sites:
        results.append(await run_one(site))

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
