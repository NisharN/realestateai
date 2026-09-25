"""Voice configuration: typed settings → /voice/config and the WS ready frame; STT container hints."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_lead_repository, get_property_repository
from app.main import app
from app.modules.store import reset_memory
from app.modules.tools import area_ranking
from app.modules.voice.config import build_voice_config
from app.services.voice_service import VoiceService, audio_suffix

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset():
    reset_memory()
    area_ranking.reset_cache()
    get_settings.cache_clear()
    yield
    reset_memory()
    area_ranking.reset_cache()
    get_settings.cache_clear()


def test_config_endpoint_reports_effective_settings_and_providers():
    res = client.get("/api/v1/voice/config?language=en")
    assert res.status_code == 200
    body = res.json()
    s = get_settings()
    assert body["vad_silence_ms"] == s.VOICE_VAD_SILENCE_MS
    assert body["max_audio_bytes"] == s.VOICE_MAX_AUDIO_BYTES
    assert body["low_confidence"] == s.VOICE_LOW_CONFIDENCE
    assert body["providers"]["stt"] in {"none", "groq", "huggingface"}
    assert body["providers"]["tts"] in {"none", "piper", "browser"}
    assert body["providers"]["stt_available"] == (body["providers"]["stt"] != "none")
    assert "audio/webm" in body["audio_formats"]


def test_fault_flags_disable_providers(monkeypatch):
    monkeypatch.setenv("FAULT_STT", "true")
    monkeypatch.setenv("FAULT_TTS", "true")
    get_settings.cache_clear()
    cfg = build_voice_config(VoiceService(), "en")
    assert cfg.providers.stt == "none"
    assert cfg.providers.tts == "browser"
    assert sorted(cfg.faults) == ["stt", "tts"]


def test_provider_none_overrides_availability(monkeypatch):
    monkeypatch.setenv("VOICE_TTS_PROVIDER", "none")
    get_settings.cache_clear()
    cfg = build_voice_config(VoiceService(), "en")
    assert cfg.providers.tts == "none"
    assert cfg.providers.tts_available is False


def test_ready_frame_carries_config():
    ws_id = get_settings().WORKSPACE_ID
    lead = asyncio.run(get_lead_repository(ws_id).create({"name": "V", "phone": "+971500000077", "source": "website"}))
    with client.websocket_connect(f"/api/v1/voice/conversation/{lead['id']}") as ws:
        ready = ws.receive_json()
    assert ready["type"] == "ready"
    assert ready["config"]["vad_silence_ms"] == get_settings().VOICE_VAD_SILENCE_MS
    assert ready["config"]["providers"]["tts"] in {"none", "piper", "browser"}


@pytest.mark.parametrize(
    "mime,head,expected",
    [
        ("audio/webm;codecs=opus", b"", ".webm"),
        ("audio/ogg", b"", ".ogg"),
        ("audio/mp4", b"", ".m4a"),
        ("", b"\x1aE\xdf\xa3" + b"\0" * 8, ".webm"),
        ("", b"OggS" + b"\0" * 8, ".ogg"),
        ("", b"RIFF\0\0\0\0WAVE", ".wav"),
        ("", b"\0\0\0\x18ftypisom", ".m4a"),
        ("", b"garbage", ".wav"),
    ],
)
def test_audio_suffix_from_mime_or_magic(mime, head, expected):
    assert audio_suffix(mime, head) == expected


def test_area_ranking_uses_only_communities_with_rent_and_sale_samples():
    ws_id = get_settings().WORKSPACE_ID
    repo = get_property_repository(ws_id)

    async def seed():
        for i in range(3):
            await repo.create({"title": f"s{i}", "area": "Jumeirah Village Circle", "price": 1_000_000, "listing_type": "sale", "property_type": "apartment", "bedrooms": 1})
            await repo.create({"title": f"r{i}", "area": "Jumeirah Village Circle", "price": 80_000, "listing_type": "rent", "property_type": "apartment", "bedrooms": 1})
            await repo.create({"title": f"d{i}", "area": "Downtown Dubai", "price": 3_000_000, "listing_type": "sale", "property_type": "apartment", "bedrooms": 1})
        return await area_ranking.area_ranking(ws_id)

    ranking = asyncio.run(seed())
    ids = [a.community_id for a in ranking.areas]
    assert "jvc" in ids
    assert "downtown_dubai" not in ids
    jvc = next(a for a in ranking.areas if a.community_id == "jvc")
    assert jvc.gross_yield_pct == 8.0


def test_disabled_stt_provider_is_enforced_not_just_advertised(monkeypatch):
    monkeypatch.setenv("VOICE_STT_PROVIDER", "none")
    get_settings.cache_clear()
    svc = VoiceService()
    svc.groq_client = object()  # configured, but must not be called
    assert svc.stt_providers() == []
    result = asyncio.run(svc.transcribe(b"RIFF....WAVE", "en", mime="audio/wav"))
    assert result.provider is None
    assert "disabled" in (result.error or "")
    assert build_voice_config(svc, "en").providers.stt == "none"


def test_explicit_stt_provider_skips_other_clients(monkeypatch):
    monkeypatch.setenv("VOICE_STT_PROVIDER", "huggingface")
    get_settings.cache_clear()
    svc = VoiceService()
    svc.groq_client = object()
    svc.huggingface_client = None
    assert svc.stt_providers() == []
    svc.huggingface_client = object()
    assert svc.stt_providers() == ["huggingface"]


def test_disabled_tts_provider_skips_piper(monkeypatch):
    monkeypatch.setenv("VOICE_TTS_PROVIDER", "none")
    get_settings.cache_clear()
    svc = VoiceService()
    svc._piper_model = lambda language: "/fake/model.onnx"  # type: ignore[method-assign]
    assert svc.tts_provider("en") == "none"
    assert asyncio.run(svc.text_to_speech("hello", "en")) is None


def test_area_ranking_samples_sale_and_rent_independently():
    ws_id = get_settings().WORKSPACE_ID
    repo = get_property_repository(ws_id)

    async def seed():
        for i in range(area_ranking.SAMPLE_LIMIT + 5):
            await repo.create({"title": f"r{i}", "area": "Jumeirah Village Circle", "price": 80_000, "listing_type": "rent", "property_type": "apartment", "bedrooms": 1})
        for i in range(3):
            await repo.create({"title": f"s{i}", "area": "Jumeirah Village Circle", "price": 1_000_000, "listing_type": "sale", "property_type": "apartment", "bedrooms": 1})
        return await area_ranking.area_ranking(ws_id)

    ranking = asyncio.run(seed())
    jvc = next(a for a in ranking.areas if a.community_id == "jvc")
    assert jvc.sale_samples >= 3
    assert jvc.rent_samples == area_ranking.SAMPLE_LIMIT
    assert jvc.gross_yield_pct == 8.0
