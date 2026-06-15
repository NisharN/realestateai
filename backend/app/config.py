"""Application configuration and settings."""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional, List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # Groq LLM (Free tier: 30 RPM, 6K TPM, 1K RPD for most models)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"  # 1K RPD - use for quality
    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"  # 14.4K RPD - use for volume

    # WhatsApp Business API
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: Optional[str] = "dubai-real-estate-webhook"

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    # Scraping
    PROXY_LIST: Optional[str] = None
    SCRAPER_HEADLESS: bool = True

    # Voice (Piper TTS)
    PIPER_MODEL_PATH: str = "./models/piper"
    PIPER_VOICE_EN: str = "en_US-lessac-medium"
    PIPER_VOICE_AR: str = "ar_JO-kareem-medium"

    # LangGraph
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True

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
        if self.PROXY_LIST:
            return [p.strip() for p in self.PROXY_LIST.split(",")]
        return []


@lru_cache()
def get_settings() -> Settings:
    return Settings()
