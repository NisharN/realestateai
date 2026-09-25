"""Voice agent configuration served to clients (architecture §11).

One typed object derived from ``Settings`` plus live provider availability, so
the browser tunes VAD, size limits and fallbacks from the same source the
server enforces — no duplicated constants.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.services.voice_service import VoiceService


class VoiceProviders(BaseModel):
    stt: str  # groq | huggingface | none
    tts: str  # piper | browser | none
    stt_available: bool
    tts_available: bool


class VoiceConfig(BaseModel):
    providers: VoiceProviders
    heartbeat_s: float
    thinking_after_s: float
    low_confidence: float
    vad_silence_ms: int
    vad_threshold: float
    max_utterance_s: int
    max_audio_bytes: int
    max_text_chars: int
    hands_free_default: bool
    audio_formats: list[str]
    faults: list[str]


def _stt_provider(settings: Settings, voice: VoiceService) -> str:
    wanted = settings.VOICE_STT_PROVIDER.lower()
    if wanted == "none" or settings.FAULT_STT:
        return "none"
    if wanted in {"groq", "auto"} and voice.groq_client is not None:
        return "groq"
    if wanted in {"huggingface", "auto"} and voice.huggingface_client is not None:
        return "huggingface"
    return "none"


def _tts_provider(settings: Settings, voice: VoiceService, language: str) -> str:
    wanted = settings.VOICE_TTS_PROVIDER.lower()
    if wanted == "none":
        return "none"
    if wanted in {"piper", "auto"} and not settings.FAULT_TTS and voice.tts_available(language):
        return "piper"
    return "browser"


def build_voice_config(voice: VoiceService, language: str = "en") -> VoiceConfig:
    settings = get_settings()
    stt = _stt_provider(settings, voice)
    tts = _tts_provider(settings, voice, language)
    faults = [name for name, on in (("stt", settings.FAULT_STT), ("tts", settings.FAULT_TTS)) if on]
    return VoiceConfig(
        providers=VoiceProviders(stt=stt, tts=tts, stt_available=stt != "none", tts_available=tts != "none"),
        heartbeat_s=settings.VOICE_HEARTBEAT_S,
        thinking_after_s=settings.VOICE_THINKING_AFTER_S,
        low_confidence=settings.VOICE_LOW_CONFIDENCE,
        vad_silence_ms=settings.VOICE_VAD_SILENCE_MS,
        vad_threshold=settings.VOICE_VAD_THRESHOLD,
        max_utterance_s=settings.VOICE_MAX_UTTERANCE_S,
        max_audio_bytes=settings.VOICE_MAX_AUDIO_BYTES,
        max_text_chars=settings.VOICE_MAX_TEXT_CHARS,
        hands_free_default=settings.VOICE_HANDS_FREE_DEFAULT,
        audio_formats=["audio/webm", "audio/ogg", "audio/wav", "audio/mp4"],
        faults=faults,
    )
