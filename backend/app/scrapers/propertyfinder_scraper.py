"""PropertyFinder.ae scraper for Dubai real estate."""
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class PropertyFinderScraper(BaseScraper):
    """Scraper for PropertyFinder.ae (major Dubai portal)."""

    BASE_URL = "https://www.propertyfinder.ae"

    SEARCH_URLS = {
        "buy_apartment": "/en/buy/apartments-for-sale.html",
        "buy_villa": "/en/buy/villas-for-sale.html",
        "rent_apartment": "/en/rent/apartments-for-rent.html",
        "rent_villa": "/en/rent/villas-for-rent.html",
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
        """Scrape PropertyFinder listings."""
        listings = []

        try:
            page = await self.get_page()

            search_path = self.SEARCH_URLS.get(property_type, "/en/buy/apartments-for-sale.html")

            # Build query params
            params = []
            if area:
                params.append(f"location={area.lower().replace(' ', '-')}")
            if min_price:
                params.append(f"price_min={min_price}")
            if max_price:
                params.append(f"price_max={max_price}")
            if bedrooms:
                params.append(f"bedrooms={bedrooms}")

            url = urljoin(self.BASE_URL, search_path)
            if params:
                url += "?" + "&".join(params)

            logger.info(f"Scraping PropertyFinder: {url}")

            await page.goto(url, wait_until="networkidle", timeout=60000)
            await self.random_delay(3, 6)
            await self.scroll_page(page, scrolls=5)

            # PropertyFinder uses card-based layout
            selectors = [
                '[data-testid="property-card"]',
                '.card',
                '[class*="property-card"]',
                'article',
            ]

            cards = []
            for selector in selectors:
                cards = await page.query_selector_all(selector)
                if cards:
                    break

            logger.info(f"Found {len(cards)} PropertyFinder cards")

            for card in cards[:20]:
                try:
                    listing = await self._parse_pf_card(card)
                    if listing:
                        listings.append(self.normalize_property(listing))
                except Exception as e:
                    logger.warning(f"PF card parse error: {e}")
                    continue

            await page.close()

        except Exception as e:
            logger.error(f"PropertyFinder scrape error: {e}")

        return listings

    async def _parse_pf_card(self, card) -> Optional[Dict[str, Any]]:
        """Parse PropertyFinder card."""
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

            # Extract details
            beds_el = await card.query_selector('[data-testid="bedrooms"], [aria-label*="bed"]')
            beds = await beds_el.inner_text() if beds_el else None

            baths_el = await card.query_selector('[data-testid="bathrooms"], [aria-label*="bath"]')
            baths = await baths_el.inner_text() if baths_el else None

            size_el = await card.query_selector('[data-testid="size"], [aria-label*="sqft"]')
            size = await size_el.inner_text() if size_el else None

            property_type = "apartment"
            if "villa" in title.lower():
                property_type = "villa"
            elif "penthouse" in title.lower():
                property_type = "penthouse"

            return {
                "id": href.split("-")[-1].replace(".html", "") if href else "",
                "url": urljoin(self.BASE_URL, href) if href else "",
                "title": title.strip(),
                "price": price,
                "area": location.strip(),
                "property_type": property_type,
                "bedrooms": beds,
                "bathrooms": baths,
                "size": size,
                "images": [img] if img else [],
                "description": "",
            }

        except Exception as e:
            logger.warning(f"PF parse error: {e}")
            return None

    async def scrape_detail(self, url: str) -> Dict[str, Any]:
        """Scrape PropertyFinder detail page."""
        try:
            page = await self.get_page()
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await self.random_delay(2, 4)

            desc_el = await page.query_selector('[data-testid="description"], .description')
            description = await desc_el.inner_text() if desc_el else ""

            amenity_els = await page.query_selector_all('[data-testid="amenity"], .amenity')
            amenities = [await el.inner_text() for el in amenity_els if await el.inner_text()]

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
                "amenities": [a.strip() for a in amenities if a.strip()],
                "images": images,
            }

        except Exception as e:
            logger.error(f"PF detail error: {e}")
            return {}


async def scrape_propertyfinder(**kwargs) -> List[Dict[str, Any]]:
    """Convenience function."""
    async with PropertyFinderScraper() as scraper:
        return await scraper.scrape_listings(**kwargs)
