"""Application configuration and settings."""
from functools import lru_cache
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    # App
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # --- Single-tenant deployment identity (see PILOT.md) ---
    # One deployment == one brokerage. The founder (acting as forward-deployed
    # engineer) sets WORKSPACE_ID at deploy time. Roles (owner/admin/agent)
    # still apply *within* this workspace; there is no cross-tenant switching,
    # so there is no X-Workspace-ID header and no shared-instance data-leak
    # surface to get wrong.
    WORKSPACE_ID: str = "00000000-0000-0000-0000-000000000001"
    WORKSPACE_NAME: str = "Demo Brokerage"

    # Demo auth: when true, requests are authenticated as a local demo owner
    # instead of requiring a real Supabase session. This is what lets the whole
    # product be walked through offline with no accounts and no keys. It is
    # force-disabled whenever APP_ENV is production (see ``demo_auth_enabled``)
    # so it can never accidentally ship to a real customer deployment.
    DEMO_AUTH: bool = True
    DEMO_ROLE: str = "owner"  # owner | admin | agent — preview a role's view

    # --- Data mode: mock by default, real opt-in per source ---
    # "mock" => serve seeded demo data, never call the external service.
    # "live" => call the real API (requires the matching credentials below).
    # Default everything to mock so the app is demoable offline with zero keys.
    DATA_MODE_PROPERTIES: str = "mock"   # mock | rapidapi | propertyfinder
    DATA_MODE_WHATSAPP: str = "mock"     # mock | live
    DATA_MODE_DLD: str = "mock"          # mock (sample rows) | live

    # Dubai Land Department open data (Dubai Pulse). Free, official, and not a
    # ToS grey area — unlike portal listing data. Only read when
    # DATA_MODE_DLD=live; the exact dataset URL depends on how the deployment
    # registers with the platform.
    DLD_TRANSACTIONS_URL: str = ""
    DLD_API_TOKEN: str = ""

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_INVITE_REDIRECT_URL: str = "http://localhost:3000/auth/callback"
    CORS_ORIGINS: str = "http://localhost:3000"

    # Groq LLM (Free tier: 30 RPM, 6K TPM, 1K RPD for most models)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"  # 1K RPD - use for quality
    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"  # 14.4K RPD - use for volume
    HUGGING_FACE_API_KEY: str = ""
    HUGGING_FACE_STT_MODEL: str = "openai/whisper-large-v3-turbo"

    # WhatsApp Business API
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: Optional[str] = "dubai-real-estate-webhook"
    META_APP_SECRET: str = ""

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    # Scraping
    PROXY_LIST: Optional[str] = None
    SCRAPER_HEADLESS: bool = True
    SCRAPER_BROWSER_CHANNEL: Optional[str] = None
    SCRAPER_STORAGE_STATE_PATH: Optional[str] = None
    SCRAPER_USER_DATA_DIR: Optional[str] = None
    SCRAPER_PROFILE_NAME: Optional[str] = None
    SCRAPER_STATE_DIR: str = "./runtime/scraper-state"
    APPROVED_FEED_URL: Optional[str] = None
    APPROVED_FEED_TOKEN: Optional[str] = None
    RAPIDAPI_UAE_REAL_ESTATE_KEY: Optional[str] = None
    RAPIDAPI_UAE_REAL_ESTATE_HOST: str = "uae-real-estate3.p.rapidapi.com"

    # Bayut and Dubizzle are actively anti-bot-protected on their public
    # browse paths (see docs/scraper_operations.md, verified July 2026) and
    # require proxies or manually-solved browser sessions to work at all.
    # Deferred per the product/market review: default OFF. The endpoints
    # still exist for whoever wants to opt back in with real proxy/session
    # infrastructure — they just aren't the default recommended path
    # anymore. Property Finder, CSV/CRM import, approved feeds, and
    # RapidAPI remain fully enabled.
    ENABLE_BAYUT_DUBIZZLE_SCRAPING: bool = False

    # Voice (Piper TTS)
    PIPER_MODEL_PATH: str = "./models/piper"
    PIPER_VOICE_EN: str = "en_US-lessac-medium"
    PIPER_VOICE_AR: str = "ar_JO-kareem-medium"

    # LangGraph
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: Optional[str] = None

    # Jobs and billing
    REDIS_URL: str = "redis://localhost:6379/0"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID: str = ""
    BILLING_SUCCESS_URL: str = "http://localhost:3000/configure?billing=success"
    BILLING_CANCEL_URL: str = "http://localhost:3000/configure?billing=cancelled"

    # --- Reminders engine thresholds (hardcoded workflow templates) ---
    # No visual workflow builder: these are the tunable knobs on the preset
    # templates instead. See PILOT.md for why the canvas was rejected.
    FOLLOWUP_DELAY_MINUTES: int = 5        # new lead -> first auto follow-up
    VIEWING_REMINDER_HOURS: int = 24       # hours before a viewing
    MANDATE_RENEWAL_LEAD_DAYS: int = 45    # nudge before mandate expiry
    LISTING_STALE_DAYS: int = 14           # listing considered stale after N days
    HOT_LEAD_SCORE: int = 60               # escalate to human at/above this

    # --- Voice safety gate (broker hard requirement) ---
    # Voice itself is deferred past the pilot, but the gate ships now so no
    # future workflow can auto-dial without a human approving the first call.
    VOICE_REQUIRE_HUMAN_APPROVAL: bool = True
    VOICE_OUTBOUND_ENABLED: bool = False

    @property
    def supabase_url(self) -> str:
        return self.SUPABASE_URL

    @property
    def supabase_key(self) -> str:
        return self.SUPABASE_KEY

    @property
    def supabase_service_key(self) -> str:
        return self.SUPABASE_SERVICE_KEY or self.SUPABASE_KEY

    @property
    def proxies(self) -> List[str]:
        if not self.PROXY_LIST:
            return []
        items = [p.strip() for p in self.PROXY_LIST.split(",") if p.strip()]
        # Reject obviously placeholder entries so dev scrapers don't break
        return [
            p
            for p in items
            if not p.lower().startswith(("http://proxy", "https://proxy"))
            and "example" not in p.lower()
        ]

    @property
    def playwright_proxies(self) -> List[Dict[str, Any]]:
        """Parse proxies into Playwright-ready dictionaries.

        Supports:
        - `http://host:port`
        - `http://user:pass@host:port`
        - `socks5://user:pass@host:port`
        """
        parsed: List[Dict[str, Any]] = []
        for raw in self.proxies:
            parsed_url = urlparse(raw)
            if not parsed_url.scheme or not parsed_url.hostname or not parsed_url.port:
                continue
            proxy: Dict[str, Any] = {
                "server": f"{parsed_url.scheme}://{parsed_url.hostname}:{parsed_url.port}"
            }
            if parsed_url.username:
                proxy["username"] = parsed_url.username
            if parsed_url.password:
                proxy["password"] = parsed_url.password
            parsed.append(proxy)
        return parsed

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def demo_auth_enabled(self) -> bool:
        """Demo auth is never allowed in production, regardless of the flag."""
        return self.DEMO_AUTH and self.APP_ENV.lower() != "production"

    @property
    def properties_mode(self) -> str:
        """Effective property source. Falls back to mock when creds are absent."""
        mode = (self.DATA_MODE_PROPERTIES or "mock").lower()
        if mode == "rapidapi" and not self.RAPIDAPI_UAE_REAL_ESTATE_KEY:
            return "mock"
        return mode

    @property
    def whatsapp_mode(self) -> str:
        """Effective WhatsApp mode. Live requires a token and phone number id."""
        mode = (self.DATA_MODE_WHATSAPP or "mock").lower()
        if mode == "live" and not (
            self.WHATSAPP_ACCESS_TOKEN and self.WHATSAPP_PHONE_NUMBER_ID
        ):
            return "mock"
        return mode


@lru_cache()
def get_settings() -> Settings:
    return Settings()
