"""Application configuration and settings."""
from functools import lru_cache
from typing import List, Optional

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

    # --- LLM gateway (architecture §10) ---
    # Ordered provider chain. Every call has a deadline; when the whole chain
    # fails the caller falls back to rules / templates, never to an error.
    # Standalone real-estate CRM (system of record once deployed)
    CRM_BASE_URL: str = ""
    CRM_API_KEY: str = ""
    CRM_WEBHOOK_SECRET: str = ""
    # Public base URL of this API, used to render inbound webhook URLs for connectors.
    PUBLIC_API_URL: str = "http://localhost:8000"

    LLM_PROVIDERS: str = "groq,secondary,ollama"
    LLM_SECONDARY_API_KEY: str = ""
    LLM_SECONDARY_BASE_URL: str = ""          # any OpenAI-compatible endpoint
    LLM_SECONDARY_MODEL_FAST: str = ""
    LLM_SECONDARY_MODEL_QUALITY: str = ""
    LLM_OLLAMA_BASE_URL: str = ""             # e.g. http://localhost:11434
    LLM_OLLAMA_MODEL: str = "qwen2.5:3b"
    LLM_EXTRACT_TIMEOUT_S: float = 1.5
    LLM_RESPOND_TIMEOUT_S: float = 2.5
    LLM_BREAKER_FAILURES: int = 3
    LLM_BREAKER_WINDOW_S: int = 60
    LLM_BREAKER_COOLDOWN_S: int = 120

    # --- Conversation engine ---
    TURN_DEADLINE_CHAT_S: float = 6.0
    TURN_DEADLINE_VOICE_S: float = 4.0
    STT_TIMEOUT_S: float = 2.5
    TTS_TIMEOUT_S: float = 2.0

    # --- Voice agent (architecture §11; served to the client via /voice/config) ---
    VOICE_STT_PROVIDER: str = "auto"          # auto | groq | huggingface | none
    VOICE_TTS_PROVIDER: str = "auto"          # auto | piper | browser | none
    VOICE_HEARTBEAT_S: float = 20.0
    VOICE_THINKING_AFTER_S: float = 1.2       # send `thinking` when a turn takes longer
    VOICE_LOW_CONFIDENCE: float = 0.6         # STT confidence below this is repeated back
    VOICE_VAD_SILENCE_MS: int = 900           # client stops an utterance after this much silence
    VOICE_VAD_THRESHOLD: float = 0.015        # RMS level treated as speech (0..1)
    VOICE_MAX_UTTERANCE_S: int = 30
    VOICE_MAX_AUDIO_BYTES: int = 2 * 1024 * 1024
    VOICE_MAX_TEXT_CHARS: int = 2000
    VOICE_HANDS_FREE_DEFAULT: bool = True     # re-open the mic after Ali finishes speaking
    HANDOFF_REASSIGN_MINUTES: int = 15

    # --- Demo data (mock mode only) ---
    # Extra deterministic leads/listings/viewings/follow-ups generated on top of
    # the hand-written seed. 0 keeps tests fast; 100000 is the stress-test demo.
    DEMO_SEED_SCALE: int = 0

    # --- PDPL retention (architecture §15) ---
    RETENTION_RAW_DAYS: int = 90        # raw connector payloads
    RETENTION_LEAD_DAYS: int = 730      # idle, unconverted, unassigned leads

    # --- Fault injection (pilot drills only; never set in production) ---
    FAULT_LLM_ALL: bool = False         # every LLM provider fails -> deterministic replies
    FAULT_STT: bool = False             # STT fails -> client asked to type
    FAULT_TTS: bool = False             # TTS fails -> browser speech fallback
    FAULT_DB_SLOW_MS: int = 0           # added latency per table call
    WEBHOOK_SIGNING_SECRET: str = ""          # generic push connector HMAC key
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

    # Licensed property sources (no portal scraping — BRD §1.4)
    APPROVED_FEED_URL: Optional[str] = None
    APPROVED_FEED_TOKEN: Optional[str] = None
    RAPIDAPI_UAE_REAL_ESTATE_KEY: Optional[str] = None
    RAPIDAPI_UAE_REAL_ESTATE_HOST: str = "uae-real-estate3.p.rapidapi.com"

    # Voice (Piper TTS)
    PIPER_MODEL_PATH: str = "./models/piper"
    PIPER_VOICE_EN: str = "en_US-lessac-medium"
    PIPER_VOICE_AR: str = "ar_JO-kareem-medium"

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
    def llm_providers(self) -> List[str]:
        return [p.strip().lower() for p in self.LLM_PROVIDERS.split(",") if p.strip()]

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
