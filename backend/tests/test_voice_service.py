import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.voice_service import VoiceService


def _service(groq=None, hf=None, timeout=1.0) -> VoiceService:
    service = VoiceService.__new__(VoiceService)
    service.groq_client = groq
    service.huggingface_client = hf
    service.settings = SimpleNamespace(
        HUGGING_FACE_STT_MODEL="openai/whisper-large-v3-turbo",
        STT_TIMEOUT_S=timeout,
        TTS_TIMEOUT_S=timeout,
        PIPER_VOICE_EN="en_US-lessac-medium",
        PIPER_VOICE_AR="ar_JO-kareem-medium",
        FAULT_STT=False,
        FAULT_TTS=False,
    )
    service.piper_binary = None
    service.piper_path = "/nonexistent"
    return service


def _groq(text=None, error=None):
    create = AsyncMock(return_value=SimpleNamespace(text=text)) if error is None else AsyncMock(side_effect=error)
    return SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))


@pytest.mark.asyncio
async def test_transcribe_prefers_groq():
    hf = SimpleNamespace(automatic_speech_recognition=AsyncMock())
    service = _service(groq=_groq("Dubai Marina"), hf=hf)

    result = await service.transcribe(b"audio", "en")

    assert result.text == "Dubai Marina"
    assert result.provider == "groq"
    hf.automatic_speech_recognition.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcribe_falls_back_to_hugging_face_when_groq_fails():
    hf = SimpleNamespace(
        automatic_speech_recognition=AsyncMock(return_value=SimpleNamespace(text="مرسى دبي"))
    )
    service = _service(groq=_groq(error=RuntimeError("provider unavailable")), hf=hf)

    result = await service.transcribe(b"audio", "ar")

    assert result.text == "مرسى دبي"
    assert result.provider == "huggingface"
    hf.automatic_speech_recognition.assert_awaited_once_with(
        b"audio", model="openai/whisper-large-v3-turbo"
    )


@pytest.mark.asyncio
async def test_transcribe_times_out_and_falls_back():
    async def slow(**_kwargs):
        await asyncio.sleep(0.5)
        return SimpleNamespace(text="late")

    groq = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=slow)))
    hf = SimpleNamespace(automatic_speech_recognition=AsyncMock(return_value="fast"))
    service = _service(groq=groq, hf=hf, timeout=0.05)

    result = await service.transcribe(b"audio", "en")

    assert result.text == "fast"
    assert result.provider == "huggingface"


@pytest.mark.asyncio
async def test_transcribe_reports_error_without_any_provider():
    service = _service()

    result = await service.transcribe(b"audio", "en")

    assert result.text == ""
    assert result.error == "no STT provider configured"
    assert await service.speech_to_text(b"audio", "en") == ""


@pytest.mark.asyncio
async def test_transcribe_does_not_call_provider_for_empty_audio():
    service = _service(groq=_groq("x"))

    result = await service.transcribe(b"", "en")

    assert result.text == ""
    assert result.error == "empty audio"


@pytest.mark.asyncio
async def test_tts_returns_none_without_piper():
    service = _service()

    assert not service.tts_available("en")
    assert await service.text_to_speech("hello", "en") is None


def test_silent_wav_is_valid_pcm():
    wav = VoiceService.silent_wav(0.1, 16000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert int.from_bytes(wav[40:44], "little") == 3200


@pytest.mark.asyncio
async def test_groq_confidence_from_segments():
    from pydantic import BaseModel

    class Verbose(BaseModel):
        text: str
        segments: list[dict]

    resp = Verbose(text="Dubai Marina", segments=[{"avg_logprob": -0.2}, {"avg_logprob": -0.4}])
    create = AsyncMock(return_value=resp)
    groq = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    service = _service(groq=groq, hf=SimpleNamespace(automatic_speech_recognition=AsyncMock()))

    result = await service.transcribe(b"audio", "en")

    assert result.confidence == pytest.approx(0.7)
    assert create.await_args.kwargs["response_format"] == "verbose_json"
