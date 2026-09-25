"""Import first in offline tooling: pins live-provider settings to empty so
the in-memory store and template paths are used, never a real database, LLM,
or WhatsApp account. Process env wins over ``.env`` in pydantic-settings, so
these are set explicitly rather than merely removed."""
from __future__ import annotations

import os

OFFLINE_ENV = {
    "SUPABASE_URL": "",
    "SUPABASE_KEY": "",
    "SUPABASE_SERVICE_KEY": "",
    "GROQ_API_KEY": "",
    "LLM_PROVIDERS": "",
    "LLM_SECONDARY_API_KEY": "",
    "LLM_SECONDARY_BASE_URL": "",
    "LLM_OLLAMA_BASE_URL": "",
    "HUGGING_FACE_API_KEY": "",
    "WHATSAPP_ACCESS_TOKEN": "",
    "WHATSAPP_PHONE_NUMBER_ID": "",
    "DATA_MODE_WHATSAPP": "mock",
}

EVAL_WORKSPACE_ID = "00000000-0000-0000-0000-00000000e7a1"


def scrub() -> None:
    os.environ.update(OFFLINE_ENV)


scrub()
