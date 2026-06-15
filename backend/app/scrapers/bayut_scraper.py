"""Bayut.com scraper for Dubai real estate listings."""
import asyncio
import json
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, quote

from playwright.async_api import Page

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class BayutScraper(BaseScraper):
    """Scraper for Bayut.com (Dubai's largest property portal)."""

    BASE_URL = "https://www.bayut.com"

    # Search URLs for different property types
    SEARCH_URLS = {
        "buy_apartment": "/for-sale/apartments/dubai/",
        "buy_villa": "/for-sale/villas/dubai/",
        "buy_penthouse": "/for-sale/penthouses/dubai/",
        "rent_apartment": "/for-rent/apartments/dubai/",
        "rent_villa": "/for-rent/villas/dubai/",
        "rent_penthouse": "/for-rent/penthouses/dubai/",
    }

    async def scrape_listings(
        self,
        property_type: str = "buy_apartment",
        area: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        bedrooms: Optional[int] = None,
        pages: int = 1
    ) -> List[Dict[str, Any]]:
        """Scrape property listings from Bayut.

        Args:
            property_type: One of SEARCH_URLS keys
            area: Dubai area name (e.g., "downtown-dubai")
            min_price: Minimum price in AED
            max_price: Maximum price in AED
            bedrooms: Number of bedrooms
            pages: Number of pages to scrape
        """
        listings = []

        try:
            page = await self.get_page()

            # Build search URL
            search_path = self.SEARCH_URLS.get(property_type, "/for-sale/apartments/dubai/")
            if area:
                search_path = f"{search_path}{area.lower().replace(' ', '-')}/"

            # Add query params
            params = []
            if min_price:
                params.append(f"price_min={min_price}")
            if max_price:
                params.append(f"price_max={max_price}")
            if bedrooms:
                params.append(f"bedrooms={bedrooms}")

            url = urljoin(self.BASE_URL, search_path)
            if params:
                url += "?" + "&".join(params)

            logger.info(f"Scraping Bayut: {url}")

            await page.goto(url, wait_until="networkidle", timeout=60000)
            await self.random_delay(3, 6)
            await self.scroll_page(page, scrolls=5)

            # Extract listings using multiple selectors (Bayut changes these often)
            selectors = [
                '[data-testid="property-card"]',
                '.ef447dde',
                '[role="article"]',
                '.ca3976f1',  # legacy
            ]

            cards = []
            for selector in selectors:
                cards = await page.query_selector_all(selector)
                if cards:
                    break

            logger.info(f"Found {len(cards)} listing cards")

            for card in cards[:20]:  # Limit per page
                try:
                    listing = await self._parse_card(card)
                    if listing:
                        listings.append(self.normalize_property(listing))
                except Exception as e:
                    logger.warning(f"Error parsing card: {e}")
                    continue

            # Pagination
            for p in range(2, pages + 1):
                next_url = f"{url}&page={p}"
                logger.info(f"Scraping page {p}: {next_url}")

                await page.goto(next_url, wait_until="networkidle", timeout=60000)
                await self.random_delay(3, 6)
                await self.scroll_page(page, scrolls=5)

                for selector in selectors:
                    cards = await page.query_selector_all(selector)
                    if cards:
                        break

                for card in cards[:20]:
                    try:
                        listing = await self._parse_card(card)
                        if listing:
                            listings.append(self.normalize_property(listing))
                    except Exception as e:
                        continue

            await page.close()

        except Exception as e:
            logger.error(f"Bayut scraping error: {e}")

        logger.info(f"Total Bayut listings scraped: {len(listings)}")
        return listings

    async def _parse_card(self, card) -> Optional[Dict[str, Any]]:
        """Parse a single property card element."""
        try:
            # Title
            title_el = await card.query_selector('h2, [data-testid="title"], .title, a[aria-label]')
            title = await title_el.inner_text() if title_el else ""

            # Price
            price_el = await card.query_selector('[data-testid="price"], .price, .c4fc20ba')
            price_text = await price_el.inner_text() if price_el else ""

            # Location/Area
            location_el = await card.query_selector('[data-testid="location"], .location, [aria-label*="location"]')
            location = await location_el.inner_text() if location_el else ""

            # Details (beds, baths, size)
            details = await card.query_selector_all('[data-testid="property-details"] span, .details span')
            beds, baths, size = None, None, None
            for detail in details:
                text = await detail.inner_text()
                if "bed" in text.lower():
                    beds = text
                elif "bath" in text.lower():
                    baths = text
                elif "sqft" in text.lower() or "sqm" in text.lower():
                    size = text

            # Image
            img_el = await card.query_selector('img')
            img_url = await img_el.get_attribute("src") if img_el else ""

            # URL
            link_el = await card.query_selector('a[href]')
            href = await link_el.get_attribute("href") if link_el else ""

            # Property type from title
            property_type = "apartment"
            title_lower = title.lower()
            if "villa" in title_lower:
                property_type = "villa"
            elif "penthouse" in title_lower:
                property_type = "penthouse"
            elif "townhouse" in title_lower:
                property_type = "townhouse"

            return {
                "id": href.split("/")[-2] if "/" in href else "",
                "url": urljoin(self.BASE_URL, href) if href else "",
                "title": title.strip(),
                "price": price_text,
                "area": location.strip(),
                "property_type": property_type,
                "bedrooms": beds,
                "bathrooms": baths,
                "size": size,
                "images": [img_url] if img_url else [],
                "description": "",
            }

        except Exception as e:
            logger.warning(f"Card parse error: {e}")
            return None

    async def scrape_detail(self, url: str) -> Dict[str, Any]:
        """Scrape detailed property page."""
        try:
            page = await self.get_page()
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await self.random_delay(2, 4)

            # Description
            desc_el = await page.query_selector('[data-testid="description"], .description, [class*="description"]')
            description = await desc_el.inner_text() if desc_el else ""

            # Amenities
            amenity_els = await page.query_selector_all('[data-testid="amenity"], .amenity, [class*="amenities"] li')
            amenities = []
            for el in amenity_els:
                text = await el.inner_text()
                if text:
                    amenities.append(text.strip())

            # Images gallery
            img_els = await page.query_selector_all('img[class*="gallery"], [data-testid="gallery"] img')
            images = []
            for img in img_els[:10]:
                src = await img.get_attribute("src")
                if src and "http" in src:
                    images.append(src)

            # Map coordinates (often in script tags)
            scripts = await page.query_selector_all("script")
            lat, lng = None, None
            for script in scripts:
                text = await script.inner_text()
                if "latitude" in text.lower() or "longitude" in text.lower():
                    import re
                    lat_match = re.search(r'latitude["']?\s*[:=]\s*([\d.]+)', text)
                    lng_match = re.search(r'longitude["']?\s*[:=]\s*([\d.]+)', text)
                    if lat_match:
                        lat = float(lat_match.group(1))
                    if lng_match:
                        lng = float(lng_match.group(1))
                    if lat and lng:
                        break

            await page.close()

            return {
                "url": url,
                "description": description.strip(),
                "amenities": amenities,
                "images": images,
                "latitude": lat,
                "longitude": lng,
            }

        except Exception as e:
            logger.error(f"Detail scrape error for {url}: {e}")
            return {}


# Convenience function for direct use
async def scrape_bayut(**kwargs) -> List[Dict[str, Any]]:
    """Scrape Bayut listings."""
    async with BayutScraper() as scraper:
        return await scraper.scrape_listings(**kwargs)
