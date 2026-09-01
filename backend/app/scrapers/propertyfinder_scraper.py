"""PropertyFinder.ae scraper for Dubai real estate."""
import logging
import re
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

            # Build query params. Property Finder's search URLs and location
            # parameter conventions change frequently; area filtering is safer
            # to apply after extraction than by composing brittle query strings.
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

            logger.info(f"Scraping PropertyFinder: {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                try:
                    await page.goto(url, wait_until="load", timeout=30000)
                except Exception:
                    return listings

            await self.random_delay(3, 6)
            block_reason = await self.detect_block(page, "Property Finder")
            if block_reason:
                logger.warning(block_reason)
                await page.close()
                return listings
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
                        normalized = self.normalize_property(listing)
                        if area and area.lower() not in (normalized.get("area") or "").lower():
                            continue
                        if self.is_legit_listing(normalized):
                            listings.append(normalized)
                except Exception as e:
                    logger.warning(f"PF card parse error: {e}")
                    continue

            for pageno in range(2, pages + 1):
                next_url = f"{url}{'&' if '?' in url else '?'}page={pageno}"
                logger.info(f"Scraping PropertyFinder page {pageno}: {next_url}")
                try:
                    await page.goto(next_url, wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    break
                await self.random_delay(3, 6)
                block_reason = await self.detect_block(page, "Property Finder")
                if block_reason:
                    logger.warning(block_reason)
                    break
                await self.scroll_page(page, scrolls=4)

                cards = []
                for selector in selectors:
                    cards = await page.query_selector_all(selector)
                    if cards:
                        break

                for card in cards[:20]:
                    try:
                        listing = await self._parse_pf_card(card)
                        if listing:
                            normalized = self.normalize_property(listing)
                            if area and area.lower() not in (normalized.get("area") or "").lower():
                                continue
                            if self.is_legit_listing(normalized):
                                listings.append(normalized)
                    except Exception as e:
                        logger.warning(f"PF page {pageno} parse error: {e}")
                        continue

            await page.close()

        except Exception as e:
            logger.error(f"PropertyFinder scrape error: {e}")

        return listings

    async def _parse_pf_card(self, card) -> Optional[Dict[str, Any]]:
        """Parse PropertyFinder card."""
        try:
            text = " ".join((await card.inner_text()).split())
            lines = [line.strip() for line in (await card.inner_text()).splitlines() if line.strip()]

            link_el = await card.query_selector('a[href^="/en/"]')
            href = await link_el.get_attribute("href") if link_el else ""
            if not href:
                all_links = await card.query_selector_all("a[href]")
                for anchor in all_links:
                    candidate = await anchor.get_attribute("href")
                    if candidate and "/en/" in candidate:
                        href = candidate
                        break
            if not href:
                return None

            title = ""
            location = ""
            for i, line in enumerate(lines):
                if line.startswith("AED") or re.fullmatch(r"\d[\d,]*", line):
                    for candidate in lines[i + 1 : i + 8]:
                        lower = candidate.lower()
                        if len(candidate) > 10 and not lower.startswith(("listed", "call", "email", "whatsapp", "area:", "delivery date:", "launch price:")):
                            title = candidate
                            break
                    for candidate in lines[i + 1 : i + 10]:
                        if "," in candidate and "dubai" in candidate.lower():
                            location = candidate
                            break
                    if title:
                        break

            price_match = re.search(r"(\d[\d,]*)\s*AED|AED\s*([\d,]+)", text, flags=re.IGNORECASE)
            if not price_match:
                for line in lines:
                    if re.fullmatch(r"\d[\d,]*", line):
                        price_match = re.match(r"(\d[\d,]*)", line)
                        break
            price = (price_match.group(1) or price_match.group(2)) if price_match else ""

            img_el = await card.query_selector('img')
            img = await img_el.get_attribute("src") if img_el else ""

            beds = None
            baths = None
            size = None
            size_match = re.search(r"Area:\s*([\d,]+)\s*ft(?:²|2)?", text, flags=re.IGNORECASE)
            if size_match:
                size = size_match.group(1)

            if location and location in lines:
                loc_index = lines.index(location)
                numeric_lines = [line for line in lines[max(0, loc_index - 4):loc_index] if re.fullmatch(r"\d+|studio", line.lower())]
                if len(numeric_lines) >= 1:
                    beds = numeric_lines[0]
                if len(numeric_lines) >= 2:
                    baths = numeric_lines[1]

            property_type = "apartment"
            if "villa" in title.lower():
                property_type = "villa"
            elif "penthouse" in title.lower():
                property_type = "penthouse"

            return {
                "id": href.rstrip("/").split("/")[-1].replace(".html", ""),
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
