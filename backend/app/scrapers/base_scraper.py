"""Base scraper with stealth and proxy support."""
import asyncio
import os
import random
import logging
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime

from playwright.async_api import async_playwright, Page, Browser
from fake_useragent import UserAgent

from app.config import get_settings

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all property scrapers."""

    def __init__(self):
        self.settings = get_settings()
        self.ua = UserAgent()
        self.proxies = self.settings.playwright_proxies
        self.browser: Optional[Browser] = None
        self.context = None
        self.persistent_context = None
        self.storage_state_path = self.settings.SCRAPER_STORAGE_STATE_PATH
        self.user_data_dir = self.settings.SCRAPER_USER_DATA_DIR
        self.profile_name = self.settings.SCRAPER_PROFILE_NAME

    async def __aenter__(self):
        """Async context manager entry."""
        self.playwright = await async_playwright().start()

        browser_args = {
            "headless": self.settings.SCRAPER_HEADLESS,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
        }
        if self.settings.SCRAPER_BROWSER_CHANNEL:
            browser_args["channel"] = self.settings.SCRAPER_BROWSER_CHANNEL

        # Add proxy if available
        if self.proxies:
            proxy = random.choice(self.proxies)
            browser_args["proxy"] = proxy

        context_args = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": self.ua.random,
            "locale": "en-US",
            "timezone_id": "Asia/Dubai",
            "geolocation": {"latitude": 25.2048, "longitude": 55.2708},
            "permissions": ["geolocation"],
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        if self.profile_name:
            browser_args["args"].append(f"--profile-directory={self.profile_name}")

        if self.user_data_dir:
            self.persistent_context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                **browser_args,
                **context_args,
            )
            self.context = self.persistent_context
            self.browser = self.context.browser
        else:
            self.browser = await self.playwright.chromium.launch(**browser_args)
            if self.storage_state_path and os.path.exists(self.storage_state_path):
                context_args["storage_state"] = self.storage_state_path
            self.context = await self.browser.new_context(**context_args)

        # Inject stealth scripts
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            window.chrome = { runtime: {} };
        """)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.context:
            await self.context.close()
        if self.browser and not self.persistent_context:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()

    async def get_page(self) -> Page:
        """Get a new page with stealth."""
        page = await self.context.new_page()

        # Additional evasion
        await page.evaluate("""
            () => {
                const newProto = navigator.__proto__;
                delete newProto.webdriver;
                navigator.__proto__ = newProto;
            }
        """)

        return page

    async def detect_block(self, page: Page, site_name: str) -> Optional[str]:
        """Detect common anti-bot / challenge pages."""
        title = (await page.title()).lower()
        url = page.url.lower()
        body = (await page.locator("body").inner_text()).lower()

        if "captcha" in title or "captchachallenge" in url or "verify your identity" in body:
            return f"{site_name} blocked the scrape with a CAPTCHA challenge"
        if "incapsula" in url or "incapsula" in body or "_incapsula_resource" in (await page.content()).lower():
            return f"{site_name} blocked the scrape with an Incapsula challenge"
        if len(body.strip()) < 50:
            return f"{site_name} returned an empty or challenge shell instead of listings"
        return None

    async def random_delay(self, min_sec: float = 2.0, max_sec: float = 5.0):
        """Random delay to mimic human behavior."""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def scroll_page(self, page: Page, scrolls: int = 3):
        """Scroll page to load lazy content."""
        for _ in range(scrolls):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await self.random_delay(1, 3)

    @abstractmethod
    async def scrape_listings(self, **kwargs) -> List[Dict[str, Any]]:
        """Scrape property listings. Must be implemented by subclass."""
        pass

    @abstractmethod
    async def scrape_detail(self, url: str) -> Dict[str, Any]:
        """Scrape single property detail. Must be implemented by subclass."""
        pass

    def normalize_property(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize scraped data to standard schema."""
        return {
            "source": self.__class__.__name__.replace("Scraper", "").lower(),
            "source_id": raw_data.get("id", ""),
            "source_url": raw_data.get("url", ""),
            "title": raw_data.get("title", ""),
            "description": raw_data.get("description", ""),
            "price": self._parse_price(raw_data.get("price", "")),
            "price_per_sqft": raw_data.get("price_per_sqft"),
            "area": raw_data.get("area", ""),
            "property_type": raw_data.get("property_type", "").lower(),
            "bedrooms": self._parse_number(raw_data.get("bedrooms", "")),
            "bathrooms": self._parse_number(raw_data.get("bathrooms", "")),
            "size_sqft": self._parse_number(raw_data.get("size", "")),
            "images": raw_data.get("images", []),
            "video_url": raw_data.get("video_url"),
            "floor_plan_url": raw_data.get("floor_plan_url"),
            "map_lat": raw_data.get("latitude"),
            "map_lng": raw_data.get("longitude"),
            "amenities": raw_data.get("amenities", []),
            "developer": raw_data.get("developer"),
            "completion_date": raw_data.get("completion_date"),
            "scraped_at": datetime.utcnow().isoformat(),
            "is_active": True,
        }

    def is_legit_listing(self, normalized: Dict[str, Any]) -> bool:
        """Reject cards that do not look like a real property listing."""
        title = (normalized.get("title") or "").strip()
        area = (normalized.get("area") or "").strip()
        price = normalized.get("price")
        url = (normalized.get("source_url") or "").strip()

        if not title or len(title) < 8:
            return False
        if not area:
            return False
        if not isinstance(price, (int, float)) or price <= 0:
            return False
        if not url.startswith("http"):
            return False
        return True

    def extract_numbers(self, text: str) -> List[int]:
        """Extract integer-like values from free-form card text."""
        if not text:
            return []
        cleaned = text.replace(",", "")
        return [int(match) for match in re.findall(r"\d+", cleaned)]

    def _parse_price(self, price_str: str) -> Optional[float]:
        """Extract numeric price from string."""
        if not price_str:
            return None
        # Remove currency symbols, commas, text
        import re
        numbers = re.findall(r'[\d,]+', str(price_str).replace(",", ""))
        if numbers:
            try:
                return float(numbers[0])
            except ValueError:
                pass
        return None

    def _parse_number(self, val) -> Optional[int]:
        """Parse number from various formats."""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return int(val)
        # Extract first number from string
        import re
        numbers = re.findall(r'\d+', str(val))
        if numbers:
            return int(numbers[0])
        return None
