"""One view of everything the agent platform is wired to.

Connectors (CRM pull / webhook / CSV), messaging channels, AI providers and the
future standalone CRM link are reported with the same shape so the Co-work page
can render a single integrations grid with health, last activity and next steps.
"""
from __future__ import annotations

from typing import Any, Literal

from app.api.admin import _public
from app.config import get_settings
from app.modules.llm import get_gateway
from app.modules.store import table
from app.modules.voice.config import build_voice_config
from app.services.voice_service import VoiceService

Status = Literal["connected", "degraded", "not_configured", "paused", "error"]


def _card(id: str, kind: str, name: str, status: Status, detail: str, *, provider: str | None = None, last_activity: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": id, "kind": kind, "name": name, "status": status, "detail": detail, "provider": provider, "last_activity": last_activity, **(extra or {})}


async def _connector_cards(workspace_id: str) -> list[dict[str, Any]]:
    rows = await table("connectors", workspace_id).select(order="created_at", desc=True, limit=200)
    cards: list[dict[str, Any]] = []
    for row in rows:
        pub = _public(row)
        st = row.get("status") or "active"
        if st == "paused":
            status: Status = "paused"
        elif st == "disabled":
            status = "not_configured"
        elif row.get("last_error") or int(row.get("consecutive_failures") or 0) > 0:
            status = "error"
        else:
            status = "connected"
        cards.append(
            _card(
                f"connector:{row['id']}",
                "connector",
                pub.get("display_name") or pub.get("type") or "Connector",
                status,
                f"{(row.get('mode') or 'push').title()} · {row.get('type')} · every {row.get('schedule_seconds') or 0}s" if row.get("mode") == "pull" else f"Push · {row.get('type')}",
                provider=row.get("type"),
                last_activity=row.get("last_success_at") or row.get("last_run_at") or row.get("updated_at"),
                extra={"connector": pub},
            )
        )
    return cards


def _platform_cards() -> list[dict[str, Any]]:
    s = get_settings()
    cards: list[dict[str, Any]] = []

    wa = s.whatsapp_mode
    cards.append(
        _card(
            "channel:whatsapp",
            "channel",
            "WhatsApp Business",
            "connected" if wa == "live" else "degraded",
            "Live Meta Cloud API" if wa == "live" else "Mock mode — messages are recorded, not delivered. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.",
            provider="meta",
        )
    )

    gw = get_gateway()
    cards.append(
        _card(
            "ai:llm",
            "ai",
            "LLM gateway",
            "connected" if gw.available else "degraded",
            "Phrasing/extraction providers online" if gw.available else "No LLM provider configured — deterministic templates only.",
            provider=",".join(p.name for p in gw.providers if p.configured()) or None,
        )
    )

    vc = build_voice_config(VoiceService())
    stt_ok, tts_ok = vc.providers.stt_available, vc.providers.tts_available
    cards.append(
        _card(
            "ai:voice",
            "ai",
            "Voice (STT / TTS)",
            "connected" if stt_ok and tts_ok else "degraded" if stt_ok or tts_ok else "not_configured",
            f"STT: {vc.providers.stt} · TTS: {vc.providers.tts}",
            provider=f"{vc.providers.stt}/{vc.providers.tts}",
        )
    )

    db = "supabase" if s.SUPABASE_URL else "memory"
    cards.append(
        _card(
            "data:store",
            "data",
            "Primary data store",
            "connected" if db == "supabase" else "degraded",
            "Supabase Postgres" if db == "supabase" else "In-memory demo store — data resets on restart.",
            provider=db,
        )
    )

    cards.append(
        _card(
            "crm:standalone",
            "crm",
            "Real-estate CRM (standalone)",
            "connected" if s.CRM_BASE_URL else "not_configured",
            "Authoritative CRM for leads, listings and deals." if s.CRM_BASE_URL else "Not linked yet — set CRM_BASE_URL and CRM_API_KEY once the CRM is deployed.",
            provider="realestate-crm",
        )
    )
    return cards


async def list_integrations(workspace_id: str) -> dict[str, Any]:
    connectors = await _connector_cards(workspace_id)
    platform = _platform_cards()
    all_cards = connectors + platform
    counts = {k: sum(1 for c in all_cards if c["status"] == k) for k in ("connected", "degraded", "not_configured", "paused", "error")}
    return {"integrations": all_cards, "counts": counts}
