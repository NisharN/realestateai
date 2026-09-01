"""Dubizzle.com scraper for Dubai classifieds/properties."""
import logging
import re
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

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                try:
                    await page.goto(url, wait_until="load", timeout=30000)
                except Exception:
                    return listings

            await self.random_delay(3, 6)
            block_reason = await self.detect_block(page, "Dubizzle")
            if block_reason:
                logger.warning(block_reason)
                await page.close()
                return listings
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
                        normalized = self.normalize_property(listing)
                        if self.is_legit_listing(normalized):
                            listings.append(normalized)
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
            text = " ".join((await card.inner_text()).split())
            lines = [line.strip() for line in (await card.inner_text()).splitlines() if line.strip()]

            href = ""
            links = await card.query_selector_all("a[href]")
            for anchor in links:
                candidate = await anchor.get_attribute("href")
                if candidate and "/property-for-sale/" in candidate:
                    href = candidate
                    break
            if not href:
                return None

            title = ""
            location = ""
            for i, line in enumerate(lines):
                if line.startswith("AED"):
                    for candidate in lines[i + 1 : i + 8]:
                        lower = candidate.lower()
                        if len(candidate) > 10 and not lower.startswith(("handover", "payment plan", "email", "call", "whatsapp")):
                            title = candidate
                            break
                    for candidate in lines[i + 1 : i + 10]:
                        if "," in candidate and "dubai" in candidate.lower():
                            location = candidate
                            break
                    if title:
                        break

            price_match = re.search(r"AED\s*([\d,]+)", text)
            price = price_match.group(1) if price_match else ""

            img_el = await card.query_selector('img')
            img = await img_el.get_attribute("src") if img_el else ""

            beds = None
            baths = None
            size = None
            triplet_match = re.search(
                r"Apartment\s+(Studio|\d+)\s*Bed[s]?\s+(\d+)\s*Bath.*?(\d[\d,]*)\s*sqft",
                text,
                flags=re.IGNORECASE,
            )
            if triplet_match:
                beds, baths, size = triplet_match.group(1), triplet_match.group(2), triplet_match.group(3)

            property_type = "apartment"
            if "villa" in title.lower():
                property_type = "villa"
            elif "penthouse" in title.lower():
                property_type = "penthouse"

            return {
                "id": href.rstrip("/").split("/")[-1],
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
