"""Import first in offline tooling: strips live-provider credentials from the
process so the in-memory store and template paths are used, never a real
database, LLM, or WhatsApp account."""
from __future__ import annotations

import os

LIVE_ENV_KEYS = (
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_KEY",
    "GROQ_API_KEY",
    "LLM_SECONDARY_API_KEY",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
)

EVAL_WORKSPACE_ID = "00000000-0000-0000-0000-00000000e7a1"


def scrub() -> None:
    for key in LIVE_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["DATA_MODE_WHATSAPP"] = "mock"


scrub()
