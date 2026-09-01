"""Capture a reusable browser storage state for protected portals.

Usage:
  python scripts/capture_scraper_session.py bayut
  python scripts/capture_scraper_session.py dubizzle

This opens a visible browser. Solve any challenge manually, wait until the
listings page is visible, then press Enter in the terminal to save cookies and
local storage to the configured state file.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from playwright.async_api import async_playwright

from app.config import get_settings

PORTAL_URLS = {
    "bayut": "https://www.bayut.com/for-sale/apartments/dubai/",
    "dubizzle": "https://dubai.dubizzle.com/en/property-for-sale/residential/apartment/",
    "propertyfinder": "https://www.propertyfinder.ae/en/buy/dubai/apartments-for-sale.html",
}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("portal", choices=sorted(PORTAL_URLS))
    parser.add_argument("--state-path", help="Override storage state path")
    parser.add_argument("--channel", help="Browser channel, e.g. chrome")
    args = parser.parse_args()

    settings = get_settings()
    state_dir = ROOT / "backend" / "runtime" / "scraper-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state_path) if args.state_path else state_dir / f"{args.portal}.json"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel=args.channel or settings.SCRAPER_BROWSER_CHANNEL or None,
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 960},
            locale="en-US",
            timezone_id="Asia/Dubai",
        )
        page = await context.new_page()
        await page.goto(PORTAL_URLS[args.portal], wait_until="domcontentloaded", timeout=60000)

        print(f"Opened {args.portal} at {page.url}")
        print("Solve any CAPTCHA/login challenge in the browser window.")
        print("When the listing page looks correct, press Enter here to save session state.")
        input()

        await context.storage_state(path=str(state_path))
        await browser.close()

    print(f"Saved storage state to: {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
