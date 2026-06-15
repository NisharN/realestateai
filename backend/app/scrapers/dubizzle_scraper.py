"""Dubizzle.com scraper for Dubai classifieds/properties."""
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class DubizzleScraper(BaseScraper):
    """Scraper for Dubizzle.com (classifieds, including properties)."""

    BASE_URL = "https://dubai.dubizzle.com"

    SEARCH_URLS = {
        "buy_apartment": "/property-for-sale/residential/apartment/",
        "buy_villa": "/property-for-sale/residential/villa/",
        "rent_apartment": "/property-for-rent/residential/apartment/",
        "rent_villa": "/property-for-rent/residential/villa/",
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
        """Scrape Dubizzle property listings."""
        listings = []

        try:
            page = await self.get_page()

            search_path = self.SEARCH_URLS.get(property_type, "/property-for-sale/residential/apartment/")

            params = []
            if area:
                params.append(f"city=dubai&location={area.lower().replace(' ', '-')}")
            if min_price:
                params.append(f"price__gte={min_price}")
            if max_price:
                params.append(f"price__lte={max_price}")
            if bedrooms:
                params.append(f"bedrooms={bedrooms}")

            url = urljoin(self.BASE_URL, search_path)
            if params:
                url += "?" + "&".join(params)

            logger.info(f"Scraping Dubizzle: {url}")

            await page.goto(url, wait_until="networkidle", timeout=60000)
            await self.random_delay(3, 6)
            await self.scroll_page(page, scrolls=5)

            # Dubizzle listing selectors
            selectors = [
                '[data-testid="listing-card"]',
                '.listing-card',
                '[class*="listing"]',
            ]

            cards = []
            for selector in selectors:
                cards = await page.query_selector_all(selector)
                if cards:
                    break

            logger.info(f"Found {len(cards)} Dubizzle cards")

            for card in cards[:20]:
                try:
                    listing = await self._parse_dubizzle_card(card)
                    if listing:
                        listings.append(self.normalize_property(listing))
                except Exception as e:
                    logger.warning(f"Dubizzle parse error: {e}")
                    continue

            await page.close()

        except Exception as e:
            logger.error(f"Dubizzle scrape error: {e}")

        return listings

    async def _parse_dubizzle_card(self, card) -> Optional[Dict[str, Any]]:
        """Parse Dubizzle listing card."""
        try:
            title_el = await card.query_selector('h2, [data-testid="title"], .title')
            title = await title_el.inner_text() if title_el else ""

            price_el = await card.query_selector('[data-testid="price"], .price')
            price = await price_el.inner_text() if price_el else ""

            location_el = await card.query_selector('[data-testid="location"], .location')
            location = await location_el.inner_text() if location_el else ""

            img_el = await card.query_selector('img')
            img = await img_el.get_attribute("src") if img_el else ""

            link_el = await card.query_selector('a[href]')
            href = await link_el.get_attribute("href") if link_el else ""

            property_type = "apartment"
            if "villa" in title.lower():
                property_type = "villa"
            elif "penthouse" in title.lower():
                property_type = "penthouse"

            return {
                "id": href.split("/")[-2] if "/" in href else "",
                "url": urljoin(self.BASE_URL, href) if href else "",
                "title": title.strip(),
                "price": price,
                "area": location.strip(),
                "property_type": property_type,
                "images": [img] if img else [],
                "description": "",
            }

        except Exception as e:
            logger.warning(f"Dubizzle card error: {e}")
            return None

    async def scrape_detail(self, url: str) -> Dict[str, Any]:
        """Scrape Dubizzle detail page."""
        try:
            page = await self.get_page()
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await self.random_delay(2, 4)

            desc_el = await page.query_selector('[data-testid="description"], .description')
            description = await desc_el.inner_text() if desc_el else ""

            img_els = await page.query_selector_all('img[class*="gallery"]')
            images = []
            for img in img_els[:10]:
                src = await img.get_attribute("src")
                if src:
                    images.append(src)

            await page.close()

            return {
                "url": url,
                "description": description.strip(),
                "images": images,
            }

        except Exception as e:
            logger.error(f"Dubizzle detail error: {e}")
            return {}


async def scrape_dubizzle(**kwargs) -> List[Dict[str, Any]]:
    """Convenience function."""
    async with DubizzleScraper() as scraper:
        return await scraper.scrape_listings(**kwargs)
